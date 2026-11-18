"""R2 关键词检索：中文 bigram + 英文词，BM25 打分，纯标准库。

向量检索擅长语义相近，关键词检索擅长人名/公司名/数字这类字面命中。
两路结果在 hybrid.py 里用 RRF 融合。
"""

from __future__ import annotations

import math
import re
from collections import Counter

K1 = 1.5
B = 0.75

_CJK_RE = re.compile(r"[一-鿿]+")
_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文取相邻二字，英文/数字取小写整词。

    中文单字信息太散（“的”“了”），整句又太严，bigram 是免分词的折中。
    """
    text = (text or "").lower()
    tokens: list[str] = []
    for match in _CJK_RE.finditer(text):
        run = match.group()
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    tokens.extend(_WORD_RE.findall(text))
    return tokens


def doc_text(chunk: dict) -> str:
    """标题也算正文：中文标题常是检索的唯一中文线索。"""
    parts = (chunk.get("title_zh"), chunk.get("title"), chunk.get("text"))
    return " ".join(part for part in parts if part)


class BM25Index:
    """内存 BM25；几百到几千块直接遍历，不需要倒排表的额外复杂度。"""

    def __init__(self, chunks: list[dict]):
        self.chunks = list(chunks)
        self.tfs: list[Counter] = []
        self.lengths: list[int] = []
        document_freq: Counter = Counter()
        for chunk in self.chunks:
            tokens = tokenize(doc_text(chunk))
            term_freq = Counter(tokens)
            self.tfs.append(term_freq)
            self.lengths.append(len(tokens))
            document_freq.update(term_freq.keys())
        self.df = document_freq
        self.total = len(self.chunks)
        self.avgdl = (sum(self.lengths) / self.total) if self.total else 0.0

    def _idf(self, token: str) -> float:
        df = self.df.get(token, 0)
        if df <= 0:
            return 0.0
        return math.log(1 + (self.total - df + 0.5) / (df + 0.5))

    def search(self, query: str, *, top_k: int = 5) -> list[dict]:
        if top_k <= 0 or not self.chunks:
            return []
        terms = [term for term in dict.fromkeys(tokenize(query)) if term in self.df]
        if not terms:
            return []
        idf = {term: self._idf(term) for term in terms}
        avgdl = self.avgdl or 1.0

        scores: list[float] = []
        for term_freq, length in zip(self.tfs, self.lengths):
            score = 0.0
            norm = K1 * (1 - B + B * length / avgdl)
            for term in terms:
                freq = term_freq.get(term)
                if not freq:
                    continue
                score += idf[term] * freq * (K1 + 1) / (freq + norm)
            scores.append(score)

        order = sorted(range(self.total), key=lambda index: scores[index], reverse=True)
        results = []
        for index in order[:top_k]:
            if scores[index] <= 0:
                break
            chunk = dict(self.chunks[index])
            chunk["score"] = round(scores[index], 4)
            results.append(chunk)
        return results
