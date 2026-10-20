# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Read .ms files, compute quality-check statistics, and export ML-ready arrays."""
from __future__ import annotations

import csv
import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import CITE
from .spec import DatasetSpec


@dataclass
class Replicate:
    positions: np.ndarray     # (S,) float in [0, 1]
    haps: np.ndarray          # (n, S) uint8 of 0/1


def read_ms(path: str | Path, n: int) -> list[Replicate]:
    lines = Path(path).read_bytes().split(b"\n")
    reps, i = [], 0
    while i < len(lines):
        if lines[i].startswith(b"//"):
            S = int(lines[i + 1].split(b":")[1])
            if S == 0:
                reps.append(Replicate(np.zeros(0), np.zeros((n, 0), np.uint8)))
                i += 2
                continue
            pos = np.array(lines[i + 2].split(b":")[1].split(), dtype=float)
            rows = lines[i + 3:i + 3 + n]
            haps = (np.frombuffer(b"".join(r.strip() for r in rows), np.uint8).reshape(n, S) - 48)
            reps.append(Replicate(pos, haps))
            i += 3 + n
        else:
            i += 1
    return reps


def central(rep: Replicate, k: int, center: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """The k SNPs closest to `center`, in genomic order."""
    S = rep.positions.size
    if S <= k:
        return rep.positions, rep.haps
    mid = int(np.searchsorted(rep.positions, center))
    lo = min(max(0, mid - k // 2), S - k)
    return rep.positions[lo:lo + k], rep.haps[:, lo:lo + k]


def garud_h(haps: np.ndarray) -> tuple[float, float, int]:
    """H12 and H2/H1 (Garud et al. 2015) plus number of distinct haplotypes."""
    if haps.shape[1] == 0:
        return 1.0, 0.0, 1
    _, counts = np.unique(haps, axis=0, return_counts=True)
    p = np.sort(counts / counts.sum())[::-1]
    h1 = float((p ** 2).sum())
    h12 = float(h1 + 2 * p[0] * p[1]) if p.size > 1 else h1
    h2 = h1 - p[0] ** 2
    return h12, float(h2 / h1), int(p.size)


def stats(rep: Replicate, window: int = 200) -> dict:
    n, S = rep.haps.shape
    a1 = sum(1 / i for i in range(1, n))
    a2 = sum(1 / i ** 2 for i in range(1, n))
    d = rep.haps.sum(axis=0).astype(float)
    pi = float((2 * d * (n - d) / (n * (n - 1))).sum())
    tw = S / a1
    b1, b2 = (n + 1) / (3 * (n - 1)), 2 * (n * n + n + 3) / (9 * n * (n - 1))
    c1, c2 = b1 - 1 / a1, b2 - (n + 2) / (a1 * n) + a2 / a1 ** 2
    e1, e2 = c1 / a1, c2 / (a1 ** 2 + a2)
    var = e1 * S + e2 * S * (S - 1)
    D = (pi - tw) / math.sqrt(var) if var > 0 else 0.0
    h12, h2h1, nh = garud_h(central(rep, window)[1])
    return {"segsites": S, "pi": pi, "theta_w": tw, "tajimas_d": D, "h12": h12, "h2_h1": h2h1, "haplotypes": nh}


def _files(spec: DatasetSpec, out: Path):
    for c in spec.classes:
        for i in range(1, c.count + 1):
            folder = c.name.capitalize() + "/" if spec.folder_per_class else ""
            p = out / f"{folder}{c.name}_{i}.ms"
            if p.exists():
                yield c.name, p


def qc(out: str | Path, window: int = 200, workers: int = 4, on_progress=None) -> dict:
    """Compute statistics for every file; write qc_stats.csv and return per-class summaries."""
    out = Path(out)
    spec = DatasetSpec.load(out / "spec.json")
    if spec.tree_output:
        raise RuntimeError("This dataset holds trees (-T), not haplotypes, so there are no statistics to compute.")
    files = list(_files(spec, out))

    def one(item):
        cls, p = item
        rep = read_ms(p, spec.sample_size)[0]
        return {"file": p.name, "class": cls, **stats(rep, window)}

    rows = []
    with ThreadPoolExecutor(workers) as pool:
        for k, r in enumerate(pool.map(one, files), 1):
            rows.append(r)
            if on_progress and k % 25 == 0:
                on_progress(k, len(files))
    if not rows:
        raise RuntimeError("No .ms files found to check.")
    with open(out / "qc_stats.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    keys = [k for k in rows[0] if k not in ("file", "class")]
    summary = {}
    for c in spec.classes:
        sub = [r for r in rows if r["class"] == c.name]
        if sub:
            summary[c.name] = {k: {"median": float(np.median([r[k] for r in sub])),
                                   "values": [r[k] for r in sub]} for k in keys}
    (out / "qc_summary.json").write_text(json.dumps(
        {c: {k: v["median"] for k, v in s.items()} for c, s in summary.items()}, indent=2))
    return summary


def export_ml(out: str | Path, snps: int = 201, sort_rows: bool = True, workers: int = 4,
              on_progress=None) -> Path:
    """Fixed-size haplotype images for CNNs: X (files, n, snps) uint8, positions, labels.

    Takes the `snps` sites closest to each file's sweep position (0.5 by default;
    the real one if it was drawn), pads with zeros if fewer, and (optionally) sorts
    haplotypes from most to least common, a standard step for sweep classifiers.
    """
    out = Path(out)
    spec = DatasetSpec.load(out / "spec.json")
    if spec.tree_output:
        raise RuntimeError("This dataset holds trees (-T), not haplotypes, so there is nothing to export.")
    names = spec.label_names
    label_of = {c.name: c.label or c.name for c in spec.classes}
    files = list(_files(spec, out))
    centers = {}
    for c in spec.classes:
        tab = out / f"params_{c.name}.csv"
        if tab.exists():
            with open(tab) as fh:
                for row in csv.DictReader(fh):
                    if row.get("x"):
                        centers[row["file"]] = float(row["x"])
    n = spec.sample_size
    X = np.zeros((len(files), n, snps), np.uint8)
    P = np.full((len(files), snps), -1.0, np.float32)

    def one(k):
        cls, p = files[k]
        rep = read_ms(p, n)[0]
        pos, h = central(rep, snps, centers.get(p.name, 0.5))
        if sort_rows and h.shape[1]:
            uniq, inv, cnt = np.unique(h, axis=0, return_inverse=True, return_counts=True)
            order = np.argsort(-cnt[inv.ravel()], kind="stable")
            h = h[order]
        X[k, :, :h.shape[1]] = h
        P[k, :pos.size] = pos
        return k

    with ThreadPoolExecutor(workers) as pool:
        for done, _ in enumerate(pool.map(one, range(len(files))), 1):
            if on_progress and done % 25 == 0:
                on_progress(done, len(files))
    y = np.array([names.index(label_of[c]) for c, _ in files], np.int16)
    dest = out / "ml" / f"haplotypes_{snps}snps.npz"
    dest.parent.mkdir(exist_ok=True)
    np.savez_compressed(dest, X=X, positions=P, y=y, classes=np.array(names),
                        files=np.array([p.name for _, p in files]),
                        source_class=np.array([c for c, _ in files]),
                        made_with=np.array(CITE))
    return dest
