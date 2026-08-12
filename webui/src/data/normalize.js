export const emptyConfig = {
  revision: "",
  system: {
    min_disk_gb: 5,
    scan_interval_seconds: 21600,
    max_downloads_per_run: 0,
    download_timeout_seconds: 7200,
    plex_mode: true,
    sync_watch_later: false,
  },
  network: {
    request_timeout_seconds: 30,
    sync_retry_attempts: 3,
    sync_retry_backoff_seconds: 2,
  },
  components: {
    "yt-dlp": { strategy: "auto" },
    ffmpeg: { strategy: "notify" },
  },
  archive_protection: {
    mark_deleted_prefix: "[源端已删]",
    tombstone_prefix: "[失效墓碑]",
  },
  favorites: [],
  sync_collections: [],
};

const statusMap = { 0: "active", 1: "tombstoned", 2: "protected" };

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
  };
}

export function normalizeConfig(payload) {
  const envelope = payload?.config ? payload : payload?.data?.config ? payload.data : {};
  const data = envelope.config || payload?.data || payload || {};
  return {
    revision: envelope.revision || payload?.revision || "",
    system: { ...emptyConfig.system, ...(data.system || {}) },
    network: { ...emptyConfig.network, ...(data.network || {}) },
    components: {
      "yt-dlp": { ...emptyConfig.components["yt-dlp"], ...(data.components?.["yt-dlp"] || {}) },
      ffmpeg: { ...emptyConfig.components.ffmpeg, ...(data.components?.ffmpeg || {}) },
    },
    archive_protection: {
      ...emptyConfig.archive_protection,
      ...(data.archive_protection || {}),
    },
    favorites: Array.isArray(data.favorites) ? data.favorites : [],
    sync_collections: Array.isArray(data.sync_collections) ? data.sync_collections : [],
  };
}

export function configPayload(config) {
  const { revision, ...publicConfig } = config;
  return { revision, config: publicConfig };
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
