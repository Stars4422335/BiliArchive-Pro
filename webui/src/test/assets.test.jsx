/**
 * AssetsView 测试：分页、筛选与详情抽屉。
 *
 * 这些交互一旦回归，用户看到的现象是"筛选没生效"或"翻页跳错"，
 * 不会报错也不会白屏，因此特别需要自动化保护。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AssetsView from "../views/AssetsView";

vi.mock("../api/client", () => ({
  api: {
    getAssets: vi.fn(),
    getAssetPoster: vi.fn().mockResolvedValue(new Blob([""])),
  },
  ApiError: class ApiError extends Error {
    constructor(message, status, data) {
      super(message);
      this.status = status;
      this.data = data;
    }
  },
}));

const PAGE_SIZE = 10;

function makeItems(count, offset = 0) {
  return Array.from({ length: count }, (_, index) => ({
    id: `BV${offset + index}`,
    bvid: `BV${offset + index}`,
    title: `资产 ${offset + index}`,
    type: "video",
    status: "active",
    p_count: 1,
    updated_at: "2026-10-01 12:00:00",
    poster_available: false,
  }));
}

function assetsResponse(total, count = PAGE_SIZE, offset = 0) {
  return { items: makeItems(count, offset), total, page: 1, page_size: PAGE_SIZE };
}

beforeEach(async () => {
  const { api } = await import("../api/client");
  api.getAssets.mockResolvedValue(assetsResponse(25));
});

describe("初始加载", () => {
  it("按默认分页参数请求", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={null} loading={false} error="" onLoad={api.getAssets} />);

    await waitFor(() => {
      expect(api.getAssets).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1, page_size: PAGE_SIZE, type: "all", status: "all" })
      );
    });
  });

  it("渲染总条数", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    expect(await screen.findByText(/共 25 条匹配记录/)).toBeInTheDocument();
  });
});

describe("分页", () => {
  it("点击下一页后请求第二页", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    await userEvent.click(await screen.findByRole("button", { name: "下一页" }));

    await waitFor(() => {
      expect(api.getAssets).toHaveBeenCalledWith(expect.objectContaining({ page: 2 }));
    });
  });

  it("第一页时上一页按钮禁用", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    expect(await screen.findByRole("button", { name: "上一页" })).toBeDisabled();
  });

  it("最后一页时下一页按钮禁用", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    // 25 条 / 每页 10 条 = 3 页
    expect(await screen.findByText("第 1 / 3 页")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).not.toBeDisabled();
  });
});

describe("筛选", () => {
  it("切换类型后回到第一页", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    await userEvent.selectOptions(await screen.findByLabelText("资产类型"), "video");

    await waitFor(() => {
      expect(api.getAssets).toHaveBeenCalledWith(
        expect.objectContaining({ type: "video", page: 1 })
      );
    });
  });

  it("切换状态后带上传参���", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    await userEvent.selectOptions(await screen.findByLabelText("资产状态"), "tombstoned");

    await waitFor(() => {
      expect(api.getAssets).toHaveBeenCalledWith(
        expect.objectContaining({ status: "tombstoned" })
      );
    });
  });

  it("搜索会带上修剪后的关键词", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    await userEvent.type(await screen.findByLabelText("搜索资产"), "  我的视频  ");

    await waitFor(() => {
      expect(api.getAssets).toHaveBeenCalledWith(
        expect.objectContaining({ query: "我的视频" })
      );
    }, { timeout: 2000 });
  });
});

describe("详情抽屉", () => {
  it("点击行打开抽屉", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    await userEvent.click(await screen.findByText("资产 0"));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("资产详情")).toBeInTheDocument();
  });

  it("Esc 关闭抽屉", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    await userEvent.click(await screen.findByText("资产 0"));
    await screen.findByRole("dialog");

    await userEvent.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("关闭按钮也能关闭抽屉", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={assetsResponse(25)} loading={false} error="" onLoad={api.getAssets} />);

    await userEvent.click(await screen.findByText("资产 0"));
    await screen.findByRole("dialog");

    await userEvent.click(screen.getByRole("button", { name: "关闭详情" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});

describe("空态与错误", () => {
  it("无结果时给出空态提示", async () => {
    const { api } = await import("../api/client");
    api.getAssets.mockResolvedValue({ items: [], total: 0, page: 1, page_size: PAGE_SIZE });
    render(<AssetsView assets={{ items: [], total: 0 }} loading={false} error="" onLoad={api.getAssets} />);

    expect(await screen.findByText("暂无资产")).toBeInTheDocument();
  });

  it("有错误时显示错误信息", async () => {
    const { api } = await import("../api/client");
    render(<AssetsView assets={null} loading={false} error="数据库不可读" onLoad={api.getAssets} />);

    expect(await screen.findByText("数据库不可读")).toBeInTheDocument();
  });
});
