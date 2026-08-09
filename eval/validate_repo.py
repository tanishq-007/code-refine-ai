"""
eval/validate_repo.py

Structural smoke test: runs Phase 1 scan() against ANY repo (no ground
truth needed) and checks the resulting findings are well-formed via
analyzers/validate.py. Complements score_pipeline.py, which measures
precision/recall but only works against eval/sample_repo.
"""
from __future__ import annotations

import argparse
import sys

from analyzers.scan import scan
from analyzers.validate import validate_findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the repo to scan and validate.")
    args = parser.parse_args()

    findings = scan(args.repo)
    violations = validate_findings(args.repo, findings)

    print(f"scanned {args.repo}: {len(findings)} findings")
    if violations:
        print(f"{len(violations)} violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1

    print("clean: all findings reference real files/lines with no duplicate ids")
    return 0


if __name__ == "__main__":
    sys.exit(main())
