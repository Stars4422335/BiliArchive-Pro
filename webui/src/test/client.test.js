/**
 * API 客户端测试。
 *
 * 这里是前端最容易出现"静默回归"的地方：参数拼错不会报错，
 * 只会让用户看到"筛选没生效"或"翻页跳到错误位置"。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, clearStoredToken, getStoredToken, storeToken } from "../api/client";

const originalFetch = global.fetch;

function mockFetch(payload = {}, ok = true, status = 200) {
  const spy = vi.fn().mockResolvedValue({
    ok,
    status,
    headers: { get: () => "application/json" },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  });
  global.fetch = spy;
  return spy;
}

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe("令牌存取", () => {
  it("保存后能读回", () => {
    storeToken("  abc123  ");
    expect(getStoredToken()).toBe("abc123");
  });

  it("清除后为空", () => {
    storeToken("abc");
    clearStoredToken();
    expect(getStoredToken()).toBe("");
  });
});

describe("请求头", () => {
  it("带令牌时写入 Authorization", async () => {
    storeToken("secret");
    const spy = mockFetch({ ok: true });

    await api.getHealth();

    const headers = spy.mock.calls[0][1].headers;
    expect(headers.get("Authorization")).toBe("Bearer secret");
  });

  it("无令牌时不写 Authorization", async () => {
    const spy = mockFetch({ ok: true });

    await api.getHealth();

    expect(spy.mock.calls[0][1].headers.get("Authorization")).toBeNull();
  });
});

describe("getAssets 参数拼接", () => {
  it("只拼接有意义的参数，过滤空值与 all", async () => {
    const spy = mockFetch({ items: [], total: 0 });

    await api.getAssets({ query: "", type: "all", status: "", page: 1, page_size: 10 });

    const url = spy.mock.calls[0][0];
    expect(url).toBe("/api/assets?page=1&page_size=10");
  });

  it("保留实际筛选值", async () => {
    const spy = mockFetch({ items: [], total: 0 });

    await api.getAssets({ query: "测试", type: "video", status: "active", page: 2, page_size: 20 });

    const url = new URL(spy.mock.calls[0][0], "http://localhost");
    expect(url.searchParams.get("query")).toBe("测试");
    expect(url.searchParams.get("type")).toBe("video");
    expect(url.searchParams.get("status")).toBe("active");
    expect(url.searchParams.get("page")).toBe("2");
    expect(url.searchParams.get("page_size")).toBe("20");
  });

  it("搜索词中的特殊字符被正确编码", async () => {
    const spy = mockFetch({ items: [], total: 0 });

    await api.getAssets({ query: "a&b=c", page: 1, page_size: 10 });

    const url = new URL(spy.mock.calls[0][0], "http://localhost");
    expect(url.searchParams.get("query")).toBe("a&b=c");
  });
});

describe("错误处理", () => {
  it("HTTP 错误时抛出带状态码的 ApiError", async () => {
    mockFetch({ detail: "参数不合法" }, false, 422);

    await expect(api.getConfig()).rejects.toMatchObject({
      status: 422,
      message: "参数不合法",
    });
  });

  it("网络异常时抛出状态码 0 并给出可读提示", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("boom"));

    await expect(api.getDashboard()).rejects.toMatchObject({
      status: 0,
      message: "无法连接到管理 API，请确认服务已启动。",
    });
  });

  it("非 JSON 响应按文本处理", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => "text/plain" },
      text: async () => "plain body",
    });

    await expect(api.getDashboard()).resolves.toBe("plain body");
  });
});

describe("命令下发", () => {
  it("postCommand 以 JSON 提交命令体", async () => {
    const spy = mockFetch({ id: "cmd-1", status: "pending" });

    await api.postCommand({ command: "trigger_scan" });

    const [url, options] = spy.mock.calls[0];
    expect(url).toBe("/api/commands");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ command: "trigger_scan" });
  });
});
