"""关键词 + 字符级向量特征的混合检索，带来源约束。"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.corpus import build_docs


def _tokens(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{1,4}", text)
    return [t for t in tokens if t]


def _ngrams(text: str, n: int = 2) -> Counter:
    clean = re.sub(r"\s+", "", text.lower())
    return Counter(clean[i : i + n] for i in range(len(clean) - n + 1))


def _cosine(a: Counter, b: Counter) -> float:
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class HybridSearcher:
    def __init__(self) -> None:
        self.docs = build_docs()
        self._vectors = [_ngrams(d["content"]) for d in self.docs]

    def hybrid_search(self, query: str, top_k: int = 8) -> list[dict]:
        q_tokens = Counter(_tokens(query))
        q_vec = _ngrams(query)
        scored: list[tuple[float, dict]] = []
        for doc, vec in zip(self.docs, self._vectors):
            doc_tokens = Counter(_tokens(doc["content"]))
            overlap = sum((q_tokens & doc_tokens).values())
            keyword_score = overlap / max(1, sum(q_tokens.values()))
            vec_score = _cosine(q_vec, vec)
            city_bonus = 0.08 if query.find(doc["city"]) >= 0 else 0.0
            score = keyword_score * 0.6 + vec_score * 0.4 + city_bonus
            scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, doc in scored[:top_k]:
            item = dict(doc)
            item["score"] = round(score, 4)
            item["source_constrained"] = bool(item.get("source"))
            results.append(item)
        return results


searcher = HybridSearcher()

