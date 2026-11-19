/**
 * SettingsView 测试：下载重试次数与字幕语言白名单。
 *
 * 这两个键是 yt-dlp 参数加固（v1.9.9 收尾）新增的：一旦它们没进入
 * payload、或者 NaN/脏字符串被原样提交，用户看到的现象是"保存失败"
 * 而配置实际没变，所以渲染、payload 与归一化三层都要卡住。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsView from "../views/SettingsView";
import {
  DEFAULT_DOWNLOAD_RETRIES,
  DEFAULT_SUBTITLE_LANGS,
  MAX_DOWNLOAD_RETRIES,
  emptyConfig,
  normalizeConfig,
  normalizeRetries,
  normalizeSubtitleLangs,
} from "../data/normalize";

vi.mock("../api/client", () => ({
  api: {
    getDiscoverFavorites: vi.fn(),
    getDiscoverCollections: vi.fn(),
  },
}));

const clone = (value) => JSON.parse(JSON.stringify(value));

function makeConfig(systemOverrides = {}) {
  const config = clone(emptyConfig);
  config.revision = "rev-1";
  config.system = { ...config.system, ...systemOverrides };
  return config;
}

function renderSettings(config, onSave) {
  render(
    <SettingsView
      config={config}
      loading={false}
      error=""
      onRetry={() => {}}
      onSave={onSave}
    />
  );
  return {
    retries: screen.getByLabelText(/下载重试次数/),
    langs: screen.getByLabelText(/字幕语言白名单/),
  };
}

/** 直接触发表单 submit：保存按钮通过 form 属性关联，jsdom 下不可靠。 */
function submitForm() {
  fireEvent.submit(document.getElementById("settings-form"));
}

describe("新字段渲染", () => {
  it("显示当前配置值与默认提示", () => {
    const { retries, langs } = renderSettings(
      makeConfig({ download_retries: 4, subtitle_langs: "zh-CN,en-US" }),
      vi.fn()
    );

    expect(retries).toHaveValue(4);
    expect(langs).toHaveValue("zh-CN,en-US");
    expect(screen.getByText(new RegExp(`默认 ${DEFAULT_DOWNLOAD_RETRIES}`))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(DEFAULT_SUBTITLE_LANGS))).toBeInTheDocument();
  });

  it("两个字段都标注为即时生效（与后端 EFFECT_METADATA 一致）", () => {
    const { retries, langs } = renderSettings(makeConfig(), vi.fn());

    for (const input of [retries, langs]) {
      const label = input.closest("label");
      expect(label.querySelector(".effect-immediate")).not.toBeNull();
      expect(label.textContent).toContain("即时生效");
    }
  });
});

describe("生效徽章分类", () => {
  /** ToggleRow 把 label 与徽章一起放进 <strong>，徽章 class 就是分类结果。 */
  function badgeOf(labelPattern) {
    const strong = screen.getByText(labelPattern, { selector: "strong" });
    return strong.querySelector(".effect-badge");
  }

  it("下载总开关显示即时生效（P0 修好的热重载能力不能被标成需重启）", () => {
    renderSettings(makeConfig(), vi.fn());

    const badge = badgeOf(/启用下载/);
    expect(badge).not.toBeNull();
    expect(badge.className).toContain("effect-immediate");
    expect(badge.textContent).toBe("即时生效");
  });

  it("清晰度审计与免密模式同为即时生效", () => {
    renderSettings(makeConfig(), vi.fn());

    for (const pattern of [/清晰度审计/, /免密码模式/]) {
      const badge = badgeOf(pattern);
      expect(badge).not.toBeNull();
      expect(badge.className).toContain("effect-immediate");
      expect(badge.textContent).toBe("即时生效");
    }
  });

  it("真正的重启项仍显示需重启（防止把全部字段一律当即时生效）", () => {
    renderSettings(makeConfig(), vi.fn());

    const badge = badgeOf(/数据库 WAL 模式/);
    expect(badge).not.toBeNull();
    expect(badge.className).toContain("effect-restart");
    expect(badge.textContent).toBe("需重启");
  });
});

