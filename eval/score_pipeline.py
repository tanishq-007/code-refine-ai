"""
eval/score_pipeline.py

Runs Phase 1 scan against eval/sample_repo (planted debt), matches
findings to eval/ground_truth.json by (file, symbol) within type, and
reports precision / recall / F1 per finding type plus an overall row.
No API key needed -- this only exercises the deterministic analyzers,
not LLM scoring.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Tuple

from analyzers.base import Finding, FINDING_TYPES
from analyzers.scan import scan

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_REPO = os.path.join(HERE, "sample_repo")
GROUND_TRUTH_PATH = os.path.join(HERE, "ground_truth.json")


def _load_ground_truth() -> Dict[str, List[Dict]]:
    with open(GROUND_TRUTH_PATH) as f:
        return json.load(f)


def _key(file: str, symbol: str) -> Tuple[str, str]:
    return (file.replace("\\", "/"), symbol or "")


def evaluate(repo_root: str = SAMPLE_REPO, ground_truth_path: str = GROUND_TRUTH_PATH) -> Dict:
    findings = scan(repo_root)
    with open(ground_truth_path) as f:
        gt = json.load(f)

    report = {}
    total_tp = total_fp = total_fn = 0

    for ftype in FINDING_TYPES:
        predicted = {_key(f.file, f.symbol) for f in findings if f.type == ftype}
        expected = {_key(g["file"], g["symbol"]) for g in gt.get(ftype, [])}

        tp = len(predicted & expected)
        fp = len(predicted - expected)
        fn = len(expected - predicted)

        precision = tp / (tp + fp) if (tp + fp) else (1.0 if fn == 0 else 0.0)
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        report[ftype] = {
            "precision": round(precision, 2), "recall": round(recall, 2), "f1": round(f1, 2),
            "tp": tp, "fp": fp, "fn": fn,
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn

    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) else 0.0
    report["OVERALL"] = {
        "precision": round(overall_p, 2), "recall": round(overall_r, 2), "f1": round(overall_f1, 2),
        "tp": total_tp, "fp": total_fp, "fn": total_fn,
    }
    return report


def print_report(report: Dict) -> None:
    print(f"{'type':<18}{'P':>7}{'R':>7}{'F1':>7}   (tp/fp/fn)")
    for ftype in list(FINDING_TYPES) + ["OVERALL"]:
        r = report[ftype]
        print(f"{ftype:<18}{r['precision']:>7.2f}{r['recall']:>7.2f}{r['f1']:>7.2f}  "
              f"({r['tp']}/{r['fp']}/{r['fn']})")


if __name__ == "__main__":
    print_report(evaluate())
