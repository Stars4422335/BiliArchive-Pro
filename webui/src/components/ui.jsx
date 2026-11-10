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
    normalized.includes("offline") || normalized.includes("not_running") ? "offline" :
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
  const [secret, setSecret] = useState("");
  const [mode, setMode] = useState("password");
  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-icon"><KeyRound size={22} /></div>
        <p className="brand-kicker">BiliArchive-Pro</p>
        <h1 id="auth-title">管理面板登录</h1>
        <p className="auth-message">{message || "请输入管理密码登录。首次使用请查看服务日志中的自动生成密码。"}</p>
        <form className="auth-form" onSubmit={(event) => { event.preventDefault(); onSubmit(secret, mode); }}>
          {mode === "password" ? (
            <>
              <label htmlFor="api-secret">管理密码</label>
              <input id="api-secret" type="password" value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="current-password" placeholder="输入管理密码" autoFocus />
            </>
          ) : (
            <>
              <label htmlFor="api-secret">环境令牌</label>
              <input id="api-secret" type="password" value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="off" placeholder="输入 BILIARCHIVE_WEB_TOKEN" autoFocus />
            </>
          )}
          <button className="button button-primary" type="submit" disabled={!secret.trim()}><KeyRound size={16} />登录</button>
        </form>
        <button className="text-button" type="button" onClick={() => { setMode(mode === "password" ? "token" : "password"); setSecret(""); }}>
          {mode === "password" ? "改用环境令牌登录" : "改用管理密码登录"}
        </button>
        {onClear && <button className="text-button" type="button" onClick={onClear}>清除已保存会话</button>}
      </section>
    </main>
  );
}

const PASSWORD_RULE = { min: 8, max: 12 };

export function passwordIssues(value) {
  const issues = [];
  if (value.length < PASSWORD_RULE.min || value.length > PASSWORD_RULE.max) issues.push(`长度需为 ${PASSWORD_RULE.min}-${PASSWORD_RULE.max} 位`);
  if (!/[0-9]/.test(value)) issues.push("需含数字");
  if (!/[A-Z]/.test(value)) issues.push("需含大写字母");
  if (!/[a-z]/.test(value)) issues.push("需含小写字母");
  if (!/[^0-9A-Za-z]/.test(value)) issues.push("需含符号");
  return issues;
}

export function PasswordChangeDialog({ required = false, onSubmit, onClose, error = "" }) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const issues = passwordIssues(newPassword);
  const confirmMismatch = confirmPassword.length > 0 && confirmPassword !== newPassword;
  const canSubmit = oldPassword.length > 0 && newPassword.length > 0 && issues.length === 0 && !confirmMismatch;
  return (
    <div className="drawer-backdrop" role="presentation">
      <aside className="detail-drawer password-dialog" role="dialog" aria-modal="true" aria-labelledby="pwd-title">
        <div className="drawer-header">
          <div>
            <p className="page-kicker">安全</p>
            <h2 id="pwd-title">{required ? "请设置新的管理密码" : "修改管理密码"}</h2>
          </div>
        </div>
        {required && <p className="auth-message">当前使用的是自动生成的初始密码，登录后必须修改。</p>}
        <form className="auth-form" onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit(oldPassword, newPassword); }}>
          <label htmlFor="pwd-old">原密码 / 初始密码</label>
          <input id="pwd-old" type="password" value={oldPassword} onChange={(event) => setOldPassword(event.target.value)} autoComplete="current-password" />
          <label htmlFor="pwd-new">新密码</label>
          <input id="pwd-new" type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" />
          <label htmlFor="pwd-confirm">确认新密码</label>
          <input id="pwd-confirm" type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" />
          {issues.length > 0 && <p className="auth-message">密码要求：{issues.join("、")}</p>}
          {confirmMismatch && <p className="auth-message">两次输入的新密码不一致。</p>}
          {error && <p className="auth-message">{error}</p>}
          <button className="button button-primary" type="submit" disabled={!canSubmit}><KeyRound size={16} />确认修改</button>
          {!required && onClose && <button className="text-button" type="button" onClick={onClose}>取消</button>}
        </form>
      </aside>
    </div>
  );
}