describe("提交 payload", () => {
  let onSave;

  beforeEach(() => {
    onSave = vi.fn().mockResolvedValue({ effects: { immediate: 2, restart: 0 } });
  });

  it("修改后的两个字段进入 payload", async () => {
    const { retries, langs } = renderSettings(makeConfig(), onSave);

    fireEvent.change(retries, { target: { value: "3" } });
    fireEvent.change(langs, { target: { value: "zh-Hans,en-US" } });
    submitForm();

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const payload = onSave.mock.calls[0][0];
    expect(payload.system.download_retries).toBe(3);
    expect(payload.system.subtitle_langs).toBe("zh-Hans,en-US");
  });

  it("超上限的重试次数被夹到上限", async () => {
    const { retries } = renderSettings(makeConfig(), onSave);

    fireEvent.change(retries, { target: { value: String(MAX_DOWNLOAD_RETRIES + 10) } });
    submitForm();

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].system.download_retries).toBe(MAX_DOWNLOAD_RETRIES);
  });

  it("清空重试次数回落默认值而不是 NaN", async () => {
    const { retries } = renderSettings(makeConfig(), onSave);

    fireEvent.change(retries, { target: { value: "" } });
    submitForm();

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const payload = onSave.mock.calls[0][0].system;
    expect(payload.download_retries).toBe(DEFAULT_DOWNLOAD_RETRIES);
    expect(Number.isNaN(payload.download_retries)).toBe(false);
  });

  it("字幕白名单被 trim 并丢掉空项", async () => {
    const { langs } = renderSettings(makeConfig(), onSave);

    fireEvent.change(langs, { target: { value: "  zh-CN , ,en-US  " } });
    submitForm();

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].system.subtitle_langs).toBe("zh-CN,en-US");
  });

  it("半角分号会被归一化成后端接受的逗号分隔", async () => {
    const { langs } = renderSettings(makeConfig(), onSave);

    fireEvent.change(langs, { target: { value: "zh-Hans;en-US" } });
    submitForm();

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].system.subtitle_langs).toBe("zh-Hans,en-US");
  });

  it("空白字幕白名单回落默认值", async () => {
    const { langs } = renderSettings(makeConfig(), onSave);

    fireEvent.change(langs, { target: { value: "   " } });
    submitForm();

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].system.subtitle_langs).toBe(DEFAULT_SUBTITLE_LANGS);
  });

  it("保存按钮仍然可用", async () => {
    renderSettings(makeConfig(), onSave);
    await userEvent.click(screen.getByRole("button", { name: /保存设置/ }));
    // 按钮本身就是 submit 类型，点击后不报错即算通过（jsdom 的 form 关联由
    // submitForm 用例覆盖）；这里只确认交互链路未被打断。
    expect(screen.getByRole("button", { name: /保存设置/ })).not.toBeDisabled();
  });
});

describe("归一化函数", () => {
  it("normalizeRetries 处理空值与非数字", () => {
    expect(normalizeRetries(undefined)).toBe(DEFAULT_DOWNLOAD_RETRIES);
    expect(normalizeRetries(null)).toBe(DEFAULT_DOWNLOAD_RETRIES);
    expect(normalizeRetries("")).toBe(DEFAULT_DOWNLOAD_RETRIES);
    expect(normalizeRetries("abc")).toBe(DEFAULT_DOWNLOAD_RETRIES);
    expect(normalizeRetries(Number.NaN)).toBe(DEFAULT_DOWNLOAD_RETRIES);
  });

  it("normalizeRetries 夹取范围并取整", () => {
    expect(normalizeRetries(0)).toBe(0);
    expect(normalizeRetries("3")).toBe(3);
    expect(normalizeRetries(-5)).toBe(0);
    expect(normalizeRetries(60)).toBe(MAX_DOWNLOAD_RETRIES);
    expect(normalizeRetries(3.7)).toBe(3);
  });

  it("normalizeSubtitleLangs 只做清洗与回退", () => {
    expect(normalizeSubtitleLangs("zh-Hans")).toBe("zh-Hans");
    expect(normalizeSubtitleLangs(" zh-CN , ,en-US ")).toBe("zh-CN,en-US");
    expect(normalizeSubtitleLangs("")).toBe(DEFAULT_SUBTITLE_LANGS);
    expect(normalizeSubtitleLangs(",")).toBe(DEFAULT_SUBTITLE_LANGS);
    expect(normalizeSubtitleLangs(null)).toBe(DEFAULT_SUBTITLE_LANGS);
  });

  it("normalizeSubtitleLangs 逐项校验：非法片段丢弃而不是整串存进配置", () => {
    // 后端遇到 `zh;en` 会判定非法并整串回退默认 → 前端必须归一化成
    // 后端真正接受的形式，否则 UI 显示值与引擎生效值不一致。
    expect(normalizeSubtitleLangs("zh;en")).toBe("zh,en");
    expect(normalizeSubtitleLangs("zh-CN, ; ,en-US")).toBe("zh-CN,en-US");
    // 全部非法 → 回退默认白名单
    expect(normalizeSubtitleLangs("zh Hans,中文,$$$")).toBe(DEFAULT_SUBTITLE_LANGS);
    expect(normalizeSubtitleLangs(";")).toBe(DEFAULT_SUBTITLE_LANGS);
  });

  it("normalizeConfig 读取时也会归一化这两个字段", () => {
    // 与 GET /api/config 的响应形状一致：revision 与 config 同级。
    const config = normalizeConfig({
      revision: "r1",
      config: { system: { download_retries: "", subtitle_langs: " en-US " } },
    });

    expect(config.system.download_retries).toBe(DEFAULT_DOWNLOAD_RETRIES);
    expect(config.system.subtitle_langs).toBe("en-US");
    expect(config.revision).toBe("r1");
  });

  it("normalizeConfig 缺少这两个字段时用默认值", () => {
    const config = normalizeConfig({ config: { system: {} } });

    expect(config.system.download_retries).toBe(DEFAULT_DOWNLOAD_RETRIES);
    expect(config.system.subtitle_langs).toBe(DEFAULT_SUBTITLE_LANGS);
  });
});
