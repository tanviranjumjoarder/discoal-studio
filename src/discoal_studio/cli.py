# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Command line: the same engine as the app, for scripts and HPC clusters."""
from __future__ import annotations

import json
import signal
import sys
import threading
from pathlib import Path

import typer

from . import CITE, __version__, analysis, engine, hpc
from .compiler import check, compile_spec
from .runner import Runner, default_workers, pilot
from .spec import DatasetSpec, preset_descriptions, presets

app = typer.Typer(help="discoal Studio: reproducible discoal datasets on your own computer.",
                  no_args_is_help=False, invoke_without_command=True, add_completion=False)


@app.callback()
def main(ctx: typer.Context, version: bool = typer.Option(False, "--version")):
    if version:
        typer.echo(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        gui(port=0, browser=False)   # explicit: typer's Option defaults are truthy objects in a plain call


def _load(spec: str) -> DatasetSpec:
    p = Path(spec)
    if p.is_file():
        return DatasetSpec.load(p)
    if spec in presets():
        return presets()[spec]
    raise typer.BadParameter(f"{spec} is neither a spec file nor a preset ({', '.join(presets())})")


@app.command()
def gui(port: int = 0, browser: bool = typer.Option(False, help="Open in your web browser instead of an app window")):
    """Open the desktop app."""
    from .desktop import launch
    launch(port=port, use_browser=browser)


@app.command("presets")
def list_presets():
    """List built-in presets."""
    for k, v in preset_descriptions().items():
        typer.echo(f"{k}\n    {v}")


@app.command()
def plan(spec: str, show: int = typer.Option(3, help="Commands to print per class")):
    """Check a spec and print example commands (runs nothing)."""
    s = _load(spec)
    for w in check(s):
        typer.secho("warning: " + w, fg="yellow")
    seen: dict[str, int] = {}
    for j in compile_spec(s):
        seen[j.cls] = seen.get(j.cls, 0) + 1
        if seen[j.cls] <= show:
            typer.echo(f"{j.relpath}: {j.command}")
    typer.echo(f"{s.total_files} files in total.")


@app.command()
def estimate(spec: str, workers: int = default_workers()):
    """Run a few test files and estimate time and disk for the whole dataset."""
    typer.echo(json.dumps(pilot(_load(spec), workers=workers), indent=2))


@app.command()
def run(spec: str, out: Path = typer.Option(..., help="Output folder"),
        workers: int = typer.Option(default_workers(), help="Parallel discoal processes"),
        shard: str = typer.Option("0/1", help="k/n: run every n-th file starting at k (SLURM arrays)"),
        timeout: float = typer.Option(None, help="Seconds before one file is given up")):
    """Generate the dataset (skips files that already exist)."""
    s = _load(spec)
    k, n = (int(x) for x in shard.split("/"))
    last = [0]

    def tick(p):
        if p.done - last[0] >= max(1, p.total // 100) or p.state != "running":
            last[0] = p.done
            eta = f", ~{p.eta_seconds / 60:.1f} min left" if p.eta_seconds else ""
            typer.echo(f"\r{p.done}/{p.total} files{eta}   ", nl=False)

    r = Runner(s, out, workers=workers, shard=(k, n), timeout=timeout, on_progress=tick)

    def on_term(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, on_term)
    finished = threading.Event()        # not Thread.join: an interrupted join() can return early later

    def work():
        try:
            r.run()
        finally:
            finished.set()
    threading.Thread(target=work).start()
    try:
        while not finished.wait(0.5):
            pass
    except KeyboardInterrupt:          # Ctrl+C / scancel: stop discoal too, keep finished files
        r.stop()
        finished.wait()
    p = r.progress
    typer.echo("\n" + p.message)
    if p.state != "done":
        raise typer.Exit(1)


@app.command()
def qc(out: Path, window: int = 200):
    """Compute summary statistics for a finished dataset (qc_stats.csv, qc_summary.json)."""
    summary = analysis.qc(out, window=window, workers=default_workers())
    typer.echo(json.dumps({c: {k: round(v["median"], 4) for k, v in d.items()} for c, d in summary.items()}, indent=2))


@app.command("export-ml")
def export_ml(out: Path, snps: int = 201, no_sort: bool = False):
    """Write fixed-size haplotype arrays (ml/haplotypes_<snps>snps.npz) for deep learning."""
    typer.echo(analysis.export_ml(out, snps=snps, sort_rows=not no_sort, workers=default_workers()))


@app.command("export-hpc")
def export_hpc(spec: str, folder: Path, tasks: int = 10, cpus: int = 4, mem: str = "8G",
               time: str = "06:00:00", partition: str = ""):
    """Write spec.json, a SLURM array script and commands.txt for a cluster."""
    for f in hpc.export(_load(spec), folder, tasks=tasks, cpus=cpus, mem=mem, time=time, partition=partition):
        typer.echo(f)


@app.command("build-discoal")
def build_discoal():
    """Compile the bundled (patched) discoal for this computer."""
    try:
        typer.echo(engine.build(log=typer.echo))
    except RuntimeError as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(1)


@app.command()
def cite():
    """How to cite discoal Studio and discoal."""
    typer.echo(CITE)
    typer.echo("BibTeX and CITATION.cff: see the README, or the app's About & cite dialog.")


@app.command()
def verify(out: Path, files: int = 5):
    """Re-run some files from a finished dataset and check they come out identical."""
    import filecmp
    import tempfile
    s = DatasetSpec.load(out / "spec.json")
    small = s.model_copy(deep=True)
    for c in small.classes:
        c.count = min(c.count, files)
    with tempfile.TemporaryDirectory() as tmp:
        Runner(small, tmp, workers=default_workers()).run()
        bad = [j.relpath for j in compile_spec(small)
               if (out / j.relpath).exists() and not filecmp.cmp(out / j.relpath, Path(tmp) / j.relpath, shallow=False)]
    if bad:
        typer.secho(f"Different: {', '.join(bad)}", fg="red")
        raise typer.Exit(1)
    typer.secho("Identical: the dataset reproduces exactly.", fg="green")


if __name__ == "__main__":
    sys.exit(app())
