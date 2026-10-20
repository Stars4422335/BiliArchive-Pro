/**
 * OperationsView 测试：运维指令的二次确认流程。
 *
 * 这条流程是安全边界的一部分——重启核心与重下资产都需要用户明确确认，
 * 因此必须保证"没点确认就不会下发指令"。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OperationsView from "../views/OperationsView";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    getCommands: vi.fn(),
    postCommand: vi.fn(),
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

const EMPTY_SNAPSHOT = {
  supported: ["trigger_scan", "restart", "redownload_asset"],
  pending: [],
  history: [],
  updated_at: null,
};

beforeEach(() => {
  api.getCommands.mockResolvedValue(EMPTY_SNAPSHOT);
  api.postCommand.mockResolvedValue({ id: "cmd-1", status: "pending" });
});

describe("立即巡检", () => {
  it("点击后直接下发指令，不需要二次确认", async () => {
    const user = userEvent.setup();
    render(<OperationsView requireAuthentication={() => {}} />);

    await user.click(await screen.findByRole("button", { name: "触发巡检" }));

    await waitFor(() => {
      expect(api.postCommand).toHaveBeenCalledWith(
        expect.objectContaining({ command: "trigger_scan" })
      );
    });
  });
});

describe("重启核心的二次确认", () => {
  it("未确认前不下发任何指令", async () => {
    const user = userEvent.setup();
    render(<OperationsView requireAuthentication={() => {}} />);

    await user.click(await screen.findByRole("button", { name: "提示重启" }));

    expect(await screen.findByText(/确认提示核心重启/)).toBeInTheDocument();
    expect(api.postCommand).not.toHaveBeenCalled();
  });

  it("确认后才下发 restart 指令", async () => {
    const user = userEvent.setup();
    render(<OperationsView requireAuthentication={() => {}} />);

    await user.click(await screen.findByRole("button", { name: "提示重启" }));
    await user.click(await screen.findByRole("button", { name: "我已了解，发送指令" }));

    await waitFor(() => {
      expect(api.postCommand).toHaveBeenCalledWith(
        expect.objectContaining({ command: "restart" })
      );
    });
  });

  it("取消后不下发指令", async () => {
    const user = userEvent.setup();
    render(<OperationsView requireAuthentication={() => {}} />);

    await user.click(await screen.findByRole("button", { name: "提示重启" }));
    await user.click(await screen.findByRole("button", { name: "取消" }));

    expect(api.postCommand).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByText(/确认提示核心重启/)).not.toBeInTheDocument();
    });
  });
});

describe("重新下载的二次确认", () => {
  it("非法编号时按钮不可用", async () => {
    const user = userEvent.setup();
    render(<OperationsView requireAuthentication={() => {}} />);

    const input = await screen.findByPlaceholderText("BV1GJ411x7h7");
    await user.type(input, "../../etc/passwd");

    expect(screen.getByRole("button", { name: "重新下载" })).toBeDisabled();
    expect(api.postCommand).not.toHaveBeenCalled();
  });

  it("合法编号时点击先进确认态，不直接下发", async () => {
    const user = userEvent.setup();
    render(<OperationsView requireAuthentication={() => {}} />);

    const input = await screen.findByPlaceholderText("BV1GJ411x7h7");
    await user.type(input, "BV1GJ411x7h7");
    await user.click(screen.getByRole("button", { name: "重新下载" }));

    expect(await screen.findByText(/确认重新下载该资产/)).toBeInTheDocument();
    expect(api.postCommand).not.toHaveBeenCalled();
  });

  it("确认后携带 asset_id 下发指令", async () => {
    const user = userEvent.setup();
    render(<OperationsView requireAuthentication={() => {}} />);

    const input = await screen.findByPlaceholderText("BV1GJ411x7h7");
    await user.type(input, "BV1GJ411x7h7");
    await user.click(screen.getByRole("button", { name: "重新下载" }));
    await user.click(await screen.findByRole("button", { name: "确认重下" }));

    await waitFor(() => {
      expect(api.postCommand).toHaveBeenCalledWith(
        expect.objectContaining({
          command: "redownload_asset",
          payload: { asset_id: "BV1GJ411x7h7" },
        })
      );
    });
  });
});

describe("接口失败", () => {
  it("下发失败时显示错误提示且不崩溃", async () => {
    const user = userEvent.setup();
    api.postCommand.mockRejectedValue(new Error("服务不可用"));
    render(<OperationsView requireAuthentication={() => {}} />);

    await user.click(await screen.findByRole("button", { name: "触发巡检" }));

    // 错误提示由 catch 里的 setFeedback 异步写入，等它落定再断言
    await waitFor(() => {
      expect(screen.getByText("服务不可用")).toBeInTheDocument();
    });
  });

  it("401 时触发重新认证回调", async () => {
    const user = userEvent.setup();
    const requireAuthentication = vi.fn();
    const { ApiError } = await import("../api/client");
    api.postCommand.mockRejectedValue(new ApiError("需要令牌", 401, null));
    render(<OperationsView requireAuthentication={requireAuthentication} />);

    await user.click(await screen.findByRole("button", { name: "触发巡检" }));

    await waitFor(() => {
      expect(requireAuthentication).toHaveBeenCalled();
    });
  });
});
