export const DEFAULT_DOWNLOAD_RETRIES = 10;
export const MAX_DOWNLOAD_RETRIES = 50;
export const DEFAULT_SUBTITLE_LANGS = "zh-Hans,zh-CN,zh,ai-zh";

export const emptyConfig = {
  revision: "",
  system: {
    min_disk_gb: 5,
    scan_interval_seconds: 21600,
    max_downloads_per_run: 0,
    download_timeout_seconds: 7200,
    download_retries: DEFAULT_DOWNLOAD_RETRIES,
    subtitle_langs: DEFAULT_SUBTITLE_LANGS,
    plex_mode: true,
    sync_watch_later: false,
    sync_watch_history: false,
    download_enabled: false,
    quality_audit_enabled: false,
    disable_auth: false,
    max_history_days: 90,
    db_wal: false,
    verify_integrity: "light",
    check_update_on_start: false,
  },
  network: {
    request_timeout_seconds: 30,
    sync_retry_attempts: 3,
    sync_retry_backoff_seconds: 2,
    github_proxy_url: "",
  },
  components: {
    "yt-dlp": { strategy: "auto", path: "" },
    ffmpeg: { strategy: "notify", path: "" },
  },
  archive_protection: {
    mark_deleted_prefix: "[源端已删]",
    tombstone_prefix: "[失效墓碑]",
  },
  followings: { mode: "off", article_types: "off", list: [] },
  wordcloud: { enabled: false, max_terms: 60 },
  summary: { enabled: false, mode: "local", max_chars: 220 },
  favorites: [],
  sync_collections: [],
};

const statusMap = { 0: "active", 1: "tombstoned", 2: "protected" };

/**
 * 下载重试次数归一化：数字输入框清空或输入非法字符会得到 ""/NaN，
 * 直接提交会被后端（0~50 整数校验）拒绝，用户只看到一句"保存失败"。
 * 这里统一夹到 0~50 的整数，非法值回落默认值 10。
 */
export function normalizeRetries(value) {
  const raw = typeof value === "string" ? value.trim() : value;
  if (raw === "" || raw === null || raw === undefined) return DEFAULT_DOWNLOAD_RETRIES;
  const number = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(number)) return DEFAULT_DOWNLOAD_RETRIES;
  return Math.min(MAX_DOWNLOAD_RETRIES, Math.max(0, Math.trunc(number)));
}

/**
 * 语言标签格式：与后端 `Downloader._SUBTITLE_LANG_PATTERN` **近似**对齐。
 *
 * 这里刻意比后端更严（后端只限制整串 ≤200 字符，不限单项长度），所以前端
 * 产物一定能被后端接受，不会出现"UI 显示值 ≠ 引擎生效值"。
 * 放宽这条正则时**不得宽于后端的整串 200 限制**，否则会反向出现不一致。
 */
const SUBTITLE_LANG_PATTERN = /^[A-Za-z0-9_-]{1,40}$/;

/**
 * 字幕语言白名单归一化：按逗号/分号切分、逐项 trim，只保留合法语言标签，
 * 清洗后为空则回落默认白名单。
 *
 * 必须逐项校验而不是只做 trim：后端遇到任何非法项会整串回退默认，若前端
 * 把 `zh;en` 这类值原样保存并显示，用户看到的值就不是引擎实际生效的值。
 * 这里顺手把 `;` 当分隔符处理，把它归一化成后端能接受的形式。
 */
export function normalizeSubtitleLangs(value) {
  if (typeof value !== "string") return DEFAULT_SUBTITLE_LANGS;
  const langs = value
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter((part) => SUBTITLE_LANG_PATTERN.test(part));
  return langs.length ? langs.join(",") : DEFAULT_SUBTITLE_LANGS;
}

function normalizeAsset(item = {}) {
  const id = item.id || item.bvid || "";
  const status = statusMap[item.status] || statusMap[String(item.status)] || item.status || "unknown";
  return {
    ...item,
    id,
    status,
    poster_available: Boolean(item.poster_available),
    updated_at: item.updated_at || item.last_check || "",
    poster_url: item.poster_url || (id ? `/api/assets/${encodeURIComponent(id)}/poster` : ""),
  };
}

