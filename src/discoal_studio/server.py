# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Local web API behind the desktop window. Listens on 127.0.0.1 only and
requires a per-launch token, so other websites cannot drive it."""
from __future__ import annotations

import atexit
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import CITE, __version__, analysis, assistant, engine, hpc
from .compiler import check, compile_one
from .runner import Runner, default_workers, pilot
from .spec import DatasetSpec, preset_descriptions, presets

STATIC = Path(__file__).parent / "static"
TOKEN = os.environ.get("DISCOAL_STUDIO_TOKEN") or secrets.token_urlsafe(16)
DATA_ROOT = Path.home() / "discoal-studio-datasets"


def auth(x_token: str = Header("")):
    if not secrets.compare_digest(x_token, TOKEN):
        raise HTTPException(403, "bad token")


app = FastAPI(title="discoal Studio", version=__version__)
api = FastAPI(dependencies=[Depends(auth)])


class State:
    runner: Runner | None = None
    thread: threading.Thread | None = None
    task: dict = {"kind": None, "state": "idle", "message": "", "done": 0, "total": 0}
    lock = threading.Lock()


S = State()


@atexit.register
def _stop_children():
    """Closing the app must not leave discoal processes running."""
    if S.runner:
        S.runner.stop()


def _spec(d: dict) -> DatasetSpec:
    try:
        return DatasetSpec.model_validate(d)
    except ValidationError as e:
        msgs = ["{}: {}".format(".".join(str(x) for x in err["loc"]), err["msg"]) for err in e.errors()]
        raise HTTPException(422, "; ".join(msgs))


def _busy():
    if S.thread and S.thread.is_alive():
        raise HTTPException(409, "Another task is still running.")


def _background(kind: str, fn):
    _busy()
    S.task = {"kind": kind, "state": "running", "message": "", "done": 0, "total": 0, "result": None}

    def go():
        try:
            S.task["result"] = fn()
            if S.task["state"] == "running":
                S.task["state"] = "done"
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            S.task.update(state="error", message=str(e))

    S.thread = threading.Thread(target=go, daemon=True)
    S.thread.start()
    return {"started": kind}


class SpecIn(BaseModel):
    spec: dict


class RunIn(BaseModel):
    spec: dict
    out: str
    workers: int | None = None


class FolderIn(BaseModel):
    out: str
    snps: int = 201
    window: int = 200


class AskIn(BaseModel):
    prompt: str
    spec: dict | None = None   # the form's current spec, so "now make it 500 each" edits it


class HpcIn(BaseModel):
    spec: dict
    folder: str
    tasks: int = 10
    cpus: int = 4
    mem: str = "8G"
    time: str = "06:00:00"
    partition: str = ""


@api.get("/info")
def info():
    b = engine.find()
    return {"version": __version__, "engine": engine.describe(b) if b else None,
            "can_build": engine.compiler() is not None, "cpus": os.cpu_count(),
            "default_workers": default_workers(), "data_root": str(DATA_ROOT),
            "assistant_unavailable": assistant.available(), "cite": CITE,
            "presets": {k: {"description": v, "spec": presets()[k].model_dump(exclude_none=True)}
                        for k, v in preset_descriptions().items()}}


@api.post("/engine/build")
def build_engine():
    return _background("build", lambda: engine.describe(engine.build(log=lambda m: S.task.update(message=m))))


@api.post("/check")
def check_spec(body: SpecIn):
    spec = _spec(body.spec)
    examples = []
    for c in spec.classes:
        for i in range(1, min(2, c.count) + 1):
            j = compile_one(spec, c, i)
            examples.append({"file": j.relpath, "command": j.command,
                             "values": {k: v for k, v in j.row.items() if k not in ("file", "command")}})
    return {"total_files": spec.total_files, "warnings": check(spec), "examples": examples}


@api.post("/assistant")
def ask(body: AskIn):
    """Draft a spec from plain English. Only returns a spec for the form; it never runs anything."""
    try:
        return assistant.draft(body.prompt, current=body.spec).as_dict()
    except assistant.AssistantError as e:
        raise HTTPException(503 if assistant.available() else 422, str(e))


@api.post("/pilot")
def run_pilot(body: SpecIn):
    spec = _spec(body.spec)
    engine.ensure()
    return _background("pilot", lambda: pilot(spec))


@api.post("/run")
def run(body: RunIn):
    spec = _spec(body.spec)
    _busy()
    binary = engine.ensure()

    def tick(p):
        S.task.update(done=p.done, total=p.total, message=p.message, progress=p.as_dict())

    S.runner = Runner(spec, Path(body.out).expanduser(), workers=body.workers, binary=binary, on_progress=tick)

    def go():
        p = S.runner.run()
        S.task["state"] = p.state
        return p.as_dict()
    return _background("run", go)


@api.post("/stop")
def stop():
    if S.runner and S.task.get("kind") == "run":
        S.runner.stop()
    return {"ok": True}


@api.get("/status")
def status():
    t = dict(S.task)
    if t.get("kind") == "run" and S.runner:
        t["progress"] = S.runner.progress.as_dict()
    return t


@api.post("/qc")
def run_qc(body: FolderIn):
    out = Path(body.out).expanduser()
    return _background("qc", lambda: analysis.qc(out, window=body.window, workers=default_workers(),
                                                 on_progress=lambda d, t: S.task.update(done=d, total=t)))


@api.post("/export-ml")
def export_ml(body: FolderIn):
    out = Path(body.out).expanduser()
    return _background("export", lambda: str(analysis.export_ml(
        out, snps=body.snps, workers=default_workers(), on_progress=lambda d, t: S.task.update(done=d, total=t))))


@api.post("/hpc")
def export_hpc(body: HpcIn):
    spec = _spec(body.spec)
    files = hpc.export(spec, Path(body.folder).expanduser(), tasks=body.tasks, cpus=body.cpus,
                       mem=body.mem, time=body.time, partition=body.partition)
    return {"files": [str(f) for f in files]}


@api.post("/open")
def open_folder(body: FolderIn):
    p = Path(body.out).expanduser()
    if not p.exists():
        raise HTTPException(404, "folder does not exist yet")
    opener = {"darwin": ["open"], "win32": ["explorer"]}.get(sys.platform, ["xdg-open"])
    subprocess.Popen([*opener, str(p)])
    return {"ok": True}


app.mount("/api", api)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
