"""弹幕词云生成（纯标准库，输出 SVG）。

设计取舍
--------
1. **零新依赖**：项目已有 danmaku -> ASS 的转换链路，词云沿用同一条，
   不引入 wordcloud / jieba / matplotlib。SVG 用文本拼装即可，
   也避免了位图字体在 Windows / macOS / Linux 上的渲染差异。

2. **字符二元组（bigram）而非词典分词**：弹幕是极短的高频口语，
   大量是「前」「哈哈」「打卡」「awsl」这类固定或半固定短语。
   jieba 需要词典和模型文件，对弹幕这种噪声文本收益有限；
   而二元组能自然捕获「前排」「gg」「泪目」这类模式，
   并且完全确定、无外部资源依赖。

3. **不参与完成状态判定**：词云是衍生品，生成失败只打印提示，
   绝不影响视频下载与 NFO 写入的成功语义（与孤本保护、墓碑机制
   一致：只增不减，失败不阻断）。
"""

from __future__ import annotations

import html
import math
import os
import random
import re
import xml.etree.ElementTree as ET

from app.core.secure_file import atomic_write_text


# 单条弹幕最多贡献的词数，避免一条刷屏弹幕主导整个词云
MAX_TERMS_PER_COMMENT = 6
MIN_TERM_LENGTH = 2
MAX_TERM_LENGTH = 8
DEFAULT_TERMS = 60
MAX_COMMENTS = 20000

# 弹幕里高频但无信息量的噪声词：应答词、纯符号、常见语气词。
# 原则：只滤掉「本身不携带内容」的应答与虚词，不要滤掉「前排」「沙发」
# 这类虽高频但确有语义的词——它们恰恰是词云最有价值的部分。
NOISE_TERMS = frozenset({
    "哈哈", "呵呵", "哈哈哈", "啊啊", "啊啊啊啊", "2333", "233",
    "wwwww", "www", "qwq", "awa", "awsl", "twt", "hhh",
    "路过", "学习", "观摩", "已阅", "顶",
    "什么", "怎么", "这个", "那个", "就是", "还是", "可以", "不是",
    "没有", "一个", "我们", "你们", "他们", "自己", "现在", "已经",
    "真的", "感觉", "觉得", "知道", "看到", "起来", "出来", "下去",
    "的话", "一下", "有点", "这么", "那么", "因为", "所以", "但是",
    "如果", "可能", "应该", "需要", "那样",
    "up", "UP", "Up", "uP", "yys", "ovo", "QwQ",
    "bili", "B站", "b站", "阿婆", "主厨",
})

# 纯符号、标点、空白：直接剔除，不参与分词
_PUNCTUATION = re.compile(r"[\s!-/:-@\[-`{-~　-〿＀-￯]+")
# 候选词单元：中文连续段 / 拉丁字母起始的词 / 纯数字段
_TOKEN_RUN = re.compile(r"[一-鿿]+|[A-Za-z][A-Za-z0-9_]*|\d+")
_LATIN_RUN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# 词云配色：偏亮的色相，适合深色背景；避免与媒体库封面撞色
_PALETTE = (
    "#FF6B9D", "#FFA96B", "#FFD166", "#8CE99A",
    "#66D9E8", "#74A0FF", "#B197FC", "#FF8FAB",
)


