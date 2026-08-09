#!/usr/bin/env python3
"""
main.py -- Code Debt Collector CLI

    python main.py scan  [--repo PATH] [-o findings.json] [--quiet]
    python main.py score [--repo PATH] [-i findings.json] [-o scored.json] [--no-rag]
    python main.py run   [--repo PATH] [-o roadmap.md] [--top-n 10] [--no-fixes]
                         [--transport {in-process,mcp}] [--strategy {single,multi}]
    python main.py eval  [--repo PATH]   (defaults to eval/sample_repo, no API key needed
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from analyzers.base import write_findings, read_findings
from analyzers.scan import scan as run_scan, _walk_files, PY_EXTS
from agent.scoring import score_findings
from agent import orchestrator
from eval import score_pipeline


def _print_table(headers, rows):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def _line(char="-"):
        print("+" + "+".join(char * (w + 2) for w in widths) + "+")

    def _row(cells):
        print("| " + " | ".join(cell.ljust(w) for cell, w in zip(cells, widths)) + " |")

    _line()
    _row(headers)
    _line("=")
    for row in rows:
        _row(row)
    _line()


def cmd_scan(args):
    findings = run_scan(args.repo)
    write_findings(findings, args.output)
    print(f"Found {len(findings)} findings -> {args.output}")
    by_type = {}
    for f in findings:
        by_type[f.type] = by_type.get(f.type, 0) + 1
    for t, n in sorted(by_type.items()):
        print(f"  {t:<18}{n}")

    if not args.quiet:
        for t in sorted(by_type):
            group = [f for f in findings if f.type == t]
            print(f"\n=== {t} ({len(group)}) ===")
            rows = [
                [f.file, f"{f.line_start}-{f.line_end}", f.symbol or "(module level)"]
                for f in sorted(group, key=lambda f: (f.file, f.line_start))
            ]
            _print_table(["File", "Lines", "Symbol"], rows)


def cmd_score(args):
    if os.path.exists(args.input):
        findings = read_findings(args.input)
    else:
        print(f"'{args.input}' not found, scanning {args.repo} first...")
        findings = run_scan(args.repo)

    py_files = [] if args.no_rag else _walk_files(args.repo, PY_EXTS)
    scored = score_findings(findings, repo_root=args.repo, py_files=py_files)

    with open(args.output, "w") as f:
        json.dump([sf.to_dict() for sf in scored], f, indent=2)

    print(f"Scored {len(scored)} findings -> {args.output}")
    print(f"{'id':<28}{'type':<16}{'impact':>7}{'effort':>7}{'ratio':>7}")
    for sf in scored[:20]:
        print(f"{sf.finding.id:<28}{sf.finding.type:<16}{sf.impact:>7}{sf.effort:>7}{sf.ratio:>7.2f}")


def cmd_run(args):
    md = orchestrator.run(args.repo, out_path=args.output, top_n=args.top_n,
                           attempt_fixes=not args.no_fixes, transport=args.transport,
                           strategy=args.strategy)
    print(f"Roadmap written -> {args.output} ({len(md.splitlines())} lines)")


def cmd_eval(args):
    repo = args.repo or score_pipeline.SAMPLE_REPO
    report = score_pipeline.evaluate(repo_root=repo)
    score_pipeline.print_report(report)


def main():
    parser = argparse.ArgumentParser(prog="code-debt-collector")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Phase 1: deterministic findings as JSON")
    p_scan.add_argument("--repo", default=".")
    p_scan.add_argument("-o", "--output", default="findings.json")
    p_scan.add_argument("--quiet", action="store_true", help="only print the type-count summary")
    p_scan.set_defaults(func=cmd_scan)

    p_score = sub.add_parser("score", help="Add LLM impact/effort scores")
    p_score.add_argument("--repo", default=".")
    p_score.add_argument("-i", "--input", default="findings.json")
    p_score.add_argument("-o", "--output", default="scored.json")
    p_score.add_argument("--no-rag", action="store_true", help="skip fan-in enrichment")
    p_score.set_defaults(func=cmd_score)

    p_run = sub.add_parser("run", help="Full agentic pass -> roadmap.md")
    p_run.add_argument("--repo", default=".")
    p_run.add_argument("-o", "--output", default="roadmap.md")
    p_run.add_argument("--top-n", type=int, default=10)
    p_run.add_argument("--no-fixes", action="store_true", help="score + roadmap only, skip fix generation")
    p_run.add_argument("--transport", choices=["in-process", "mcp"], default="in-process",
                        help="tool-execution transport for the agent loop (default: in-process)")
    p_run.add_argument("--strategy", choices=["single", "multi"], default="multi",
                        help="multi (default) routes findings to specialist agents "
                             "(Refactoring/Documentation); single uses one generalist agent")
    p_run.set_defaults(func=cmd_run)

    p_eval = sub.add_parser("eval", help="Precision/recall vs. planted debt (offline, no API key)")
    p_eval.add_argument("--repo", default=None, help="defaults to eval/sample_repo")
    p_eval.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
