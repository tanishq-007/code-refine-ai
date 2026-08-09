"""
rag/retrieval.py

Two things the scorer (agent/scoring.py) leans on:

  get_standards(query)      -> grounds severity judgments in guidance
                                retrieved from the coding-standards corpus
                                (rag/index.py's local TF-IDF index over
                                rag/standards.py) rather than the model's
                                own unaided judgment.
  enrich_fan_in(file, repo) -> real fan-in signal (how many other files
                                import this one) -- pure textual grep, no
                                retrieval needed, but grouped here since
                                it's part of the "ground the scorer in real
                                signals" phase.
"""
from __future__ import annotations

import os
import re
from typing import List

from rag import index as rag_index
from rag import standards as static_standards

_index = None


def _get_index() -> rag_index.TfidfIndex:
    global _index
    if _index is None:
        _index = rag_index.build_index(static_standards.STATIC_STANDARDS)
    return _index


def get_standards(finding_type: str) -> str:
    """Retrieves the coding-standard paragraph most relevant to finding_type
    via TF-IDF cosine similarity over the standards corpus (see
    rag/index.py). Falls back to static_standards.lookup()'s generic
    guidance only if the query shares no vocabulary with any document at
    all (score 0 for every candidate) -- shouldn't happen for a known
    finding type, but keeps this safe for an unrecognized one."""
    hits = _get_index().query(finding_type, k=1)
    if hits and hits[0][1] > 0:
        doc_id, _ = hits[0]
        return static_standards.STATIC_STANDARDS[doc_id]
    return static_standards.lookup(finding_type)


def enrich_fan_in(repo_root: str, rel_path: str, all_py_files: List[str]) -> int:
    """Counts how many other files import/reference this module by name --
    a simple but real signal for "this is load-bearing code", used to
    weight impact scores upward."""
    module_name = os.path.splitext(os.path.basename(rel_path))[0]
    if module_name == "__init__":
        module_name = os.path.basename(os.path.dirname(rel_path))
    pattern = re.compile(rf"\b(import\s+{re.escape(module_name)}\b|from\s+[\w.]*{re.escape(module_name)}\b)")

    fan_in = 0
    for other in all_py_files:
        if other == rel_path:
            continue
        try:
            with open(os.path.join(repo_root, other), encoding="utf-8") as f:
                src = f.read()
        except OSError:
            continue
        if pattern.search(src):
            fan_in += 1
    return fan_in
