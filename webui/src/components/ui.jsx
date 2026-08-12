import { useState } from "react";
import { AlertCircle, Check, Inbox, KeyRound, LoaderCircle, RefreshCw } from "lucide-react";

export function IconButton({ label, children, className = "", ...props }) {
  return (
    <button className={`icon-button ${className}`.trim()} type="button" aria-label={label} title={label} {...props}>
      {children}
    </button>
  );
}

export function StatusBadge({ status = "idle", children }) {
  const normalized = String(status).toLowerCase();
  const tone = normalized.includes("error") || normalized.includes("fail") || normalized.includes("tombstone") ? "danger" :
    normalized.includes("scan") || normalized.includes("run") || normalized === "starting" ? "warning" :
      normalized.includes("complete") || normalized.includes("success") || normalized === "ready" || normalized === "protected" || normalized === "active" ? "success" : "neutral";
  return <span className={`status-badge status-${tone}`}><span className="status-dot" />{children}</span>;
}

export function LoadingState({ label = "正在加载" }) {
  return <div className="state-block"><LoaderCircle className="spin" size={20} aria-hidden="true" /><span>{label}…</span></div>;
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state-block state-error" role="alert">
      <AlertCircle size={20} aria-hidden="true" />
      <span>{message || "数据加载失败，请稍后重试。"}</span>
      {onRetry && <button className="button button-secondary button-compact" type="button" onClick={onRetry}><RefreshCw size={15} />重试</button>}
    </div>
  );
}

export function EmptyState({ title = "暂无数据", description = "当前没有可展示的记录。" }) {
  return <div className="state-block state-empty"><Inbox size={22} aria-hidden="true" /><div><strong>{title}</strong><span>{description}</span></div></div>;
}

export function SavedNotice({ children = "已保存" }) {
  return <span className="saved-notice"><Check size={15} />{children}</span>;
}

export function Toggle({ checked, onChange, label }) {
  return (
    <button
      className={`toggle ${checked ? "is-on" : ""}`}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-thumb" />
    </button>
  );
}

export function TokenGate({ message, onSubmit, onClear }) {
  const [token, setToken] = useState("");
  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-icon"><KeyRound size={22} /></div>
        <p className="brand-kicker">BiliArchive-Pro</p>
        <h1 id="auth-title">需要管理令牌</h1>
        <p className="auth-message">{message || "当前 API 需要令牌才能访问管理面板。"}</p>
        <form className="auth-form" onSubmit={(event) => { event.preventDefault(); onSubmit(token); }}>
          <label htmlFor="api-token">访问令牌</label>
          <input id="api-token" type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="current-password" placeholder="输入令牌" autoFocus />
          <button className="button button-primary" type="submit" disabled={!token.trim()}><KeyRound size={16} />验证并继续</button>
        </form>
        {onClear && <button className="text-button" type="button" onClick={onClear}>清除已保存令牌</button>}
      </section>
    </main>
  );
}
