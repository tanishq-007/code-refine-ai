"""
mcp_server/server.py

Thin MCP binding: exposes the 6 functions in mcp_server/tools.py as MCP
tools over stdio, using the official `mcp` Python SDK. All the actual
logic lives in tools.py (and is testable without this file / without the
mcp package installed at all).

Run standalone for local testing/inspection:
    python -m mcp_server.server --repo-root /path/to/target/repo

Two ways the agent (agent/orchestrator.py) can reach these tools --
`python main.py run --transport {in-process,mcp}`:
  in-process (default): agent/orchestrator.py calls mcp_server/tools.py's
    functions directly. This file is never touched.
  mcp: the orchestrator spawns THIS file as a subprocess (the command
    above, run programmatically) and talks to it over a real MCP stdio
    session via the SDK client. If spawning or session init fails, the
    orchestrator falls the whole run back to in-process and logs why --
    see agent/orchestrator.py's module docstring for the fallback details.
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from mcp_server import tools


def _findings_path(repo_root: str) -> str:
    return os.path.join(repo_root, ".code_debt", "findings.json")


def build_server(repo_root: str):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise SystemExit(
            "The `mcp` package isn't installed. Install with `pip install mcp` "
            "to run the MCP server; the tool logic itself (mcp_server/tools.py) "
            "has no dependency on it and can be called/tested directly."
        ) from e

    mcp = FastMCP("code-debt-collector")

    @mcp.tool()
    def read_finding(finding_id: str) -> dict:
        """Look up the full record for a single finding by id."""
        return tools.read_finding(_findings_path(repo_root), finding_id)

    @mcp.tool()
    def read_file_snippet(rel_path: str, line_start: int, line_end: int) -> str:
        """Read a line range (with surrounding context) from a file in the repo."""
        return tools.read_file_snippet(repo_root, rel_path, line_start, line_end)

    @mcp.tool()
    def get_standards(finding_type: str) -> str:
        """Retrieve coding-standards guidance relevant to a finding type."""
        return tools.get_standards(finding_type)

    @mcp.tool()
    def search_codebase(pattern: str) -> list:
        """Regex-search the codebase; returns matching file/line/text."""
        return tools.search_codebase(repo_root, pattern)

    @mcp.tool()
    def propose_fix(finding_id: str) -> dict:
        """Generate a unified-diff fix proposal for a given finding id."""
        return tools.propose_fix(repo_root, _findings_path(repo_root), finding_id)

    @mcp.tool()
    def run_tests(finding_id: str) -> dict:
        """Apply the most recently proposed fix for this finding id (from
        propose_fix, server-side cached) to a throwaway copy of the repo
        and run its tests."""
        return tools.run_tests(repo_root, finding_id)

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()

    server = build_server(os.path.abspath(args.repo_root))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
