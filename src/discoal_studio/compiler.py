# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Turn a DatasetSpec into one discoal command per file (no simulation here).

Fully deterministic: the same spec always gives the same commands, seeds and
table, because each file's RNG is seeded from the text "{seed}-{class}-{i}".
For the lab preset this reproduces make_dataset.py byte for byte.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterator

from .priors import Prior
from .spec import DatasetClass, DatasetSpec

SEED_MAX = 2_000_000_000


def g(v: float) -> str:
    """A number with 10 significant digits: short but exact enough for discoal."""
    return f"{v:.10g}"


@dataclass
class Job:
    cls: str
    index: int
    relpath: str               # where the .ms file goes, relative to the output folder
    argv: list[str]            # argv[0] is "discoal"
    row: dict = field(default_factory=dict)

    @property
    def command(self) -> str:
        return " ".join(self.argv)


def _draw(prior: Prior, rng: random.Random, env: dict) -> float:
    return prior.sample(rng, env)


def compile_one(spec: DatasetSpec, c: DatasetClass, i: int) -> Job:
    rng = random.Random(f"{spec.seed}-{c.name}-{i}")
    env: dict[str, float] = {"L": spec.sites, "n": spec.sample_size}
    L = spec.sites
    N = env["N"] = _draw(spec.N, rng, env)
    mu = env["mu"] = _draw(spec.mu, rng, env)
    r = env["r"] = _draw(spec.r, rng, env)
    if N <= 0:
        raise ValueError(f"{c.name}_{i}: N must be > 0 (got {N})")

    fname = f"{c.name}_{i}.ms"
    row = dict(file=fname, N=N, mu=mu, r=r, s=0, theta=4 * N * mu * L, rho=4 * N * r * L)
    extra: list[str] = []

    if spec.populations:   # -p must come before -m/-M
        extra += ["-p", str(len(spec.populations))] + [str(p.sample_size) for p in spec.populations]

    if spec.gene_conversion:
        gc = spec.gene_conversion
        if gc.conversion_to_crossover_ratio is not None:
            extra += ["-gr", g(gc.conversion_to_crossover_ratio), g(gc.mean_tract_length)]
        else:
            extra += ["-g", g(4 * N * gc.rate_per_bp * L), g(gc.mean_tract_length)]

    events = []
    for k, ev in enumerate(spec.demography, 1):
        t = _draw(ev.generations_ago, rng, env)
        size = _draw(ev.size, rng, env)
        row[f"en{k}_generations"], row[f"en{k}_size"] = t, size
        events.append((t, size, ev.population))
    for t, size, pop in sorted(events):
        extra += ["-en", g(t / (4 * N)), str(pop), g(size / N)]

    # Optional features below draw nothing when unused, so older specs keep their exact draws.
    for k, ev in enumerate(spec.splits, 1):
        t = row[f"ed{k}_generations"] = _draw(ev.generations_ago, rng, env)
        extra += ["-ed", g(t / (4 * N)), str(ev.population), str(ev.into)]
    for k, ev in enumerate(spec.admixture, 1):
        t = row[f"ea{k}_generations"] = _draw(ev.generations_ago, rng, env)
        prop = row[f"ea{k}_proportion"] = _draw(ev.proportion, rng, env)
        extra += ["-ea", g(t / (4 * N)), str(ev.daughter), str(ev.founder1), str(ev.founder2), g(prop)]
    for k, m in enumerate(spec.migration, 1):
        rate = row[f"m{k}_rate"] = _draw(m.rate, rng, env)
        if m.from_pop is None:
            extra += ["-M", g(4 * N * rate)]
        else:
            extra += ["-m", str(m.from_pop), str(m.to_pop), g(4 * N * rate)]
    for k, a in enumerate(spec.ancient_samples, 1):
        t = row[f"A{k}_generations"] = _draw(a.generations_ago, rng, env)
        extra += ["-A", str(a.size), str(a.population), g(t / (4 * N))]
    if spec.mutations_until is not None:
        t = row["U_generations"] = _draw(spec.mutations_until, rng, env)
        extra += ["-U", g(t / (4 * N))]
    if spec.tree_output:
        extra += ["-T"]

    sweep: list[str] = []
    if c.sweep:
        sw = c.sweep
        s = env["s"] = _draw(sw.s, rng, env)
        f0 = env["f0"] = _draw(sw.f0, rng, env)
        tau = env["tau"] = _draw(sw.tau, rng, env)
        x = _draw(sw.position, rng, env)
        row.update(s=s, f0=f0, tau=tau, alpha=2 * N * s)
        if sw.position.is_random:
            row["x"] = x
        cfin = ua = None
        if sw.partial_final_freq is not None:
            cfin = row["c"] = _draw(sw.partial_final_freq, rng, env)
        if sw.recurrent_theta_a is not None:
            ua = row["uA"] = _draw(sw.recurrent_theta_a, rng, env)
        n_sweep = dist = rhh = None
        if sw.effective_size is not None:
            n_sweep = row["N_sweep"] = _draw(sw.effective_size, rng, env)
        if sw.left_distance_bp is not None:
            dist = row["left_distance_bp"] = _draw(sw.left_distance_bp, rng, env)
        if sw.recurrent_rate is not None:
            rhh = row["rhh_rate"] = _draw(sw.recurrent_rate, rng, env)

        letter = {"stochastic": "s", "deterministic": "d", "neutral": "n"}[sw.mode]
        if rhh is not None:            # recurrent hitchhiking: discoal places the sweeps itself
            sweep = ["-L" if sw.recurrent_side else "-R", g(rhh), "-a", g(2 * N * s)]
        elif sw.location == "left_of_window":
            sweep = [f"-l{letter}", g(tau / (4 * N)), g(4 * N * env["r"] * dist), "-a", g(2 * N * s)]
        else:
            sweep = [f"-w{letter}", g(tau / (4 * N)), "-a", g(2 * N * s)]
        if f0 > 0:
            sweep += ["-f", g(f0)]
        if rhh is None and sw.location == "in_window":
            sweep += ["-x", g(x)]
        if cfin is not None:
            sweep += ["-c", g(cfin)]
        if ua is not None:
            sweep += ["-uA", g(ua)]
        if n_sweep is not None:
            sweep += ["-N", str(round(n_sweep))]
        if sw.time_step is not None:
            sweep += ["-i", g(sw.time_step)]
        if sw.hide_selected_snp:
            sweep += ["-h"]
        if sw.recombination_during_sweep:
            cr = sw.recombination_during_sweep
            sweep += ["-C", str(cr.left_site), str(cr.right_site)]
    sweep += c.extra_args.split()

    row["seed1"], row["seed2"] = rng.randint(1, SEED_MAX), rng.randint(1, SEED_MAX)
    argv = ["discoal", str(spec.sample_size), str(spec.replicates_per_file), str(L),
            "-t", g(row["theta"]), "-r", g(row["rho"])] + extra + \
           ["-d", str(row["seed1"]), str(row["seed2"])] + sweep
    row["command"] = " ".join(argv)
    folder = c.name.capitalize() + "/" if spec.folder_per_class else ""
    return Job(c.name, i, folder + fname, argv, row)


