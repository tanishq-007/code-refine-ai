from agent import specialists


def test_route_routes_known_finding_types_and_defaults_unknown():
    for finding_type in specialists.REFACTORING_AGENT.handles:
        specialist, reason = specialists.route(finding_type)
        assert specialist is specialists.REFACTORING_AGENT
        assert reason == (
            f"finding type '{finding_type}' is owned by {specialists.REFACTORING_AGENT.name}"
        )

    for finding_type in specialists.DOCUMENTATION_AGENT.handles:
        specialist, reason = specialists.route(finding_type)
        assert specialist is specialists.DOCUMENTATION_AGENT
        assert reason == (
            f"finding type '{finding_type}' is owned by {specialists.DOCUMENTATION_AGENT.name}"
        )

    specialist, reason = specialists.route("mystery_finding")
    assert specialist is specialists.DEFAULT_SPECIALIST
    assert "no dedicated specialist" in reason
    assert "default fixer" in reason
