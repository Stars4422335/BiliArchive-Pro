import { Archive, Boxes, KeyRound, LayoutDashboard, Settings, ShieldCheck, Terminal, UserRound } from "lucide-react";

const navItems = [
  { id: "overview", label: "概览", icon: LayoutDashboard },
  { id: "assets", label: "资产", icon: Boxes },
  { id: "account", label: "账号", icon: UserRound },
  { id: "operations", label: "操作", icon: Terminal },
  { id: "settings", label: "设置", icon: Settings },
];

function NavItems({ activeView, onNavigate }) {
  return navItems.map(({ id, label, icon: Icon }) => (
    <button key={id} className={`nav-item ${activeView === id ? "is-active" : ""}`} type="button" onClick={() => onNavigate(id)} aria-current={activeView === id ? "page" : undefined}>
      <Icon size={18} aria-hidden="true" />
      <span>{label}</span>
    </button>
  ));
}

export default function AppShell({ activeView, onNavigate, onChangePassword, children }) {
  return (
    <div className="app-shell">
      <aside className="desktop-sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><Archive size={18} /></div>
          <div><strong>BiliArchive</strong><span>管理面板</span></div>
        </div>
        <nav className="sidebar-nav" aria-label="主导航"><NavItems activeView={activeView} onNavigate={onNavigate} /></nav>
        <div className="sidebar-footer">
          <button className="text-button sidebar-password-button" type="button" onClick={onChangePassword}><KeyRound size={14} /><span>修改密码</span></button>
          <span className="sidebar-footer-note"><ShieldCheck size={15} />本地资产保护</span>
        </div>
      </aside>
      <div className="main-column">
        <header className="mobile-header">
          <div className="brand-lockup"><div className="brand-mark"><Archive size={17} /></div><strong>BiliArchive</strong></div>
          <button className="text-button" type="button" onClick={onChangePassword}><KeyRound size={15} />改密</button>
        </header>
        <main className="page-content">{children}</main>
      </div>
      <nav className="mobile-nav" aria-label="移动端主导航"><NavItems activeView={activeView} onNavigate={onNavigate} /></nav>
    </div>
  );
}
