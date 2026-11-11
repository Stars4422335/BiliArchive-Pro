import { useCallback, useEffect, useRef, useState } from "react";
import AppShell from "./components/AppShell";
import { ApiError, api, clearStoredToken, storeToken } from "./api/client";
import { configPayload, normalizeAssets, normalizeConfig, normalizeDashboard } from "./data/normalize";
import { PasswordChangeDialog, TokenGate } from "./components/ui";
import OverviewView from "./views/OverviewView";
import AssetsView from "./views/AssetsView";
import AccountView from "./views/AccountView";
import OperationsView from "./views/OperationsView";
import SettingsView from "./views/SettingsView";

function emptyErrors() { return { dashboard: "", assets: "", config: "" }; }

export default function App() {
  const [activeView, setActiveView] = useState("overview");
  const [data, setData] = useState({ dashboard: null, assets: null, config: null });
  const [loading, setLoading] = useState({ dashboard: true, assets: false, config: true });
  const [errors, setErrors] = useState(emptyErrors);
  const [authRequired, setAuthRequired] = useState(false);
  const [authMessage, setAuthMessage] = useState("");
  const [forceChange, setForceChange] = useState(false);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const assetRequest = useRef(0);

  const requireAuthentication = useCallback((message = "登录状态无效或已过期，请重新登录。会话只保存在当前浏览器中。") => {
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
        requireAuthentication("请输入管理密码登录。首次使用请查看服务日志中的自动生成密码。");
        return;
      }
      setAuthRequired(false);
      if (health.force_change) setPasswordDialogOpen(true);
      await loadCoreData();
    } catch (error) {
      const message = error?.message || "无法连接到管理 API。";
      setLoading((current) => ({ ...current, dashboard: false, config: false }));
      setErrors((current) => ({ ...current, dashboard: message, config: message }));
    }
  }, [loadCoreData, requireAuthentication]);

  useEffect(() => { bootstrap(); }, [bootstrap]);

  async function handleTokenSubmit(secret, mode = "password") {
    if (!secret.trim()) return;
    try {
      const result = await api.login(mode === "password" ? { password: secret } : { token: secret });
      storeToken(result.session);
      setForceChange(Boolean(result.force_change));
      if (result.force_change) setPasswordDialogOpen(true);
      setAuthRequired(false);
      setAuthMessage("");
      await loadCoreData();
    } catch (error) {
      const detail = error instanceof ApiError ? error.message : "无法连接到管理 API。";
      requireAuthentication(detail);
    }
  }

  async function handlePasswordChange(oldPassword, newPassword) {
    setPasswordError("");
    try {
      const result = await api.changePassword(oldPassword, newPassword);
      storeToken(result.session);
      setForceChange(false);
      setPasswordDialogOpen(false);
      setPasswordError("");
    } catch (error) {
      setPasswordError(error instanceof ApiError ? error.message : "修改密码失败，请重试。");
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

  if (authRequired) return <TokenGate message={authMessage} onSubmit={handleTokenSubmit} onClear={() => { clearStoredToken(); setAuthMessage("已清除本地会话。"); }} />;

  return <AppShell activeView={activeView} onNavigate={setActiveView} onChangePassword={() => { setPasswordError(""); setPasswordDialogOpen(true); }}>
    {activeView === "overview" && <OverviewView dashboard={data.dashboard} loading={loading.dashboard} error={errors.dashboard} onRetry={loadCoreData} onRefresh={loadCoreData} onOpenAssets={() => setActiveView("assets")} />}
    {activeView === "assets" && <AssetsView assets={data.assets} loading={loading.assets} error={errors.assets} onLoad={loadAssets} />}
    {activeView === "account" && <AccountView requireAuthentication={requireAuthentication} />}
    {activeView === "operations" && <OperationsView requireAuthentication={requireAuthentication} />}
    {activeView === "settings" && <SettingsView config={data.config} loading={loading.config} error={errors.config} onRetry={loadCoreData} onSave={handleConfigSave} />}
    {(passwordDialogOpen || forceChange) && <PasswordChangeDialog required={forceChange} onSubmit={handlePasswordChange} onClose={forceChange ? undefined : () => { setPasswordDialogOpen(false); setPasswordError(""); }} error={passwordError} />}
  </AppShell>;
}
