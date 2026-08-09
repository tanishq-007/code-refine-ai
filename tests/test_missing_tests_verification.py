from pathlib import Path

from analyzers import missing_tests, verify


def test_missing_tests_findings_are_preserved_by_verification():
    repo_root = Path(__file__).resolve().parents[1] / "eval" / "sample_repo"
    rel_path = "src/orders.py"
    source = (repo_root / rel_path).read_text(encoding="utf-8")

    findings = missing_tests.analyze(str(repo_root), rel_path, source)
    assert any(f.symbol == "apply_shipping_rules" for f in findings)

    verified = verify._heuristic_verify(str(repo_root), findings)
    assert any(f.symbol == "apply_shipping_rules" for f in verified)
