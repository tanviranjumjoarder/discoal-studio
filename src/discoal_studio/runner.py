# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Run every discoal command on all CPU cores, safely.

* Parallel: one discoal process per worker, at low priority so the PC stays usable.
* Resumable: a file only appears under its real name once discoal finished it,
  so after a crash or Stop you just press Run again.
* Shardable: --shard k/n runs every n-th file, for SLURM job arrays.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import CITE, __version__, engine
from .compiler import Job, compile_spec
from .spec import DatasetSpec


@dataclass
class Progress:
    total: int = 0
    done: int = 0           # finished in this run or found from an earlier run
    skipped: int = 0        # already there from an earlier run
    failed: list = field(default_factory=list)
    started: float = field(default_factory=time.time)
    state: str = "idle"     # idle | running | done | stopped | error
    message: str = ""

    @property
    def eta_seconds(self) -> float | None:
        ran = self.done - self.skipped
        if ran <= 0:
            return None
        rate = ran / (time.time() - self.started)
        return (self.total - self.done - len(self.failed)) / rate

    def as_dict(self) -> dict:
        return {"total": self.total, "done": self.done, "skipped": self.skipped,
                "failed": len(self.failed), "failures": self.failed[-5:], "state": self.state,
                "message": self.message, "elapsed": time.time() - self.started, "eta": self.eta_seconds}


# Windows: start discoal at below-normal priority and without a console window popping up
# for every file (POSIX uses setpriority below).
LOW_PRIORITY = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def default_workers() -> int:
    return max(1, (os.cpu_count() or 2) - 1)


def write_tables(spec: DatasetSpec, out: Path, jobs: list[Job]) -> None:
    for c in spec.classes:
        rows = [j.row for j in jobs if j.cls == c.name]
        tmp = out / f".params_{c.name}.csv.part"
        with open(tmp, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, out / f"params_{c.name}.csv")


class Runner:
    def __init__(self, spec: DatasetSpec, out: str | Path, workers: int | None = None,
                 binary: Path | None = None, shard: tuple[int, int] = (0, 1),
                 timeout: float | None = None, on_progress: Callable[[Progress], None] | None = None):
        self.spec, self.out = spec, Path(out)
        self.workers = workers or default_workers()
        self.binary = binary or engine.ensure()
        self.shard, self.timeout = shard, timeout
        self.on_progress = on_progress or (lambda p: None)
        self.progress = Progress()
        self._stop = threading.Event()
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    # -- control -----------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for p in list(self._procs):
                p.kill()

    # -- one file ----------------------------------------------------------------
    def _run_one(self, job: Job) -> None:
        if self._stop.is_set():
            return
        dest = self.out / job.relpath
        part = dest.with_name("." + dest.name + ".part")
        with open(part, "wb") as fh:
            # argv[0] stays "discoal" so line 1 of the file is the command, exactly as on the HPC
            p = subprocess.Popen(job.argv, executable=str(self.binary), stdout=fh, stderr=subprocess.PIPE,
                                 creationflags=LOW_PRIORITY)
            with self._lock:
                self._procs.add(p)
                if self._stop.is_set():   # stop() ran while this one was starting
                    p.kill()
            if hasattr(os, "setpriority"):
                try:
                    os.setpriority(os.PRIO_PROCESS, p.pid, 10)
                except OSError:
                    pass
            timed_out = False
            try:
                _, err = p.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                _, err = p.communicate()
                timed_out = True
            finally:
                with self._lock:
                    self._procs.discard(p)
        if self._stop.is_set() or timed_out or p.returncode:
            part.unlink(missing_ok=True)
        if self._stop.is_set():
            return
        if timed_out:
            raise RuntimeError(f"timed out after {self.timeout:g} s")
        if p.returncode:
            raise RuntimeError(f"exit {p.returncode}: {err.decode(errors='replace').strip()[-300:]}")
        os.replace(part, dest)

    # -- whole dataset -----------------------------------------------------------
    def run(self) -> Progress:
        pr = self.progress
        pr.state, pr.started = "running", time.time()
        self.out.mkdir(parents=True, exist_ok=True)
        jobs = list(compile_spec(self.spec))
        k, n = self.shard
        mine = [j for idx, j in enumerate(jobs) if idx % n == k]
        for d in {(self.out / j.relpath).parent for j in mine}:
            d.mkdir(parents=True, exist_ok=True)
        todo = [j for j in mine if not (self.out / j.relpath).exists()]
        pr.total, pr.skipped = len(mine), len(mine) - len(todo)
        pr.done = pr.skipped
        self.spec.save(self.out / "spec.json")
        self._manifest("running")
        self.on_progress(pr)

        with ThreadPoolExecutor(self.workers) as pool:
            futs = {pool.submit(self._run_one, j): j for j in todo}
            for f in as_completed(futs):
                j = futs[f]
                try:
                    f.result()
                    if not self._stop.is_set():
                        pr.done += 1
                except Exception as e:  # noqa: BLE001 - keep going, report at the end
                    pr.failed.append({"file": j.relpath, "command": j.command, "error": str(e)})
                self.on_progress(pr)

        write_tables(self.spec, self.out, jobs)
        if self._stop.is_set():
            pr.state, pr.message = "stopped", "Stopped. Press Run again to continue where it left off."
        elif pr.failed:
            pr.state, pr.message = "error", f"{len(pr.failed)} file(s) failed; see manifest.json"
        else:
            pr.state, pr.message = "done", f"All {pr.total} files are ready in {self.out}"
        self._manifest(pr.state)
        self.on_progress(pr)
        return pr

    def _manifest(self, state: str) -> None:
        m = {
            "app": f"discoal-studio {__version__}",
            "cite": CITE,
            "state": state,
            "updated": dt.datetime.now().isoformat(timespec="seconds"),
            "spec": "spec.json",
            "files": self.spec.total_files,
            "shard": f"{self.shard[0]}/{self.shard[1]}",
            "discoal": engine.describe(self.binary),
            "machine": {"platform": platform.platform(), "cpus": os.cpu_count(), "workers": self.workers},
            "progress": self.progress.as_dict(),
            "failures": self.progress.failed,
            "reproduce": "discoal-studio run spec.json --out <folder>",
        }
        name = "manifest.json" if self.shard[1] == 1 else f"manifest_shard{self.shard[0]}.json"
        (self.out / name).write_text(json.dumps(m, indent=2))


def pilot(spec: DatasetSpec, per_class: int = 3, workers: int | None = None) -> dict:
    """Run a few files of each class in a temp folder; estimate time and disk for the whole set."""
    small = spec.model_copy(deep=True)
    for c in small.classes:
        c.count = min(c.count, per_class)
    workers = workers or default_workers()
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.time()
        r = Runner(small, tmp, workers=1)
        r.run()
        secs = time.time() - t0
        sizes = [p.stat().st_size for p in Path(tmp).rglob("*.ms")]
    n = max(1, len(sizes))
    per_file_s = secs / n
    total = spec.total_files
    free = shutil.disk_usage(Path.home()).free
    est_bytes = sum(sizes) / n * total
    return {
        "files_tested": len(sizes), "failed": len(r.progress.failed), "failures": r.progress.failed[:3],
        "seconds_per_file": per_file_s, "workers": workers,
        "estimated_seconds": per_file_s * total / workers,
        "estimated_bytes": est_bytes, "free_bytes": free, "enough_disk": est_bytes * 1.2 < free,
    }
