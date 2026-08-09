from agent import orchestrator


def test_rejected_fix_with_passing_retry_uses_retry():
    original = {"tests_passed": False, "applied": True}
    verdict = {"verdict": "reject", "rationale": "needs a better edit"}
    retry = {"tests_passed": True, "applied": True}

    assert orchestrator._needs_retry(verdict) is True
    assert orchestrator._use_retry(original, verdict["verdict"], retry) is True

    merged = orchestrator._merge_retry(original, verdict, retry)
    assert merged["retry_used"] is True
    assert "using the retry" in merged["retry"]
    assert "retry passed" in merged["retry"]


def test_rejected_fix_with_failing_retry_keeps_original():
    original = {"tests_passed": True, "applied": True}
    verdict = {"verdict": "reject", "rationale": "still wrong"}
    retry = {"tests_passed": False, "applied": True}

    assert orchestrator._needs_retry(verdict) is True
    assert orchestrator._use_retry(original, verdict["verdict"], retry) is False

    merged = orchestrator._merge_retry(original, verdict, retry)
    assert merged["retry_used"] is False
    assert merged is original
    assert "keeping the original" in merged["retry"]


def test_approve_verdict_never_triggers_retry():
    original = {"tests_passed": True, "applied": True}
    verdict = {"verdict": "approve", "rationale": "looks good"}
    retry = {"tests_passed": True, "applied": True}

    assert orchestrator._needs_retry(verdict) is False
    assert orchestrator._use_retry(original, verdict["verdict"], retry) is False

    merged = orchestrator._merge_retry(original, verdict, retry)
    assert merged["retry_used"] is False
    assert "keeping the original" in merged["retry"]
