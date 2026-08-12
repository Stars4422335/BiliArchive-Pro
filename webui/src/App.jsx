import { useCallback, useEffect, useRef, useState } from "react";
import AppShell from "./components/AppShell";
import { ApiError, api, clearStoredToken, storeToken } from "./api/client";
import { configPayload, normalizeAssets, normalizeConfig, normalizeDashboard } from "./data/normalize";
import { TokenGate } from "./components/ui";
import OverviewView from "./views/OverviewView";
import AssetsView from "./views/AssetsView";
import SettingsView from "./views/SettingsView";

function emptyErrors() { return { dashboard: "", assets: "", config: "" }; }

export default function App() {
  const [activeView, setActiveView] = useState("overview");
  const [data, setData] = useState({ dashboard: null, assets: null, config: null });
  const [loading, setLoading] = useState({ dashboard: true, assets: false, config: true });
  const [errors, setErrors] = useState(emptyErrors);
  const [authRequired, setAuthRequired] = useState(false);
  const [authMessage, setAuthMessage] = useState("");
  const assetRequest = useRef(0);

  const requireAuthentication = useCallback((message = "令牌无效或已过期，请重新输入。令牌只保存在当前浏览器会话中。") => {
    setAuthRequired(true);
    setAuthMessage(message);
  }, []);

  const loadCoreData = useCallback(async () => {
    setLoading((current) => ({ ...current, dashboard: true, config: true }));
    setErrors((current) => ({ ...current, dashboard: "", config: "" }));
    const results = await Promise.allSettled([api.getDashboard(), api.getConfig()]);
    const nextData = {};
    const nextErrors = { dashboard: "", config: "" };
    let unauthorized = false;
    results.forEach((result, index) => {
      const key = ["dashboard", "config"][index];
      if (result.status === "fulfilled") {
        nextData[key] = key === "dashboard" ? normalizeDashboard(result.value) : normalizeConfig(result.value);
      } else if (result.reason instanceof ApiError && result.reason.status === 401) {
        unauthorized = true;
      } else {
        nextErrors[key] = result.reason?.message || "数据加载失败。";
      }
    });
    if (Object.keys(nextData).length > 0) setData((current) => ({ ...current, ...nextData }));
    setLoading((current) => ({ ...current, dashboard: false, config: false }));
    setErrors((current) => ({ ...current, ...nextErrors }));
    if (unauthorized) requireAuthentication();
  }, [requireAuthentication]);

  const loadAssets = useCallback(async (parameters) => {
    const requestId = ++assetRequest.current;
    setLoading((current) => ({ ...current, assets: true }));
    setErrors((current) => ({ ...current, assets: "" }));
    try {
      const assets = normalizeAssets(await api.getAssets(parameters));
      if (requestId === assetRequest.current) {
        setData((current) => ({ ...current, assets }));
      }
    } catch (error) {
      if (requestId !== assetRequest.current) return;
      if (error instanceof ApiError && error.status === 401) {
        requireAuthentication();
      } else {
        setErrors((current) => ({ ...current, assets: error?.message || "资产加载失败。" }));
      }
    } finally {
      if (requestId === assetRequest.current) {
        setLoading((current) => ({ ...current, assets: false }));
      }
    }
  }, [requireAuthentication]);

  const bootstrap = useCallback(async () => {
    try {
      const health = await api.getHealth();
      if (health.auth_required && !health.authenticated) {
        setLoading((current) => ({ ...current, dashboard: false, config: false }));
        requireAuthentication("当前 API 需要管理令牌。令牌只保存在当前浏览器会话中。");
        return;
      }
      setAuthRequired(false);
      await loadCoreData();
    } catch (error) {
      const message = error?.message || "无法连接到管理 API。";
      setLoading((current) => ({ ...current, dashboard: false, config: false }));
      setErrors((current) => ({ ...current, dashboard: message, config: message }));
    }
  }, [loadCoreData, requireAuthentication]);

  useEffect(() => { bootstrap(); }, [bootstrap]);

  async function handleTokenSubmit(token) {
    if (!token.trim()) return;
    storeToken(token);
    try {
      const health = await api.getHealth();
      if (health.auth_required && !health.authenticated) {
        requireAuthentication();
        return;
      }
      setAuthRequired(false);
      await loadCoreData();
    } catch (error) {
      requireAuthentication(error?.message || "无法连接到管理 API。");
    }
  }

  async function handleConfigSave(config) {
    try {
      const savedConfig = normalizeConfig(await api.putConfig(configPayload(config)));
      setData((current) => ({ ...current, config: savedConfig }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) requireAuthentication();
      throw error;
    }
  }

  if (authRequired) return <TokenGate message={authMessage} onSubmit={handleTokenSubmit} onClear={() => { clearStoredToken(); setAuthMessage("已清除本地会话令牌。"); }} />;

  return <AppShell activeView={activeView} onNavigate={setActiveView}>
    {activeView === "overview" && <OverviewView dashboard={data.dashboard} loading={loading.dashboard} error={errors.dashboard} onRetry={loadCoreData} onRefresh={loadCoreData} onOpenAssets={() => setActiveView("assets")} />}
    {activeView === "assets" && <AssetsView assets={data.assets} loading={loading.assets} error={errors.assets} onLoad={loadAssets} />}
    {activeView === "settings" && <SettingsView config={data.config} loading={loading.config} error={errors.config} onRetry={loadCoreData} onSave={handleConfigSave} />}
  </AppShell>;
}
