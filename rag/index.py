"""
rag/index.py

Local, dependency-free retrieval index over rag/standards.py's coding-standards
corpus. No external embedding API, no API key, no network call, no GPU --
the corpus is a handful of short paragraphs (one per finding type), so a
hosted embedding model would be overkill for what's actually a small,
fixed-vocabulary retrieval problem.

Embedding: plain TF-IDF term vectors (tokenize -> term frequency -> weight by
inverse document frequency across the corpus). Retrieval: cosine similarity
between the query's TF-IDF vector and each document's, ranked descending.

Each document is indexed under its own doc_id (finding type, e.g.
"magic_number") *plus* its body text -- like indexing a document's title
alongside its content. This guarantees a query for the type name itself always
shares at least that term with its own document (many of the hand-written
standards paragraphs don't happen to repeat the type name verbatim), while the
underlying mechanism stays genuine vector similarity rather than a disguised
dict lookup -- a query that isn't an exact type name (a longer finding
description, a partial name, ...) still gets a real nearest-match result.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Tuple

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def _term_frequencies(tokens: List[str]) -> Dict[str, float]:
    counts = Counter(tokens)
    total = sum(counts.values()) or 1
    return {term: n / total for term, n in counts.items()}


class TfidfIndex:
    """Built once over a small, fixed corpus (see build_index); query() is a
    single cosine-similarity pass over that corpus, cheap enough to call per
    lookup with no caching needed."""

    def __init__(self, documents: Dict[str, str]):
        self._doc_ids = list(documents.keys())
        doc_tokens = {doc_id: _tokenize(text) for doc_id, text in documents.items()}
        doc_tf = {doc_id: _term_frequencies(tokens) for doc_id, tokens in doc_tokens.items()}

        n_docs = max(len(documents), 1)
        doc_freq: Counter = Counter()
        for tokens in doc_tokens.values():
            for term in set(tokens):
                doc_freq[term] += 1
        # smoothed IDF (add-1 in numerator and denominator) so a term appearing
        # in every document doesn't collapse to a zero/negative weight
        self._idf = {term: math.log((1 + n_docs) / (1 + count)) + 1 for term, count in doc_freq.items()}

        self._doc_vectors = {doc_id: self._weight(tf) for doc_id, tf in doc_tf.items()}

    def _weight(self, term_freqs: Dict[str, float]) -> Dict[str, float]:
        return {term: freq * self._idf.get(term, 0.0) for term, freq in term_freqs.items()}

    def query(self, text: str, k: int = 1) -> List[Tuple[str, float]]:
        """Returns up to k (doc_id, cosine_similarity) pairs, highest first.
        similarity is 0.0 for a doc sharing no vocabulary at all with the
        query -- callers should treat an all-zero result as "no match"."""
        q_tokens = _tokenize(text)
        if not q_tokens:
            return []
        q_vec = self._weight(_term_frequencies(q_tokens))
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0

        scored: List[Tuple[str, float]] = []
        for doc_id in self._doc_ids:
            doc_vec = self._doc_vectors[doc_id]
            dot = sum(v * doc_vec.get(term, 0.0) for term, v in q_vec.items())
            doc_norm = math.sqrt(sum(v * v for v in doc_vec.values())) or 1.0
            scored.append((doc_id, dot / (q_norm * doc_norm)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


def build_index(documents: Dict[str, str]) -> TfidfIndex:
    """documents: {doc_id -> body text}. doc_id (e.g. a finding type like
    "magic_number") is folded into the indexed text alongside the body --
    see the module docstring for why."""
    indexed = {
        doc_id: f"{doc_id} {doc_id.replace('_', ' ')} {text}"
        for doc_id, text in documents.items()
    }
    return TfidfIndex(indexed)
