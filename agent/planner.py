"""One-call planner for coordinating multiple findings in a single run."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from analyzers.base import Finding
from agent import llm_client

SYSTEM_PROMPT = """You are the coordinator for a technical-debt remediation run. Given the top findings, produce a single JSON object with an ordered list of finding ids and grouped dependencies. Keep the plan concise and practical."""


def plan_findings(findings: List[Finding]) -> Dict:
    """Return a planner payload with ordering and group info using one LLM call."""
    if not llm_client.have_key():
        by_file = {}
        for finding in findings:
            by_file.setdefault(finding.file, []).append(finding.id)
        groups = [{"ids": ids, "reason": f"same file {file}"} for file, ids in sorted(by_file.items()) if len(ids) > 1]
        return {"ordered_ids": [f.id for f in findings], "groups": groups}

    payload = [{"id": f.id, "type": f.type, "file": f.file, "symbol": f.symbol, "description": f.description} for f in findings]
    response = llm_client.create_chat_completion(
        model=llm_client.ORCH_MODEL,
        max_tokens=1000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
        **llm_client.response_format_kwargs({"type": "json_object"}),
    )
    parsed = llm_client.parse_json_response((response.choices[0].message.content or "{}"))
    if not isinstance(parsed, dict):
        return {"ordered_ids": [f.id for f in findings], "groups": []}
    if "ordered_ids" not in parsed:
        parsed["ordered_ids"] = [f.id for f in findings]
    if "groups" not in parsed:
        parsed["groups"] = []
    return parsed
