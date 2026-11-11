/* 账号页组件测试：状态三态渲染、二维码流程状态切换、401 处理。
   所有 bilibili API 均为 mock，不发真实请求。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  api: {
    getLoginStatus: vi.fn(),
    createLoginQrcode: vi.fn(),
    getLoginQrcodeStatus: vi.fn(),
  },
  // 组件用 instanceof ApiError 判断 401，mock 必须提供同一个类
  ApiError: class ApiError extends Error {
    constructor(message, status, data) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.data = data;
    }
  },
}));

import { api, ApiError } from "../api/client";

import AccountView from "../views/AccountView";

describe("账号页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getLoginStatus.mockResolvedValue({ logged_in: false, reason: "未登录" });
    api.createLoginQrcode.mockResolvedValue({
      qrcode_key: "k1",
      qr_image: "data:image/png;base64,xxx",
      expires_in: 180,
    });
    api.getLoginQrcodeStatus.mockResolvedValue({ status: "waiting" });
  });

  it("显示未登录状态并提供扫码入口", async () => {
    render(<AccountView requireAuthentication={() => {}} />);
    expect(await screen.findByText("未登录或凭据已失效")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /生成登录二维码/ })).toBeInTheDocument();
  });

  it("已登录时显示账号昵称与 UID", async () => {
    api.getLoginStatus.mockResolvedValue({
      logged_in: true,
      account: { name: "测试账号", uid: 946974 },
    });
    render(<AccountView requireAuthentication={() => {}} />);
    expect(await screen.findByText("测试账号")).toBeInTheDocument();
    expect(screen.getByText(/UID 946974/)).toBeInTheDocument();
  });

  it("凭据失效时展示原因", async () => {
    api.getLoginStatus.mockResolvedValue({ logged_in: false, reason: "登录凭据已失效，请重新扫码" });
    render(<AccountView requireAuthentication={() => {}} />);
    expect(await screen.findByText("登录凭据已失效，请重新扫码")).toBeInTheDocument();
  });

  it("生成二维码后进入等待扫码状态", async () => {
    const user = userEvent.setup();
    render(<AccountView requireAuthentication={() => {}} />);
    await screen.findByRole("button", { name: /生成登录二维码/ });
    await user.click(screen.getByRole("button", { name: /生成登录二维码/ }));
    expect(await screen.findByAltText("B 站登录二维码")).toBeInTheDocument();
    expect(await screen.findByText(/请用 B 站手机 App 扫一扫/)).toBeInTheDocument();
    expect(api.createLoginQrcode).toHaveBeenCalledTimes(1);
  });

  it("轮询到 done 后刷新登录状态并显示成功", async () => {
    api.getLoginQrcodeStatus.mockResolvedValue({
      status: "done",
      account: { name: "测试账号", uid: 946974 },
    });
    render(<AccountView requireAuthentication={() => {}} />);
    await screen.findByRole("button", { name: /生成登录二维码/ });
    await userEvent.click(screen.getByRole("button", { name: /生成登录二维码/ }));
    await screen.findByAltText("B 站登录二维码");
    // 轮询间隔 3 秒，等待第一次轮询完成后的成功提示
    expect(await screen.findByText(/登录成功/, {}, { timeout: 8000 })).toBeInTheDocument();
  }, 15000);

  it("状态接口 401 时触发重新认证", async () => {
    const requireAuthentication = vi.fn();
    api.getLoginStatus.mockRejectedValue(new ApiError("需要登录凭据", 401, null));
    render(<AccountView requireAuthentication={requireAuthentication} />);
    await waitFor(() => expect(requireAuthentication).toHaveBeenCalled());
  });
});
