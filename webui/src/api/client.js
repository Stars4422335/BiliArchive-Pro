const TOKEN_KEY = "biliarchive_token";

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

export function getStoredToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function storeToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearStoredToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = getStoredToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch (error) {
    throw new ApiError("无法连接到管理 API，请确认服务已启动。", 0, error);
  }

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof data === "object" && data?.detail ? data.detail : `请求失败（${response.status}）`;
    throw new ApiError(message, response.status, data);
  }
  return data;
}

async function requestBlob(path) {
  const headers = new Headers();
  const token = getStoredToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { headers });
  if (!response.ok) throw new ApiError("封面不可用", response.status, null);
  return response.blob();
}

export const api = {
  getHealth: () => request("/api/health"),
  getDashboard: () => request("/api/dashboard"),
  getAssets: (parameters = {}) => {
    const search = new URLSearchParams();
    Object.entries(parameters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "" && value !== "all") {
        search.set(key, String(value));
      }
    });
    const query = search.toString();
    return request(`/api/assets${query ? `?${query}` : ""}`);
  },
  getAssetPoster: (assetId) => requestBlob(`/api/assets/${encodeURIComponent(assetId)}/poster`),
  getConfig: () => request("/api/config"),
  putConfig: (config) => request("/api/config", { method: "PUT", body: JSON.stringify(config) }),
};
