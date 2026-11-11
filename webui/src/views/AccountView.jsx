import { KeyRound, RefreshCw, UserRoundCheck, UserRoundX, Wand2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { ErrorState, LoadingState } from "../components/ui";

const POLL_INTERVAL_MS = 3000;

export default function AccountView({ requireAuthentication }) {
  const [status, setStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState("");
  const [qr, setQr] = useState(null);
  const [qrState, setQrState] = useState("idle");
  const [qrMessage, setQrMessage] = useState("");
  const [creating, setCreating] = useState(false);
  const polling = useRef(null);

  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    setStatusError("");
    try {
      setStatus(await api.getLoginStatus());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) requireAuthentication();
      else setStatusError(error?.message || "登录状态获取失败。");
    } finally {
      setStatusLoading(false);
    }
  }, [requireAuthentication]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const stopPolling = useCallback(() => {
    if (polling.current) {
      window.clearInterval(polling.current);
      polling.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  async function pollOnce(key) {
    try {
      const result = await api.getLoginQrcodeStatus(key);
      const state = result.status || "waiting";
      if (state === "scanned") { setQrState("scanned"); setQrMessage(result.message || "已扫码，请在手机上确认"); return; }
      if (state === "confirmed") { setQrState("scanned"); setQrMessage(result.message || "已确认，正在完成登录"); return; }
      if (state === "expired") { setQrState("expired"); setQrMessage(result.message || "二维码已过期，请重新生成"); stopPolling(); await loadStatus(); return; }
      if (state === "done") {
        setQrState("done");
        setQrMessage(result.account ? `登录成功：${result.account.name}（UID ${result.account.uid}）` : "登录成功");
        stopPolling();
        await loadStatus();
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) { requireAuthentication(); stopPolling(); return; }
      if (error instanceof ApiError && error.status === 422) { setQrState("expired"); setQrMessage(error.message || "会话已失效，请重新生成"); stopPolling(); return; }
      // 网络抖动不中断轮询，等下一轮。
    }
  }

  function startPolling(key) {
    stopPolling();
    polling.current = window.setInterval(() => { pollOnce(key); }, POLL_INTERVAL_MS);
  }

  async function createQrcode() {
    setCreating(true); setQrMessage(""); setQrState("loading");
    try {
      const result = await api.createLoginQrcode();
      setQr(result);
      setQrState("waiting");
      setQrMessage("请用 B 站手机 App 扫一扫（我的 → 扫一扫）");
      startPolling(result.qrcode_key);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) requireAuthentication();
      else { setQrState("failed"); setQrMessage(error?.message || "二维码申请失败。"); }
    } finally {
      setCreating(false);
    }
  }

  const stateTone = { idle: "neutral", loading: "neutral", waiting: "warning", scanned: "warning", done: "success", expired: "danger", failed: "danger" };

  return (
    <div className="view-stack">
      <header className="page-header">
        <div>
          <p className="page-kicker">B 站账号</p>
          <h1>账号</h1>
          <p className="page-description">查看登录状态并通过扫码登录更新凭据；登录成功后核心引擎下一轮自动接管。</p>
        </div>
        <div className="header-actions">
          <button className="button button-secondary button-compact" type="button" onClick={loadStatus} disabled={statusLoading}><RefreshCw size={15} />刷新状态</button>
        </div>
      </header>
      {statusLoading && !status && <LoadingState label="正在读取登录状态" />}
      {statusError && <ErrorState message={statusError} onRetry={loadStatus} />}
      {status && (
        <section className="settings-section" aria-labelledby="login-status-title">
          <div className="settings-section-heading"><div><h2 id="login-status-title">当前登录状态</h2></div></div>
          {status.logged_in ? (
            <div className="state-block state-success account-status"><UserRoundCheck size={20} aria-hidden="true" /><div><strong>{status.account?.name || "已登录"}</strong><span>UID {status.account?.uid ?? "-"} · 登录凭据有效</span></div></div>
          ) : (
            <div className="state-block state-error account-status"><UserRoundX size={20} aria-hidden="true" /><div><strong>未登录或凭据已失效</strong><span>{status.reason || "请使用下方扫码登录。"}</span></div></div>
          )}
        </section>
      )}
      <section className="settings-section" aria-labelledby="qr-login-title">
        <div className="settings-section-heading"><div><h2 id="qr-login-title">扫码登录</h2><p>在 NAS 上直接完成 B 站登录，无需宿主机 Python 环境。二维码 3 分钟内有效。</p></div></div>
        <div className="qr-login-layout">
          {qr && qrState !== "loading" && <img className="qr-image" src={qr.qr_image} alt="B 站登录二维码" />}
          {qrState === "loading" && <div className="qr-placeholder">正在生成二维码…</div>}
          {!qr && qrState !== "loading" && <div className="qr-placeholder">尚未生成二维码</div>}
          <div className="qr-side">
            <button className="button button-primary" type="button" onClick={createQrcode} disabled={creating}><Wand2 size={15} />{qrState === "waiting" || qrState === "scanned" ? "重新生成二维码" : "生成登录二维码"}</button>
            {qrMessage && <p className={`state-block qr-message state-${stateTone[qrState] || "neutral"}`}><KeyRound size={15} />{qrMessage}</p>}
          </div>
        </div>
      </section>
    </div>
  );
}