class DanmakuWordCloud:
    """从 B 站弹幕 XML 统计高频词并渲染为 SVG。"""

    def __init__(self, *, max_terms: int = DEFAULT_TERMS, seed: int | None = 20261014):
        self.max_terms = max(1, min(500, int(max_terms)))
        # 固定种子：同一份弹幕重复生成得到同样的版式，便于回归比对
        self._random = random.Random(seed)

    @staticmethod
    def extract_terms(xml_path: str | os.PathLike[str]) -> list[str]:
        """解析弹幕 XML，返回按出现次数降序的高频词列表。

        复用 DanmakuConverter.parse_comment，保证与 ASS 转换看到同一批弹幕：
        非法时间戳、非法类型、空文本的条目同样被跳过。
        """
        from app.core.danmaku import DanmakuConverter

        try:
            root = ET.parse(os.fspath(xml_path)).getroot()
        except (ET.ParseError, OSError):
            return []

        counter: dict[str, int] = {}
        for index, element in enumerate(root):
            if index >= MAX_COMMENTS:
                break
            comment = DanmakuConverter.parse_comment(element)
            if comment is None:
                continue
            for term in DanmakuWordCloud.tokenize(comment["text"]):
                counter[term] = counter.get(term, 0) + 1

        # 过滤只出现一次的长尾噪声，再按频次排序
        ranked = [
            (term, count)
            for term, count in counter.items()
            if count >= 2 or len(term) >= MIN_TERM_LENGTH + 1
        ]
        ranked.sort(key=lambda pair: (-pair[1], pair[0]))
        return [term for term, _ in ranked]

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """把一条弹幕切成候选词。

        中文串取二元组（并保留足够长的整串），英文/数字串整体保留。
        单字词只在出现频繁时才保留，避免「的」「了」这类虚词占位。
        """
        if not text:
            return []

        # 先按空白切分再逐块处理：弹幕里「GPU FOMO」「awsl 泪目」这类
        # 空格分隔的多词短语，若先删空格会被粘成一个词。
        terms: list[str] = []
        for block in str(text).split():
            cleaned = _PUNCTUATION.sub("", block)
            if not cleaned:
                continue
            for chunk in _TOKEN_RUN.findall(cleaned):
                if _LATIN_RUN.match(chunk):
                    lowered = chunk.lower()
                    # 单个拉丁字母几乎无信息量；纯数字段单独处理
                    if len(lowered) >= 2 and lowered not in NOISE_TERMS:
                        terms.append(lowered)
                    continue
                if chunk.isdigit():
                    if len(chunk) >= 2 and chunk not in NOISE_TERMS:
                        terms.append(chunk)
                    continue

                if len(chunk) == 1:
                    continue
                # 中文：整串（若不长）+ 二元组
                if len(chunk) <= MAX_TERM_LENGTH and chunk not in NOISE_TERMS:
                    terms.append(chunk)
                for index in range(len(chunk) - 1):
                    bigram = chunk[index:index + 2]
                    if bigram not in NOISE_TERMS:
                        terms.append(bigram)

        seen: set[str] = set()
        unique: list[str] = []
        for term in terms:
            if len(term) < MIN_TERM_LENGTH or term in seen:
                continue
            seen.add(term)
            unique.append(term)
            if len(unique) >= MAX_TERMS_PER_COMMENT:
                break
        return unique

    def render_svg(self, terms: list[str], *, width: int = 1200, height: int = 800) -> str:
        """把词频列表渲染成 SVG 文本。词频越高，字号越大。"""
        if not terms:
            raise ValueError("没有可渲染的词")

        selected = terms[: self.max_terms]
        # 权重按排名衰减：头部词显著更大，尾部快速收敛
        weights = [self._weight(index, len(selected)) for index in range(len(selected))]

        min_size = max(14, int(height * 0.028))
        max_size = max(min_size + 8, int(height * 0.11))

        font_sizes = [
            min_size + int((max_size - min_size) * weight)
            for weight in weights
        ]

        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#12141a"/>',
            '<title>BiliArchive-Pro 弹幕词云</title>',
        ]

        # 确定性布局：按频次从大到小依次摆放，垂直位置按黄金分割抖动
        # 制造视觉上的分散感，同时保证同一输入输出可复现
        columns = 4
        slot = height / max(1, math.ceil(len(selected) / columns))
        for index, (term, font_size) in enumerate(zip(selected, font_sizes)):
            column = index % columns
            row = index // columns
            x = (column + 0.5) * (width / columns)
            jitter = self._random.uniform(-0.28, 0.28) * (width / columns)
            x = max(60, min(width - 60, x + jitter))
            y = (row + 0.62) * slot
            y = max(font_size, min(height - font_size * 0.5, y))
            color = _PALETTE[index % len(_PALETTE)]
            parts.append(
                f'<text x="{x:.1f}" y="{y:.1f}" fill="{color}" '
                f'font-size="{font_size}" font-family="Microsoft YaHei, PingFang SC, '
                f'Noto Sans CJK SC, sans-serif" text-anchor="middle" '
                f'dominant-baseline="middle">{html.escape(term)}</text>'
            )

        parts.append("</svg>")
        return "\n".join(parts)

    @staticmethod
    def _weight(index: int, total: int) -> float:
        """把排名映射到 0~1 的权重曲线：头部词显著更大，尾部快速收敛。"""
        if total <= 1:
            return 1.0
        normalized = 1.0 - (index / (total - 1))
        # 平方让头部差距更明显
        return normalized ** 2

    def generate(
        self,
        xml_path: str | os.PathLike[str],
        output_path: str | os.PathLike[str],
    ) -> bool:
        """从弹幕 XML 生成词云 SVG。成功返回 True。

        任何一步失败都只返回 False 并打印提示，不抛出——词云是衍生品，
        不能影响媒体下载的成功判定。
        """
        terms = self.extract_terms(xml_path)
        if len(terms) < 5:
            print("[*] 弹幕内容过少，跳过词云生成")
            return False
        try:
            svg = self.render_svg(terms)
            atomic_write_text(output_path, svg)
        except (OSError, ValueError) as exc:
            print(f"[-] 词云生成失败，已跳过: {exc}")
            return False
        return True


__all__ = ["DanmakuWordCloud", "MAX_COMMENTS", "NOISE_TERMS"]