function formatBytes(value) {
  if (typeof value !== "number" || value < 0) return "-";
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.round(value / 1024)} KB`;
}

export function normalizeDashboard(payload) {
  const data = payload?.data || payload || {};
  const runtime = data.runtime || {};
  const assetStats = data.assets || {};
  const typeCounts = assetStats.type_counts || {};
  return {
    // 后端综合 runtime.json 的 status 与 stopped_at 判断核心是否在跑
    // （只留文件不算在跑，kill -9 留下的陈旧文件也不算）。
    // 前端只在字段缺失时兜底，避免把"已停止"显示成"扫描中"。
    core_running: data.core_running ?? (
      Boolean(runtime.status)
      && !runtime.stopped_at
      && !["stopped", "complete", "completed", "offline", "error", "failed"].includes(String(runtime.status || "").toLowerCase())
    ),
    stats: {
      total_assets: data.stats?.total_assets ?? assetStats.total ?? data.total_assets ?? 0,
      videos: data.stats?.videos ?? typeCounts.video ?? data.videos ?? 0,
      articles: data.stats?.articles ?? typeCounts.article ?? data.articles ?? 0,
      storage_used: data.stats?.storage_used ?? formatBytes(data.storage?.used_bytes),
      storage_free: data.stats?.storage_free ?? formatBytes(data.storage?.free_bytes),
      missing_assets: data.stats?.missing_assets ?? assetStats.status_counts?.["1"] ?? 0,
    },
    scan: {
      status: data.scan?.status || runtime.status || data.scan_status || "idle",
      last_scan_at: data.scan?.last_scan_at || runtime.updated_at || data.last_scan_at || "",
      next_scan_at: data.scan?.next_scan_at || runtime.next_scan_at || data.next_scan_at || "",
      current_source: data.scan?.current_source || runtime.source || data.current_source || "",
      current: data.scan?.progress?.current ?? data.scan?.current ?? runtime.downloaded_count ?? 0,
      total: data.scan?.progress?.total ?? data.scan?.total ?? 0,
      message: data.scan?.message || runtime.message || "",
    },
    recent_assets: (Array.isArray(data.recent_assets) ? data.recent_assets : data.recent || []).map(normalizeAsset),
  };
}

export function normalizeAssets(payload) {
  const data = payload?.data || payload || {};
  const items = Array.isArray(data) ? data : data.items || data.assets || [];
  return {
    items: items.map(normalizeAsset),
    total: data.total ?? items.length,
    page: data.page ?? 1,
    page_size: data.page_size ?? items.length,
    // The cursor of the last row: the next page can be fetched with it
    // instead of an OFFSET, so deep pages stop scanning the table.
    next_cursor: data.next_cursor || "",
  };
}

export function normalizeConfig(payload) {
  const envelope = payload?.config ? payload : payload?.data?.config ? payload.data : {};
  const data = envelope.config || payload?.data || payload || {};
  const system = { ...emptyConfig.system, ...(data.system || {}) };
  system.download_retries = normalizeRetries(system.download_retries);
  system.subtitle_langs = normalizeSubtitleLangs(system.subtitle_langs);
  return {
    revision: envelope.revision || payload?.revision || "",
    effects: payload?.effects || data.effects || null,
    system,
    network: { ...emptyConfig.network, ...(data.network || {}) },
    components: {
      "yt-dlp": { ...emptyConfig.components["yt-dlp"], ...(data.components?.["yt-dlp"] || {}) },
      ffmpeg: { ...emptyConfig.components.ffmpeg, ...(data.components?.ffmpeg || {}) },
    },
    archive_protection: {
      ...emptyConfig.archive_protection,
      ...(data.archive_protection || {}),
    },
    followings: {
      ...emptyConfig.followings,
      ...(data.followings || {}),
      list: Array.isArray(data.followings?.list) ? data.followings.list : [],
    },
    wordcloud: { ...emptyConfig.wordcloud, ...(data.wordcloud || {}) },
    summary: { ...emptyConfig.summary, ...(data.summary || {}) },
    favorites: Array.isArray(data.favorites) ? data.favorites : [],
    sync_collections: Array.isArray(data.sync_collections) ? data.sync_collections : [],
  };
}

export function configPayload(config) {
  // revision 是乐观锁；effects 是保存响应的元数据，都不属于配置本体，
  // 回传会被后端白名单校验拒绝（"不允许配置字段"）。
  const publicConfig = { ...config };
  delete publicConfig.revision;
  delete publicConfig.effects;
  return { revision: config.revision, config: publicConfig };
}

export function formatDate(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function assetType(asset) {
  return asset.type || asset.asset_type || (asset.is_article ? "article" : "video");
}

export function assetTitle(asset) {
  return asset.title || asset.name || asset.bvid || "未命名资产";
}
