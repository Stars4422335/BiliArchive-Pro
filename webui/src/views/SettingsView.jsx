import { Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { emptyConfig } from "../data/normalize";
import { ErrorState, SavedNotice, Toggle } from "../components/ui";

const clone = (value) => JSON.parse(JSON.stringify(value));

export default function SettingsView({ config, loading, error, onRetry, onSave }) {
  const [draft, setDraft] = useState(() => clone(config || emptyConfig));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");
  useEffect(() => { if (config) setDraft(clone(config)); }, [config]);

  function updateSystem(key, value) { setDraft((current) => ({ ...current, system: { ...current.system, [key]: value } })); setSaved(false); }
  function updateNetwork(key, value) { setDraft((current) => ({ ...current, network: { ...current.network, [key]: value } })); setSaved(false); }
  function updateComponent(name, strategy) { setDraft((current) => ({ ...current, components: { ...current.components, [name]: { strategy } } })); setSaved(false); }
  function updateProtection(key, value) { setDraft((current) => ({ ...current, archive_protection: { ...current.archive_protection, [key]: value } })); setSaved(false); }
  function updateRow(group, index, key, value) {
    const numeric = (key === "id" || key === "mid") && value !== "" ? Number(value) : value;
    setDraft((current) => ({ ...current, [group]: current[group].map((row, rowIndex) => rowIndex === index ? { ...row, [key]: numeric } : row) }));
    setSaved(false);
  }
  function addRow(group, row) { setDraft((current) => ({ ...current, [group]: [...current[group], row] })); setSaved(false); }
  function removeRow(group, index) { setDraft((current) => ({ ...current, [group]: current[group].filter((_, rowIndex) => rowIndex !== index) })); setSaved(false); }
  async function submit(event) { event.preventDefault(); setSaving(true); setSaved(false); setSaveError(""); try { await onSave(draft); setSaved(true); } catch (saveFailure) { setSaveError(saveFailure?.message || "设置保存失败，请重试。"); } finally { setSaving(false); } }

  return <div className="view-stack"><header className="page-header"><div><p className="page-kicker">运行参数</p><h1>设置</h1><p className="page-description">调整扫描策略、媒体库输出和同步来源。</p></div><div className="header-actions">{saved && <SavedNotice>已保存，重启核心生效</SavedNotice>}<button className="button button-primary" type="submit" form="settings-form" disabled={loading || saving}><Save size={16} />{saving ? "保存中…" : "保存设置"}</button></div></header>
    {loading && !config && <div className="state-block">正在加载设置…</div>}
    {error && <ErrorState message={error} onRetry={onRetry} />}
    {saveError && <ErrorState message={saveError} />}
    {config && <form id="settings-form" className="settings-form" onSubmit={submit}>
      <SettingsSection title="运行设置" description="扫描周期、下载边界与媒体库输出。"><div className="form-grid"><Field label="磁盘保护阈值（GB）"><input type="number" min="0" max="1000000" step="0.1" required value={draft.system.min_disk_gb} onChange={(event) => updateSystem("min_disk_gb", Number(event.target.value))} /></Field><Field label="扫描间隔（秒）"><input type="number" min="60" max="2678400" required value={draft.system.scan_interval_seconds} onChange={(event) => updateSystem("scan_interval_seconds", Number(event.target.value))} /></Field><Field label="单轮下载上限" hint="0 表示不限制"><input type="number" min="0" max="1000000" required value={draft.system.max_downloads_per_run} onChange={(event) => updateSystem("max_downloads_per_run", Number(event.target.value))} /></Field><Field label="单项下载超时（秒）" hint="0 表示不限制"><input type="number" min="0" max="604800" required value={draft.system.download_timeout_seconds} onChange={(event) => updateSystem("download_timeout_seconds", Number(event.target.value))} /></Field><Field label="输出模式"><select value={draft.system.plex_mode ? "plex" : "flat"} onChange={(event) => updateSystem("plex_mode", event.target.value === "plex")}><option value="plex">Plex 分季模式</option><option value="flat">平铺模式</option></select></Field></div><div className="toggle-list"><ToggleRow label="同步稍后再看" description="加入周期扫描" checked={draft.system.sync_watch_later} onChange={(value) => updateSystem("sync_watch_later", value)} /></div></SettingsSection>
      <SettingsSection title="网络设置" description="同步请求的超时和重试边界。"><div className="form-grid"><Field label="请求超时（秒）"><input type="number" min="1" max="300" required value={draft.network.request_timeout_seconds} onChange={(event) => updateNetwork("request_timeout_seconds", Number(event.target.value))} /></Field><Field label="同步重试次数"><input type="number" min="1" max="10" required value={draft.network.sync_retry_attempts} onChange={(event) => updateNetwork("sync_retry_attempts", Number(event.target.value))} /></Field><Field label="重试退避（秒）"><input type="number" min="0" max="60" step="0.1" required value={draft.network.sync_retry_backoff_seconds} onChange={(event) => updateNetwork("sync_retry_backoff_seconds", Number(event.target.value))} /></Field></div></SettingsSection>
      <SettingsSection title="组件策略" description="yt-dlp 与 FFmpeg 的启动检查策略。"><div className="form-grid"><Field label="yt-dlp"><select value={draft.components["yt-dlp"].strategy} onChange={(event) => updateComponent("yt-dlp", event.target.value)}><option value="auto">自动校验更新</option><option value="notify">仅提醒</option><option value="off">关闭</option></select></Field><Field label="FFmpeg"><select value={draft.components.ffmpeg.strategy} onChange={(event) => updateComponent("ffmpeg", event.target.value)}><option value="auto">自动校验更新</option><option value="notify">仅提醒</option><option value="off">关闭</option></select></Field></div></SettingsSection>
      <SettingsSection title="归档保护" description="源端失效记录的本地标记。"><div className="form-grid"><Field label="源端已删前缀"><input maxLength="64" required value={draft.archive_protection.mark_deleted_prefix} onChange={(event) => updateProtection("mark_deleted_prefix", event.target.value)} /></Field><Field label="失效墓碑前缀"><input maxLength="64" required value={draft.archive_protection.tombstone_prefix} onChange={(event) => updateProtection("tombstone_prefix", event.target.value)} /></Field></div></SettingsSection>
      <SettingsSection title="收藏夹" description="周期同步的收藏夹来源，可增删配置行。"><EditableRows rows={draft.favorites} group="favorites" onUpdate={updateRow} onAdd={() => addRow("favorites", { id: "", name: "" })} onRemove={removeRow} fields={[{ key: "id", label: "收藏夹 ID" }, { key: "name", label: "名称" }]} /></SettingsSection>
      <SettingsSection title="合集" description="合集需要同时提供合集 ID、所属 UP 主 UID 和名称。"><EditableRows rows={draft.sync_collections} group="sync_collections" onUpdate={updateRow} onAdd={() => addRow("sync_collections", { id: "", mid: "", name: "" })} onRemove={removeRow} fields={[{ key: "id", label: "合集 ID" }, { key: "mid", label: "UP 主 UID" }, { key: "name", label: "名称" }]} /></SettingsSection>
    </form>}</div>;
}

function SettingsSection({ title, description, children }) { return <section className="settings-section"><div className="settings-section-heading"><div><h2>{title}</h2><p>{description}</p></div></div>{children}</section>; }
function Field({ label, hint, children }) { return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>; }
function ToggleRow({ label, description, checked, onChange }) { return <div className="toggle-row"><div><strong>{label}</strong><span>{description}</span></div><Toggle checked={checked} onChange={onChange} label={label} /></div>; }
function EditableRows({ rows, group, onUpdate, onAdd, onRemove, fields }) {
  return <div className="editable-list"><div className="editable-list-head"><span>{rows.length} 行配置</span><button className="button button-secondary button-compact" type="button" onClick={onAdd}><Plus size={15} />添加一行</button></div>{rows.length === 0 ? <p className="inline-empty">尚未配置来源。</p> : rows.map((row, index) => <div className={`editable-row editable-row-${fields.length}`} key={`${group}-${index}`}>{fields.map((field) => <label className="inline-field" key={field.key}><span>{field.label}</span><input type={field.key === "id" || field.key === "mid" ? "number" : "text"} min={field.key === "id" || field.key === "mid" ? "1" : undefined} maxLength={field.key === "name" ? "128" : undefined} required value={row[field.key] ?? ""} onChange={(event) => onUpdate(group, index, field.key, event.target.value)} /></label>)}<button className="icon-button danger-button" type="button" aria-label={`删除第 ${index + 1} 行`} title="删除此行" onClick={() => onRemove(group, index)}><Trash2 size={16} /></button></div>)}</div>;
}
