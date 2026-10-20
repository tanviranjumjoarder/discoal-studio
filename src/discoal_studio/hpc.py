# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Export a dataset spec for a cluster: a SLURM job array, or plain commands."""
from __future__ import annotations

from pathlib import Path

from .compiler import compile_spec
from .spec import DatasetSpec

SLURM = """#!/bin/bash
# Made by discoal-studio for dataset "{name}" ({files} files).
# {cite}
# 1) Once on the cluster:  pip install --user discoal-studio && discoal-studio build-discoal
#    (or: pip install --user /path/to/discoal_studio-*.whl)
# 2) Put this script next to spec.json and run:  sbatch run_{name}.slurm
# Every array task makes its own share of the files; re-submitting skips finished files.
#SBATCH --job-name={name}
#SBATCH --array=0-{last}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem}
#SBATCH --time={time}
#SBATCH --output=logs/{name}_%A_%a.out
{partition}
mkdir -p logs
discoal-studio run spec.json --out {out} \\
    --shard "$SLURM_ARRAY_TASK_ID/{tasks}" --workers "$SLURM_CPUS_PER_TASK"
"""


def slurm_script(spec: DatasetSpec, tasks: int = 10, cpus: int = 4, mem: str = "8G",
                 time: str = "06:00:00", partition: str = "", out: str = "discoal_data") -> str:
    from . import CITE
    return SLURM.format(cite=CITE, name=spec.name, files=spec.total_files, last=tasks - 1, tasks=tasks, cpus=cpus,
                        mem=mem, time=time, out=out,
                        partition=f"#SBATCH --partition={partition}" if partition else "")


def commands_text(spec: DatasetSpec) -> str:
    """One shell line per file, e.g. for GNU parallel:  parallel < commands.txt"""
    return "\n".join(f"{j.command} > {j.relpath}" for j in compile_spec(spec)) + "\n"


def export(spec: DatasetSpec, folder: str | Path, **kw) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    spec.save(folder / "spec.json")
    s = folder / f"run_{spec.name}.slurm"
    s.write_text(slurm_script(spec, **kw))
    c = folder / "commands.txt"
    c.write_text(commands_text(spec))
    return [folder / "spec.json", s, c]
