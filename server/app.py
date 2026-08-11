"""FastAPI backend for the Code Debt Collector web UI.

Wraps the existing CLI (main.py scan/score/run/eval) as background jobs with
live log streaming (SSE), and serves the JSON/Markdown artifacts the pipeline
writes into `<repo>/.code_debt/`.

Run:  uvicorn server.app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

from agent import fixgen
from analyzers.base import IGNORE_DIRS

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="Code Debt Collector API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Job manager
# --------------------------------------------------------------------------

VALID_COMMANDS = {"scan", "score", "run", "eval", "clone"}

# Repos added through the UI (clone-from-URL, folder upload) land here.
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, ".code_debt_workspace")


def _unique_workspace_dir(name: str) -> str:
    """Sanitized, collision-free directory under the workspace."""
    base = re.sub(r"[^A-Za-z0-9._-]", "-", name).strip(".-") or "repo"
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    dest = os.path.join(WORKSPACE_DIR, base)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(WORKSPACE_DIR, f"{base}-{n}")
        n += 1
    return dest


class JobRequest(BaseModel):
    command: str
    repo: str = ""
    url: str = ""
    top_n: int = 10
    no_fixes: bool = False
    no_rag: bool = False
    strategy: str = "multi"
    transport: str = "in-process"


class Job:
    _ids = itertools.count(1)

    def __init__(self, req: JobRequest):
        self.id = next(Job._ids)
        self.command = req.command
        if req.command == "clone":
            name = req.url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            self.repo = _unique_workspace_dir(name)
        else:
            self.repo = os.path.abspath(req.repo)
        self.status = "running"
        self.returncode: Optional[int] = None
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.lines: List[str] = []
        self.argv = self._build_argv(req)

    def _build_argv(self, req: JobRequest) -> List[str]:
        if req.command == "clone":
            # --progress forces clone progress onto the merged pipe even
            # though stderr isn't a TTY, so the UI stream shows activity
            return ["git", "clone", "--progress", req.url, self.repo]
        debt = os.path.join(self.repo, ".code_debt")
        os.makedirs(debt, exist_ok=True)
        argv = [sys.executable, "main.py", req.command]
        if req.command == "scan":
            argv += ["--repo", self.repo, "-o", os.path.join(debt, "findings.json"), "--quiet"]
        elif req.command == "score":
            argv += ["--repo", self.repo,
                     "-i", os.path.join(debt, "findings.json"),
                     "-o", os.path.join(debt, "scored.json")]
            if req.no_rag:
                argv.append("--no-rag")
        elif req.command == "run":
            argv += ["--repo", self.repo, "-o", os.path.join(debt, "roadmap.md"),
                     "--top-n", str(req.top_n),
                     "--strategy", req.strategy, "--transport", req.transport]
            if req.no_fixes:
                argv.append("--no-fixes")
        elif req.command == "eval":
            argv += ["--repo", self.repo]
        return argv

    def to_dict(self, with_lines: bool = False) -> Dict:
        d = {
            "id": self.id, "command": self.command, "repo": self.repo,
            "status": self.status, "returncode": self.returncode,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "line_count": len(self.lines),
        }
        if with_lines:
            d["lines"] = self.lines
        return d


JOBS: Dict[int, Job] = {}
JOBS_LOCK = threading.Lock()


def _run_job(job: Job) -> None:
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.Popen(
            job.argv, cwd=PROJECT_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            job.lines.append(line.rstrip("\n"))
        job.returncode = proc.wait()
        job.status = "succeeded" if job.returncode == 0 else "failed"
    except Exception as e:  # noqa: BLE001 -- job failure must land in the job record
        job.lines.append(f"[server] job crashed: {e}")
        job.status = "failed"
    finally:
        job.finished_at = time.time()


@app.post("/api/jobs")
def create_job(req: JobRequest):
    if req.command not in VALID_COMMANDS:
        raise HTTPException(400, f"unknown command '{req.command}'")
    if req.command == "clone":
        if not re.match(r"^https?://", req.url):
            raise HTTPException(400, "clone URL must start with http:// or https://")
    elif not os.path.isdir(req.repo):
        raise HTTPException(400, f"repo path does not exist: {req.repo}")
    with JOBS_LOCK:
        running = [j for j in JOBS.values() if j.status == "running"]
        if running:
            raise HTTPException(409, f"job #{running[0].id} ({running[0].command}) is still running")
        job = Job(req)
        JOBS[job.id] = job
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return job.to_dict()


@app.get("/api/jobs")
def list_jobs():
    return [j.to_dict() for j in sorted(JOBS.values(), key=lambda j: -j.id)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job.to_dict(with_lines=True)


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: int):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")

    async def gen():
        sent = 0
        while True:
            while sent < len(job.lines):
                yield f"data: {json.dumps({'line': job.lines[sent]})}\n\n"
                sent += 1
            if job.status != "running":
                yield f"event: done\ndata: {json.dumps(job.to_dict())}\n\n"
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------
# Data endpoints
# --------------------------------------------------------------------------

def _repo_root(repo: str) -> str:
    root = os.path.abspath(repo)
    if not os.path.isdir(root):
        raise HTTPException(400, f"repo path does not exist: {root}")
    return root


def _read_json(repo: str, name: str, fallback_root: bool = True):
    root = _repo_root(repo)
    candidates = [os.path.join(root, ".code_debt", name)]
    if fallback_root:
        candidates.append(os.path.join(root, name))
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return None


@app.get("/api/health")
def health():
    return {"ok": True, "project_root": PROJECT_ROOT}


@app.get("/api/repos")
def suggested_repos():
    names = [".", "addition", os.path.join("eval", "sample_repo")]
    out = []
    for n in names:
        path = os.path.abspath(os.path.join(PROJECT_ROOT, n))
        if os.path.isdir(path):
            out.append({"label": os.path.basename(path) or "project root", "path": path})
    if os.path.isdir(WORKSPACE_DIR):
        for entry in sorted(os.listdir(WORKSPACE_DIR)):
            path = os.path.join(WORKSPACE_DIR, entry)
            if os.path.isdir(path):
                out.append({"label": entry, "path": path})
    return out


@app.post("/api/repos/upload")
async def upload_repo(
    files: List[UploadFile] = File(...),
    paths: List[str] = Form(...),
    name: str = Form(""),
):
    """Receive a folder uploaded from the browser (drag-drop or folder picker).
    `paths` carries each file's repo-relative path, parallel to `files`."""
    if len(files) != len(paths):
        raise HTTPException(400, "files and paths must be parallel lists")
    if not files:
        raise HTTPException(400, "no files received")

    if not name:
        first = paths[0].replace("\\", "/").lstrip("/")
        name = first.split("/")[0] if "/" in first else "uploaded-repo"
    dest_root = _unique_workspace_dir(name)

    written = 0
    try:
        for upload, rel in zip(files, paths):
            parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
            if not parts or ".." in parts:
                raise HTTPException(400, f"unsafe relative path: {rel}")
            # the folder picker prefixes every path with the folder name,
            # which is already the workspace directory name — drop it
            if len(parts) > 1 and parts[0] == name:
                parts = parts[1:]
            full = os.path.join(dest_root, *parts)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as out:
                shutil.copyfileobj(upload.file, out)
            written += 1
    except HTTPException:
        shutil.rmtree(dest_root, ignore_errors=True)
        raise
    except OSError as e:
        shutil.rmtree(dest_root, ignore_errors=True)
        raise HTTPException(500, f"failed writing upload: {e}")

    return {"path": dest_root, "files": written}


