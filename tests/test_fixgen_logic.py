import pytest

from agent.fixgen import EditNotFoundError, _apply_edits


def test_apply_edits_succeeds_when_old_str_matches_once():
    original = "alpha\nbeta\ngamma\n"
    edits = [{"old_str": "beta\n", "new_str": "BETA\n"}]

    assert _apply_edits(original, edits) == "alpha\nBETA\ngamma\n"


def test_apply_edits_raises_when_old_str_matches_zero_times():
    original = "alpha\nbeta\ngamma\n"
    edits = [{"old_str": "delta", "new_str": "DELTA"}]

    with pytest.raises(EditNotFoundError):
        _apply_edits(original, edits)


def test_apply_edits_raises_when_old_str_matches_multiple_times():
    original = "alpha\nbeta\nbeta\ngamma\n"
    edits = [{"old_str": "beta\n", "new_str": "BETA\n"}]

    with pytest.raises(EditNotFoundError):
        _apply_edits(original, edits)
