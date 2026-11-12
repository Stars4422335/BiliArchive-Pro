import { Plus, Save, Search, Trash2, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { emptyConfig } from "../data/normalize";
import { api } from "../api/client";
import { ErrorState, SavedNotice, Toggle } from "../components/ui";

const clone = (value) => JSON.parse(JSON.stringify(value));

// 每个字段的生效分类：immediate 保存后由核心热重载，restart 需重启核心进程。
const EFFECT = {
  immediate: [
    ["system", "sync_watch_later"], ["system", "sync_watch_history"],
    ["system", "max_history_days"], ["system", "check_update_on_start"],
    ["system", "scan_interval_seconds"], ["system", "max_downloads_per_run"],
    ["system", "download_timeout_seconds"],
    ["network", "sync_retry_attempts"], ["network", "sync_retry_backoff_seconds"],
    ["network", "request_timeout_seconds"],
    ["archive_protection", "mark_deleted_prefix"], ["archive_protection", "tombstone_prefix"],
  ],
};

function effectOf(section, key) {
  const isImmediate =
    EFFECT.immediate.some(([s, k]) => s === section && k === key) ||
    ["followings", "wordcloud", "summary", "favorites", "sync_collections"].includes(section);
  return isImmediate ? "immediate" : "restart";
}

function EffectBadge({ section, k }) {
  const immediate = effectOf(section, k) === "immediate";
  return (
    <span className={`effect-badge effect-${immediate ? "immediate" : "restart"}`}>
      {immediate ? "即时生效" : "需重启"}
    </span>
  );
}

export default function SettingsView({ config, loading, error, onRetry, onSave }) {
  const [draft, setDraft] = useState(() => clone(config || emptyConfig));
  const [saving, setSaving] = useState(false);
  const [saveNotice, setSaveNotice] = useState("");
  const [saveError, setSaveError] = useState("");
  const [discoverBusy, setDiscoverBusy] = useState("");
  const [discoverError, setDiscoverError] = useState("");
  const [collectionMid, setCollectionMid] = useState("");
  useEffect(() => { if (config) setDraft(clone(config)); }, [config]);

  function updateSection(section, key, value) {
    setDraft((current) => ({ ...current, [section]: { ...current[section], [key]: value } }));
    setSaveNotice("");
  }
  function updateComponent(name, key, value) {
    setDraft((current) => ({ ...current, components: { ...current.components, [name]: { ...current.components[name], [key]: value } } }));
    setSaveNotice("");
  }
  function updateRow(group, index, key, value) {
    const numeric = (key === "id" || key === "mid") && value !== "" ? Number(value) : value;
    setDraft((current) => ({ ...current, [group]: current[group].map((row, rowIndex) => rowIndex === index ? { ...row, [key]: numeric } : row) }));
    setSaveNotice("");
  }
  function updateFollowingRow(index, key, value) {
    const numeric = key === "mid" && value !== "" ? Number(value) : value;
    setDraft((current) => ({ ...current, followings: { ...current.followings, list: current.followings.list.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: numeric } : row) } }));
    setSaveNotice("");
  }
  function addRow(group, row) { setDraft((current) => ({ ...current, [group]: [...current[group], row] })); setSaveNotice(""); }
  function addFollowingRow(row) { setDraft((current) => ({ ...current, followings: { ...current.followings, list: [...(current.followings.list || []), row] } })); setSaveNotice(""); }
  function removeRow(group, index) { setDraft((current) => ({ ...current, [group]: current[group].filter((_, rowIndex) => rowIndex !== index) })); setSaveNotice(""); }
  function removeFollowingRow(index) { setDraft((current) => ({ ...current, followings: { ...current.followings, list: current.followings.list.filter((_, rowIndex) => rowIndex !== index) } })); setSaveNotice(""); }

  function mergeById(existing, discovered, idKey, extraKeys) {
    // 按 id 去重合并：已存在的行保留手动修改，新发现的追加到末尾。
    const known = new Set(existing.map((row) => String(row[idKey])));
    const additions = discovered
      .filter((item) => !known.has(String(item[idKey])))
      .map((item) => {
        const row = { [idKey]: item[idKey] };
        extraKeys.forEach(([key, from]) => { row[key] = item[from]; });
        return row;
      });
    return [...existing, ...additions];
  }

  async function discoverFavorites() {
    setDiscoverBusy("favorites"); setDiscoverError("");
    try {
      const result = await api.getDiscoverFavorites();
      const items = (result.favorites || []).map((f) => ({ id: f.id, name: f.name, media_count: f.media_count }));
      setDraft((current) => ({ ...current, favorites: mergeById(current.favorites, items, "id", [["name", "name"]]) }));
    } catch (error) {
      setDiscoverError(error?.message || "自动获取收藏夹失败。");
    } finally {
      setDiscoverBusy("");
    }
  }

  async function discoverCollections() {
    setDiscoverBusy("collections"); setDiscoverError("");
    try {
      const mid = collectionMid.trim() ? Number(collectionMid.trim()) : undefined;
      const result = await api.getDiscoverCollections(mid);
      const items = (result.collections || []).map((c) => ({ id: c.id, mid: c.mid, name: c.name, total: c.total }));
      setDraft((current) => ({ ...current, sync_collections: mergeById(current.sync_collections, items, "id", [["mid", "mid"], ["name", "name"]]) }));
    } catch (error) {
      setDiscoverError(error?.message || "自动获取合集失败。");
    } finally {
      setDiscoverBusy("");
    }
  }

  async function submit(event) {
    event.preventDefault();
    setSaving(true); setSaveNotice(""); setSaveError("");
    try {
      const saved = await onSave(draft);
      const effects = saved?.effects;
      if (effects) {
        const parts = [];
        if (effects.immediate) parts.push(`${effects.immediate} 项已即时生效`);
        if (effects.restart) parts.push(`${effects.restart} 项需重启核心后生效`);
        setSaveNotice(`已保存：${parts.join("，")}`);
      } else {
        setSaveNotice("已保存，配置将随下次核心重启生效");
      }
    } catch (saveFailure) {
      setSaveError(saveFailure?.message || "设置保存失败，请重试。");
    } finally {
      setSaving(false);
    }
  }

  return <div className="view-stack"><header className="page-header"><div><p className="page-kicker">运行参数</p><h1>设置</h1><p className="page-description">调整扫描策略、媒体库输出与全部同步来源。标注「即时生效」的项保存后自动热重载；「需重启」的项在核心重启后生效。</p></div><div className="header-actions">{saveNotice && <SavedNotice>{saveNotice}</SavedNotice>}<button className="button button-primary" type="submit" form="settings-form" disabled={loading || saving}><Save size={16} />{saving ? "保存中…" : "保存设置"}</button></div></header>
    {loading && !config && <div className="state-block">正在加载设置…</div>}
    {error && <ErrorState message={error} onRetry={onRetry} />}
    {saveError && <ErrorState message={saveError} />}
    {config && <form id="settings-form" className="settings-form" onSubmit={submit}>
      <SettingsSection title="运行设置" description="扫描周期、下载边界与媒体库输出。"><div className="form-grid">
        <Field label={<>磁盘保护阈值（GB）<EffectBadge section="system" k="min_disk_gb" /></>}><input type="number" min="0" max="1000000" step="0.1" required value={draft.system.min_disk_gb} onChange={(event) => updateSection("system", "min_disk_gb", Number(event.target.value))} /></Field>
        <Field label={<>扫描间隔（秒）<EffectBadge section="system" k="scan_interval_seconds" /></>}><input type="number" min="60" max="2678400" required value={draft.system.scan_interval_seconds} onChange={(event) => updateSection("system", "scan_interval_seconds", Number(event.target.value))} /></Field>
        <Field label={<>单轮下载上限<EffectBadge section="system" k="max_downloads_per_run" /></>} hint="0 表示不限制"><input type="number" min="0" max="1000000" required value={draft.system.max_downloads_per_run} onChange={(event) => updateSection("system", "max_downloads_per_run", Number(event.target.value))} /></Field>
        <Field label={<>单项下载超时（秒）<EffectBadge section="system" k="download_timeout_seconds" /></>} hint="0 表示不限制"><input type="number" min="0" max="604800" required value={draft.system.download_timeout_seconds} onChange={(event) => updateSection("system", "download_timeout_seconds", Number(event.target.value))} /></Field>
        <Field label={<>输出模式<EffectBadge section="system" k="plex_mode" /></>}><select value={draft.system.plex_mode ? "plex" : "flat"} onChange={(event) => updateSection("system", "plex_mode", event.target.value === "plex")}><option value="plex">Plex 分季模式</option><option value="flat">平铺模式</option></select></Field>
        <Field label={<>完整性巡检<EffectBadge section="system" k="verify_integrity" /></>} hint="抽样校验已归档文件是否损坏"><select value={draft.system.verify_integrity || "light"} onChange={(event) => updateSection("system", "verify_integrity", event.target.value)}><option value="off">关闭</option><option value="light">轻度抽样</option><option value="full">全量校验</option></select></Field>
        <Field label={<>历史保留天数<EffectBadge section="system" k="max_history_days" /></>} hint="0 表示永久保留"><input type="number" min="0" max="3650" required value={draft.system.max_history_days ?? 0} onChange={(event) => updateSection("system", "max_history_days", Number(event.target.value))} /></Field>
      </div><div className="toggle-list">
        <ToggleRow label="启用下载" description="总开关：关闭时跳过全部下载来源（仅保留巡检与命令通道）" badge={<EffectBadge section="system" k="download_enabled" />} checked={Boolean(draft.system.download_enabled)} onChange={(value) => updateSection("system", "download_enabled", value)} />
        <ToggleRow label="同步稍后再看" description="加入周期扫描" badge={<EffectBadge section="system" k="sync_watch_later" />} checked={Boolean(draft.system.sync_watch_later)} onChange={(value) => updateSection("system", "sync_watch_later", value)} />
        <ToggleRow label="同步观看历史" description="仅记录元数据，不下载视频本体" badge={<EffectBadge section="system" k="sync_watch_history" />} checked={Boolean(draft.system.sync_watch_history)} onChange={(value) => updateSection("system", "sync_watch_history", value)} />
        <ToggleRow label="清晰度审计" description="巡检时对比本地与源端清晰度，产出低清清单（操作页可确认清除重下）" badge={<EffectBadge section="system" k="quality_audit_enabled" />} checked={Boolean(draft.system.quality_audit_enabled)} onChange={(value) => updateSection("system", "quality_audit_enabled", value)} />
        <ToggleRow label="数据库 WAL 模式" description="并发读写性能更好，需重启核心" badge={<EffectBadge section="system" k="db_wal" />} checked={Boolean(draft.system.db_wal)} onChange={(value) => updateSection("system", "db_wal", value)} />
        <ToggleRow label="启动时检查组件" description="核心启动时校验 yt-dlp / FFmpeg" badge={<EffectBadge section="system" k="check_update_on_start" />} checked={Boolean(draft.system.check_update_on_start)} onChange={(value) => updateSection("system", "check_update_on_start", value)} />
      </div></SettingsSection>
      <SettingsSection title="网络设置" description="请求超时、重试与代理。"><div className="form-grid">
        <Field label={<>请求超时（秒）<EffectBadge section="network" k="request_timeout_seconds" /></>}><input type="number" min="1" max="300" required value={draft.network.request_timeout_seconds} onChange={(event) => updateSection("network", "request_timeout_seconds", Number(event.target.value))} /></Field>
        <Field label={<>同步重试次数<EffectBadge section="network" k="sync_retry_attempts" /></>}><input type="number" min="1" max="10" required value={draft.network.sync_retry_attempts} onChange={(event) => updateSection("network", "sync_retry_attempts", Number(event.target.value))} /></Field>
        <Field label={<>重试退避（秒）<EffectBadge section="network" k="sync_retry_backoff_seconds" /></>}><input type="number" min="0" max="60" step="0.1" required value={draft.network.sync_retry_backoff_seconds} onChange={(event) => updateSection("network", "sync_retry_backoff_seconds", Number(event.target.value))} /></Field>
        <Field label={<>GitHub 代理前缀<EffectBadge section="network" k="github_proxy_url" /></>} hint="组件更新加速，如 https://mirror.example.com/；留空直连"><input value={draft.network.github_proxy_url || ""} onChange={(event) => updateSection("network", "github_proxy_url", event.target.value)} placeholder="留空直连" /></Field>
      </div></SettingsSection>
      <SettingsSection title="组件路径" description="yt-dlp 与 FFmpeg 的策略和自定义路径（需重启核心）。"><div className="form-grid">
        <Field label={<>yt-dlp 策略<EffectBadge section="components" k="yt-dlp" /></>}><select value={draft.components["yt-dlp"].strategy} onChange={(event) => updateComponent("yt-dlp", "strategy", event.target.value)}><option value="auto">自动校验更新</option><option value="notify">仅提醒</option><option value="off">关闭</option></select></Field>
        <Field label={<>yt-dlp 路径<EffectBadge section="components" k="yt-dlp" /></>} hint="留空使用内置 ./bin/yt-dlp"><input value={draft.components["yt-dlp"].path || ""} onChange={(event) => updateComponent("yt-dlp", "path", event.target.value)} placeholder="./bin/yt-dlp" /></Field>
        <Field label={<>FFmpeg 策略<EffectBadge section="components" k="ffmpeg" /></>}><select value={draft.components.ffmpeg.strategy} onChange={(event) => updateComponent("ffmpeg", "strategy", event.target.value)}><option value="auto">自动校验更新</option><option value="notify">仅提醒</option><option value="off">关闭</option></select></Field>
        <Field label={<>FFmpeg 路径<EffectBadge section="components" k="ffmpeg" /></>} hint="留空使用内置 ./bin/ffmpeg"><input value={draft.components.ffmpeg.path || ""} onChange={(event) => updateComponent("ffmpeg", "path", event.target.value)} placeholder="./bin/ffmpeg" /></Field>
      </div></SettingsSection>
      <SettingsSection title="归档保护" description="源端失效记录的本地标记。"><div className="form-grid">
        <Field label={<>源端已删前缀<EffectBadge section="archive_protection" k="mark_deleted_prefix" /></>}><input maxLength="64" required value={draft.archive_protection.mark_deleted_prefix} onChange={(event) => updateSection("archive_protection", "mark_deleted_prefix", event.target.value)} /></Field>
        <Field label={<>失效墓碑前缀<EffectBadge section="archive_protection" k="tombstone_prefix" /></>}><input maxLength="64" required value={draft.archive_protection.tombstone_prefix} onChange={(event) => updateSection("archive_protection", "tombstone_prefix", event.target.value)} /></Field>
      </div></SettingsSection>
      <SettingsSection title="UP 主同步" description="关注 UP 主的投稿与专栏同步来源（即时生效）。"><div className="form-grid">
        <Field label={<>投稿同步范围<EffectBadge section="followings" k="mode" /></>} hint="list 模式只同步下方列出的 UID；all 全量同步需配合单轮下载上限"><select value={draft.followings?.mode || "off"} onChange={(event) => updateSection("followings", "mode", event.target.value)}><option value="off">关闭</option><option value="list">仅列表中的 UP 主</option><option value="all">全部关注 UP 主</option></select></Field>
        <Field label={<>专栏同步范围<EffectBadge section="followings" k="article_types" /></>}><select value={draft.followings?.article_types || "off"} onChange={(event) => updateSection("followings", "article_types", event.target.value)}><option value="off">关闭</option><option value="article">仅列表中的 UP 主</option><option value="all">全部关注 UP 主</option></select></Field>
      </div>
        <EditableRows rows={draft.followings?.list || []} group="followings" onUpdate={updateFollowingRow} onAdd={() => addFollowingRow({ mid: "", name: "" })} onRemove={removeFollowingRow} fields={[{ key: "mid", label: "UP 主 UID" }, { key: "name", label: "名称" }]} />
      </SettingsSection>
      <SettingsSection title="词云与摘要" description="弹幕词云与简介摘要的本地生成开关（即时生效）。"><div className="form-grid">
        <Field label={<>弹幕词云<EffectBadge section="wordcloud" k="enabled" /></>}><Toggle checked={Boolean(draft.wordcloud?.enabled)} onChange={(value) => updateSection("wordcloud", "enabled", value)} label="词云开关" /></Field>
        <Field label={<>词云最大词条数<EffectBadge section="wordcloud" k="max_terms" /></>}><input type="number" min="1" max="1000" required value={draft.wordcloud?.max_terms ?? 120} onChange={(event) => updateSection("wordcloud", "max_terms", Number(event.target.value))} /></Field>
        <Field label={<>视频简介摘要<EffectBadge section="summary" k="mode" /></>} hint="写入 NFO 的情节摘要字段"><select value={draft.summary?.mode || "local"} onChange={(event) => updateSection("summary", "mode", event.target.value)}><option value="off">关闭</option><option value="local">本地抽取式</option></select></Field>
        <Field label={<>摘要最大字数<EffectBadge section="summary" k="max_chars" /></>}><input type="number" min="50" max="10000" required value={draft.summary?.max_chars ?? 220} onChange={(event) => updateSection("summary", "max_chars", Number(event.target.value))} /></Field>
      </div></SettingsSection>
      <SettingsSection title="收藏夹" description="周期同步的收藏夹来源；支持从账号自动获取名称和 ID。">
        <div className="discover-bar">
          <button className="button button-secondary button-compact" type="button" disabled={Boolean(discoverBusy)} onClick={discoverFavorites}><Wand2 size={14} />{discoverBusy === "favorites" ? "获取中…" : "自动获取我的收藏夹"}</button>
          <span className="muted-text">按 ID 去重合并，不会覆盖已有行</span>
        </div>
        <EditableRows rows={draft.favorites} group="favorites" onUpdate={updateRow} onAdd={() => addRow("favorites", { id: "", name: "" })} onRemove={removeRow} fields={[{ key: "id", label: "收藏夹 ID" }, { key: "name", label: "名称" }]} />
      </SettingsSection>
      <SettingsSection title="合集" description="从 UP 主 UID 自动获取全部合集/系列的 ID 与名称。">
        <div className="discover-bar">
          <input className="discover-mid-input" type="number" min="1" placeholder="UP 主 UID（留空用登录账号）" value={collectionMid} onChange={(event) => setCollectionMid(event.target.value)} />
          <button className="button button-secondary button-compact" type="button" disabled={Boolean(discoverBusy)} onClick={discoverCollections}><Search size={14} />{discoverBusy === "collections" ? "获取中…" : "获取该 UP 主的合集"}</button>
        </div>
        {discoverError && <ErrorState message={discoverError} />}
        <EditableRows rows={draft.sync_collections} group="sync_collections" onUpdate={updateRow} onAdd={() => addRow("sync_collections", { id: "", mid: "", name: "" })} onRemove={removeRow} fields={[{ key: "id", label: "合集 ID" }, { key: "mid", label: "UP 主 UID" }, { key: "name", label: "名称" }]} />
      </SettingsSection>
    </form>}</div>;
}