@app.get("/api/repo/validate")
def validate_repo(path: str = Query(...)):
    root = os.path.abspath(path)
    ok = os.path.isdir(root)
    py_count = 0
    if ok:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
            py_count += sum(1 for f in filenames if f.endswith(".py"))
    debt = os.path.join(root, ".code_debt")
    return {
        "ok": ok, "path": root, "py_files": py_count,
        "has_findings": os.path.isfile(os.path.join(debt, "findings.json")),
        "has_scored": os.path.isfile(os.path.join(debt, "scored.json")),
        "has_fixes": os.path.isfile(os.path.join(debt, "fixes.json")),
        "has_roadmap": os.path.isfile(os.path.join(debt, "roadmap.md")),
    }


@app.get("/api/data/findings")
def get_findings(repo: str = Query(...)):
    return _read_json(repo, "findings.json") or []


@app.get("/api/data/scored")
def get_scored(repo: str = Query(...)):
    return _read_json(repo, "scored.json") or []


@app.get("/api/data/fixes")
def get_fixes(repo: str = Query(...)):
    return _read_json(repo, "fixes.json", fallback_root=False) or {}


@app.get("/api/data/fix_preview")
def get_fix_preview(repo: str = Query(...), finding_id: str = Query(...)):
    """Whole-file before/after content for one fix's diff, for the split
    editor view -- the diff alone only carries changed hunks + a little
    context, not the full file either side of the change."""
    root = _repo_root(repo)
    fixes = _read_json(repo, "fixes.json", fallback_root=False) or {}
    fix = fixes.get(finding_id)
    if not fix:
        raise HTTPException(404, f"no fix recorded for finding '{finding_id}'")
    diff_text = fix.get("diff")
    if not diff_text:
        raise HTTPException(400, "this fix has no diff to preview")
    try:
        return fixgen.preview_fix(root, diff_text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(422, str(e))


@app.get("/api/data/roadmap")
def get_roadmap(repo: str = Query(...)):
    root = _repo_root(repo)
    for path in (os.path.join(root, ".code_debt", "roadmap.md"),
                 os.path.join(root, "roadmap.md")):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return {"markdown": f.read(), "path": path}
    return {"markdown": None, "path": None}


class ApplyFixRequest(BaseModel):
    repo: str
    finding_id: str


@app.post("/api/fixes/apply")
def apply_fix(req: ApplyFixRequest):
    """Apply one verified fix diff to the real repo. All-or-nothing: plain
    `git apply` validates the entire patch before touching any file."""
    root = _repo_root(req.repo)
    fixes_path = os.path.join(root, ".code_debt", "fixes.json")
    if not os.path.isfile(fixes_path):
        raise HTTPException(404, "no fixes.json for this repo — run the full pipeline first")
    with open(fixes_path, encoding="utf-8") as f:
        fixes = json.load(f)

    fix = fixes.get(req.finding_id)
    if not fix:
        raise HTTPException(404, f"no fix recorded for finding '{req.finding_id}'")
    if fix.get("applied_to_repo"):
        raise HTTPException(409, "this fix was already applied to the repo")
    if not fix.get("diff"):
        raise HTTPException(400, "this fix has no diff to apply")
    # mirror agent/roadmap.py::_rejected — a reviewer-rejected fix is never
    # applied, no matter what the mechanical signals say
    rejected = (not fix.get("retry_used")
                and (fix.get("review") or {}).get("verdict") == "reject")
    if rejected:
        raise HTTPException(400, "the reviewer rejected this fix — refusing to apply it")
    if not fix.get("tests_passed"):
        raise HTTPException(400, "only fixes whose sandbox tests passed can be applied")

    diff_text = fix["diff"]
    diff_path = os.path.join(root, ".code_debt", "_apply.diff")
    # newline="" matters on Windows: text-mode writes would turn \n into \r\n
    # and corrupt the patch against LF source files (same fix as fixgen.py)
    with open(diff_path, "w", encoding="utf-8", newline="") as f:
        f.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
    try:
        apply_cmd = (["git", "apply", "--whitespace=fix", diff_path]
                     if shutil.which("git") else ["patch", "-p1", "-i", diff_path])
        proc = subprocess.run(apply_cmd, cwd=root, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=60)
        log = f"$ {' '.join(apply_cmd)}\n{proc.stdout}\n{proc.stderr}".strip()
        if proc.returncode != 0:
            raise HTTPException(422, f"patch did not apply cleanly:\n{log}")
    finally:
        try:
            os.remove(diff_path)
        except OSError:
            pass

    fix["applied_to_repo"] = True
    fix["applied_at"] = time.time()
    with open(fixes_path, "w", encoding="utf-8") as f:
        json.dump(fixes, f, indent=2)
    return {"ok": True, "log": log}


class UpdateFixRequest(BaseModel):
    repo: str
    finding_id: str
    content: str


@app.post("/api/fixes/update")
def update_fix(req: UpdateFixRequest):
    """Rebuild + re-verify a fix from a manual edit made to the split
    editor's modified pane. The new diff gets the same sandboxed
    apply-and-test proof as a model-proposed one -- editing the suggestion
    doesn't let a fix skip verification, it just changes whose code is being
    verified. Clears the stale reviewer verdict, since it judged different
    content than what's being saved now."""
    root = _repo_root(req.repo)
    fixes_path = os.path.join(root, ".code_debt", "fixes.json")
    if not os.path.isfile(fixes_path):
        raise HTTPException(404, "no fixes.json for this repo — run the full pipeline first")
    with open(fixes_path, encoding="utf-8") as f:
        fixes = json.load(f)

    fix = fixes.get(req.finding_id)
    if not fix or not fix.get("diff"):
        raise HTTPException(404, f"no fix with a diff recorded for finding '{req.finding_id}'")

    try:
        result = fixgen.update_fix_from_edit(root, fix["diff"], req.content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    fix["diff"] = result["diff"] or None
    fix["applied"] = result["applied"]
    fix["tests_passed"] = result["tests_passed"]
    fix["edited_by_user"] = True
    fix["review"] = None
    fix["error"] = None
    fixes[req.finding_id] = fix
    with open(fixes_path, "w", encoding="utf-8") as f:
        json.dump(fixes, f, indent=2)
    return fix


class CreateFixRequest(BaseModel):
    repo: str
    finding_id: str
    path: str
    content: str


@app.post("/api/fixes/create")
def create_fix(req: CreateFixRequest):
    """Record a hand-written fix for any finding -- the editor tab's save
    path, for findings below the pipeline's --top-n cutoff that never got an
    LLM diff. The edit is diffed against the file on disk and earns the same
    sandboxed apply-and-test proof as a model-proposed fix. Overwrites any
    existing entry for the finding (the diff changed, so its old verdicts --
    review, applied_to_repo -- no longer describe this content)."""
    root = _repo_root(req.repo)
    try:
        result = fixgen.create_fix_from_edit(root, req.path, req.content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not result["diff"]:
        raise HTTPException(400, "edited content is identical to the file on disk — nothing to save")

    fixes_path = os.path.join(root, ".code_debt", "fixes.json")
    fixes = {}
    if os.path.isfile(fixes_path):
        with open(fixes_path, encoding="utf-8") as f:
            fixes = json.load(f)

    fix = fixes.get(req.finding_id) or {"agent": "human"}
    fix["diff"] = result["diff"]
    fix["applied"] = result["applied"]
    fix["tests_passed"] = result["tests_passed"]
    fix["edited_by_user"] = True
    fix["review"] = None
    fix["error"] = None
    fix["applied_to_repo"] = False
    fixes[req.finding_id] = fix
    os.makedirs(os.path.dirname(fixes_path), exist_ok=True)
    with open(fixes_path, "w", encoding="utf-8") as f:
        json.dump(fixes, f, indent=2)
    return fix


@app.get("/api/data/file")
def get_file(repo: str = Query(...), path: str = Query(...)):
    """Whole-file content for the editor tab. Unlike /api/data/snippet it
    doesn't trim to the finding's neighborhood -- the editor diffs the whole
    file, so it has to start from the whole file."""
    root = _repo_root(repo)
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(os.path.realpath(root) + os.sep):
        raise HTTPException(400, "path escapes repo root")
    if not os.path.isfile(full):
        raise HTTPException(404, f"no such file: {path}")
    with open(full, encoding="utf-8", errors="replace") as f:
        return {"path": path, "content": f.read()}


@app.get("/api/data/snippet")
def get_snippet(repo: str = Query(...), path: str = Query(...),
                start: int = Query(1, ge=1), end: int = Query(1, ge=1)):
    root = _repo_root(repo)
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(os.path.realpath(root) + os.sep):
        raise HTTPException(400, "path escapes repo root")
    if not os.path.isfile(full):
        raise HTTPException(404, f"no such file: {path}")
    with open(full, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    # pad a little context around the finding
    lo = max(1, start - 3)
    hi = min(len(lines), end + 3)
    return {
        "path": path, "line_start": lo, "line_end": hi, "total_lines": len(lines),
        "lines": lines[lo - 1:hi],
    }
