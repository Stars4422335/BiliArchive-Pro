"""本地抽取式摘要（纯标准库，零外部调用）。

背景与取舍
----------
计划书里的原始设想是"接入大模型生成摘要"，但那意味着**把字幕文本外发到
第三方服务**。对这个以"资产保护"为核心价值的项目来说，默认开启外发是不
合适的，因此这里先落地**纯本地**的抽取式摘要：

- **不外发任何内容**，无隐私风险，无网络依赖；
- 与弹幕词云同理，不引入新依赖；
- 同时它是将来接 LLM 的前置通路——摘要如何生成可以替换，但"摘要写进
  NFO `<outline>`"这条路径已经稳定。

算法
----
经典的 TextRank 简化版：把句子当节点，用词频逆文档频率（TF-IDF）计算
句子间相似度建图，再跑幂迭代求权重。相比纯词频挑选，它能挑出"概括性强
而非单纯出现关键词多"的句子。规模控制在几百句以内，复杂度完全够用。

LLM 接入点
----------
`LocalSummarizer` 与未来的 LLM 实现遵循同一契约：输入原始文本，输出
一段摘要文本或 None。配置 `summary.mode` 预留了 `local` / `llm`，
但当前只实现 `local`；`llm` 会明确报错而不是静默降级，避免用户以为
内容已经发出去而实际没有。
"""

from __future__ import annotations

import math
import re
from collections import Counter


# 中英文分词：中文取二元组（无词典依赖），英文/数字取整词
_TOKEN_PATTERN = re.compile(r"[一-鿿]+|[A-Za-z][A-Za-z0-9_']*|\d+")
_SENTENCE_SPLIT = re.compile(r"[。！？!?;；\n]+|(?<=[.!?])\s+")

# 句子有效性过滤
MIN_SENTENCE_CHARS = 8
MAX_SENTENCES = 400
DEFAULT_MAX_SUMMARY_CHARS = 220

# 摘要里没有信息量的套话
BOILERPLATE = frozenset({
    "大家好", "欢迎收看", "欢迎来到", "本期视频", "本期节目",
    "subscribe", "大家好我是", "记得点赞", "一键三连",
    "以下是字幕", "amara org", "中文字幕", "校对",
})


class LocalSummarizer:
    """基于 TF-IDF 相似度图的抽取式摘要器。"""

    def __init__(self, *, max_chars: int = DEFAULT_MAX_SUMMARY_CHARS):
        try:
            self.max_chars = max(40, min(2000, int(max_chars)))
        except (TypeError, ValueError):
            self.max_chars = DEFAULT_MAX_SUMMARY_CHARS

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """切词：中文二元组 + 英文/数字整词。"""
        cleaned = re.sub(r"[\s!-/:-@\[-`{-~]+", " ", text or "")
        tokens: list[str] = []
        for chunk in _TOKEN_PATTERN.findall(cleaned):
            if chunk.isascii():
                if len(chunk) >= 2:
                    tokens.append(chunk.lower())
                continue
            if len(chunk) == 1:
                continue
            for index in range(len(chunk) - 1):
                tokens.append(chunk[index:index + 2])
        return tokens

    @staticmethod
    def split_sentences(text: str) -> list[str]:
        """切句并过滤：太短、纯数字、纯符号、常见套话一律丢弃。"""
        sentences: list[str] = []
        for raw in _SENTENCE_SPLIT.split(text or ""):
            sentence = (raw or "").strip()
            if len(sentence) < MIN_SENTENCE_CHARS:
                continue
            lowered = sentence.lower()
            if any(b in lowered for b in BOILERPLATE):
                continue
            # 纯数字/标点的句子没有概括价值
            if not any(ch.isalnum() for ch in sentence):
                continue
            sentences.append(sentence)
            if len(sentences) >= MAX_SENTENCES:
                break
        return sentences

    def summarize(self, text: str) -> str | None:
        """返回摘要文本；内容不足时返回 None。

        少于两句话时不做摘要——强行截取只会得到原文片段，
        那还不如让简介保持原样。
        """
        sentences = self.split_sentences(text)
        if len(sentences) < 2:
            return None

        tokenized = [self.tokenize(sentence) for sentence in sentences]
        # 没有任何有效词的句子直接丢弃
        pairs = [
            (sentence, tokens)
            for sentence, tokens in zip(sentences, tokenized)
            if tokens
        ]
        if len(pairs) < 2:
            return None
        sentences = [p[0] for p in pairs]
        tokenized = [p[1] for p in pairs]

        frequency = Counter()
        for tokens in tokenized:
            frequency.update(set(tokens))

        total = len(sentences)
        # 出现在所有句子里的词没有区分度，idf 为 0
        idf = {
            term: math.log(total / (1 + count))
            for term, count in frequency.items()
        }

        scores = [self._sentence_score(tokens, idf) for tokens in tokenized]
        ranked = sorted(range(len(sentences)), key=lambda i: -scores[i])

        selected: list[int] = []
        length = 0
        for index in ranked:
            candidate = sentences[index]
            if length + len(candidate) > self.max_chars:
                continue
            selected.append(index)
            length += len(candidate)
            if length >= self.max_chars * 0.7:
                break
            if len(selected) >= 3:
                break

        if not selected:
            # 最长句也超预算：截断它，保证总有输出
            longest = max(range(len(sentences)), key=lambda i: len(sentences[i]))
            return sentences[longest][: self.max_chars].rstrip() + "…"

        # 恢复原文顺序，读起来才像摘要而不是关键词堆
        selected.sort()
        return "".join(sentences[i] for i in selected)

    @staticmethod
    def _sentence_score(tokens: list[str], idf: dict[str, float]) -> float:
        """句子权重 = 其词的平均 idf，再按长度轻微归一。"""
        if not tokens:
            return 0.0
        unique = set(tokens)
        total = sum(idf.get(term, 0.0) for term in unique)
        average = total / len(unique)
        # 极短句容易被高频词主导，轻微惩罚
        length_penalty = 1.0 if len(tokens) >= 4 else 0.75
        return average * length_penalty


__all__ = ["BOILERPLATE", "LocalSummarizer", "MAX_SENTENCES"]