def compile_spec(spec: DatasetSpec) -> Iterator[Job]:
    for c in spec.classes:
        for i in range(1, c.count + 1):
            yield compile_one(spec, c, i)


def check(spec: DatasetSpec, sample: int = 200) -> list[str]:
    """Draw a sample of files and return plain-language warnings (empty = looks fine)."""
    warn: set[str] = set()
    for c in spec.classes:
        for i in range(1, min(c.count, sample) + 1):
            try:
                j = compile_one(spec, c, i)
            except Exception as e:  # noqa: BLE001 - report every kind of bad input
                warn.add(f"{c.name}: {e}")
                continue
            row = j.row
            if row["theta"] > 20_000:
                warn.add(f"{c.name}: theta up to {row['theta']:.0f} - files will be very large and slow")
            if row["rho"] > 20_000:
                warn.add(f"{c.name}: rho up to {row['rho']:.0f} - simulations may be very slow")
            if c.sweep:
                if not 0 <= row["f0"] < 1:
                    warn.add(f"{c.name}: f0 must be between 0 and 1 (got {row['f0']:.3g})")
                if row["alpha"] < 1:
                    warn.add(f"{c.name}: alpha = 2Ns below 1, the sweep is nearly neutral")
                if "c" in row and not row["f0"] < row["c"] < 1:
                    warn.add(f"{c.name}: partial sweep end frequency must be above f0 and below 1")
                if "-x" in j.argv and not 0 <= float(j.argv[j.argv.index("-x") + 1]) <= 1:
                    warn.add(f"{c.name}: sweep position must be between 0 and 1")
    for c in spec.classes:
        sw = c.sweep
        if sw and sw.recurrent_rate is not None and sw.effective_size is None:
            warn.add(f"{c.name}: recurrent hitchhiking with discoal's default sweep population size (1,000,000) "
                     "is very slow; set the sweep population size (-N), e.g. to N")
        if sw and sw.recombination_during_sweep:
            warn.add(f"{c.name}: -C repeats each simulation until it recombines in the window; narrow windows are slow")
    if spec.tree_output:
        warn.add("tree output (-T) writes Newick trees: quality check and ML export need haplotypes and will not work")
    for ev in spec.demography:
        if ev.generations_ago.dist == "fixed" and float(ev.generations_ago.value) < 0:
            warn.add("demography: generations_ago must be >= 0")
    return sorted(warn)