function SettingsSection({ title, description, children }) { return <section className="settings-section"><div className="settings-section-heading"><div><h2>{title}</h2><p>{description}</p></div></div>{children}</section>; }
function Field({ label, hint, children }) { return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>; }
function ToggleRow({ label, description, badge, checked, onChange }) { return <div className="toggle-row"><div><strong>{label} {badge}</strong><span>{description}</span></div><Toggle checked={checked} onChange={onChange} label={label} /></div>; }
function EditableRows({ rows, group, onUpdate, onAdd, onRemove, fields }) {
  return <div className="editable-list"><div className="editable-list-head"><span>{rows.length} 行配置</span><button className="button button-secondary button-compact" type="button" onClick={onAdd}><Plus size={15} />添加一行</button></div>{rows.length === 0 ? <p className="inline-empty">尚未配置来源；可用上方「自动获取」按钮一键填充。</p> : rows.map((row, index) => <div className={`editable-row editable-row-${fields.length}`} key={`${group}-${index}`}>{fields.map((field) => <label className="inline-field" key={field.key}><span>{field.label}</span><input type={field.key === "id" || field.key === "mid" ? "number" : "text"} min={field.key === "id" || field.key === "mid" ? "1" : undefined} maxLength={field.key === "name" ? "128" : undefined} required value={row[field.key] ?? ""} onChange={(event) => onUpdate(group, index, field.key, event.target.value)} /></label>)}<button className="icon-button danger-button" type="button" aria-label={`删除第 ${index + 1} 行`} title="删除此行" onClick={() => onRemove(group, index)}><Trash2 size={16} /></button></div>)}</div>;
}
