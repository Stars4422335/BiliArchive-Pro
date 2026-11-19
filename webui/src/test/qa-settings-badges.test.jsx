/**
 * QA 独立验证：设置页的"生效徽章"与后端 EFFECT_METADATA 对齐。
 *
 * 与工程师的 settings.test.jsx 分开写，刻意不共用 helper：
 * 这一处是 P0 修复的用户感知面（热重载能不能生效，用户只能从徽章看出来），
 * 所以要有一份独立的、按"渲染结果"断言的证据。
 *
 * 正向：下载总开关 / 清晰度审计 / 免密码模式 → 即时生效。
 * 反例：数据库 WAL 模式 / 完整性巡检 / 输出模式 → 仍需重启。
 * 如果整张表被一律标成"即时生效"，反例立刻失败。
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SettingsView from "../views/SettingsView";
import { emptyConfig } from "../data/normalize";

vi.mock("../api/client", () => ({
  api: {
    getDiscoverFavorites: vi.fn(),
    getDiscoverCollections: vi.fn(),
  },
}));

function renderSettings() {
  render(
    <SettingsView
      config={{ ...structuredClone(emptyConfig), revision: "rev-qa" }}
      loading={false}
      error=""
      onRetry={() => {}}
      onSave={vi.fn()}
    />
  );
}

/** ToggleRow 把文字与徽章放进同一个 <strong>，徽章就是它的 .effect-badge。 */
function badgeOfToggle(labelPattern) {
  const strong = screen.getByText(labelPattern, { selector: "strong" });
  const badge = strong.querySelector(".effect-badge");
  expect(badge, `找不到 ${labelPattern} 的徽章`).not.toBeNull();
  return badge;
}

/** Field 把标题与徽章一起放进 <label class="field"><span> 里。 */
function badgeOfField(labelPattern) {
  const title = screen.getByText(labelPattern, { selector: "span" });
  const label = title.closest("label.field");
  expect(label, `${labelPattern} 不在 Field 结构里`).not.toBeNull();
  const badge = label.querySelector(".effect-badge");
  expect(badge, `找不到 ${labelPattern} 的徽章`).not.toBeNull();
  return badge;
}

describe("P0 的用户感知面：热重载项必须是「即时生效」", () => {
  it("下载总开关显示 effect-immediate + 即时生效", () => {
    renderSettings();

    const badge = badgeOfToggle(/启用下载/);

    expect(badge.className).toContain("effect-immediate");
    expect(badge.className).not.toContain("effect-restart");
    expect(badge.textContent).toBe("即时生效");
  });

  it("清晰度审计与免密码模式同为即时生效", () => {
    renderSettings();

    for (const pattern of [/清晰度审计/, /免密码模式/]) {
      const badge = badgeOfToggle(pattern);
      expect(badge.className).toContain("effect-immediate");
      expect(badge.textContent).toBe("即时生效");
    }
  });

  it("下载重试次数与字幕白名单（本次新增字段）也是即时生效", () => {
    renderSettings();

    for (const pattern of [/下载重试次数/, /字幕语言白名单/]) {
      const badge = badgeOfField(pattern);
      expect(badge.className).toContain("effect-immediate");
      expect(badge.textContent).toBe("即时生效");
    }
  });
});

describe("反例：真正需要重启的项不得被一并标成即时生效", () => {
  it("数据库 WAL 模式仍是 effect-restart + 需重启", () => {
    renderSettings();

    const badge = badgeOfToggle(/数据库 WAL 模式/);

    expect(badge.className).toContain("effect-restart");
    expect(badge.className).not.toContain("effect-immediate");
    expect(badge.textContent).toBe("需重启");
  });

  it("完整性巡检与输出模式仍是需重启", () => {
    renderSettings();

    for (const pattern of [/完整性巡检/, /输出模式/]) {
      const badge = badgeOfField(pattern);
      expect(badge.className).toContain("effect-restart");
      expect(badge.textContent).toBe("需重启");
    }
  });

  it("整页两类徽章同时存在（证明没有一律标成即时生效）", () => {
    const { container } = render(
      <SettingsView
        config={{ ...structuredClone(emptyConfig), revision: "rev-qa" }}
        loading={false}
        error=""
        onRetry={() => {}}
        onSave={vi.fn()}
      />
    );

    const immediate = container.querySelectorAll(".effect-badge.effect-immediate");
    const restart = container.querySelectorAll(".effect-badge.effect-restart");

    expect(immediate.length).toBeGreaterThan(0);
    expect(restart.length).toBeGreaterThan(0);
    // 即时生效不应吞掉整页：重启项至少有 WAL / 完整性巡检 / 输出模式 / 组件路径
    expect(restart.length).toBeGreaterThanOrEqual(3);
  });
});
