"""
analyzers/churn.py

Git-churn signal: how many commits have touched each file, and how
recently. Not a Finding-producing analyzer on its own -- it's a signal
consumed by agent/scoring.py (frequently-changed + high-complexity code is
classic high-impact debt). Returns {} gracefully if there's no .git dir or
git isn't available.
"""
from __future__ import annotations

import subprocess
import shutil
import os
from typing import Dict


def git_available(repo_root: str) -> bool:
    return shutil.which("git") is not None and os.path.isdir(os.path.join(repo_root, ".git"))


def compute_churn(repo_root: str) -> Dict[str, int]:
    """Returns {relative_file_path: commit_count}."""
    if not git_available(repo_root):
        return {}
    try:
        out = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:"],
            cwd=repo_root, capture_output=True, text=True, timeout=30, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return {}

    churn: Dict[str, int] = {}
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        churn[line] = churn.get(line, 0) + 1
    return churn
