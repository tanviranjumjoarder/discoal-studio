# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""The dataset spec: everything a user enters, in physical units.

The app converts to discoal's scaled units (theta = 4NuL, rho = 4NrL,
alpha = 2Ns, times in 4N generations), so users never do that by hand.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .priors import Prior, fixed


class SizeChange(BaseModel):
    """Instantaneous size change, going back in time (discoal -en)."""
    generations_ago: Prior
    size: Prior  # new absolute population size (diploid individuals)
    population: int = Field(0, ge=0)  # which population (0 unless you use several)


class GeneConversion(BaseModel):
    """Either -gr (initiation rate = rho x ratio) or -g (an absolute rate per bp per generation)."""
    conversion_to_crossover_ratio: float | None = Field(None, gt=0)   # -gr
    rate_per_bp: float | None = Field(None, gt=0)                     # -g, scaled 4*N*g*L by the app
    mean_tract_length: float = Field(gt=0)

    @model_validator(mode="after")
    def _one(self):
        if (self.conversion_to_crossover_ratio is None) == (self.rate_per_bp is None):
            raise ValueError("gene conversion: give either conversion_to_crossover_ratio or rate_per_bp")
        return self


class Population(BaseModel):
    """One sampled population (discoal -p). Population 0 is the one where sweeps happen."""
    name: str = Field("pop", pattern=r"^[A-Za-z0-9_-]+$")
    sample_size: int = Field(ge=0)      # haplotypes sampled from it today


class Split(BaseModel):
    """discoal -ed: going back in time, `population` joins `into` (a population split, forward in time)."""
    generations_ago: Prior
    population: int = Field(ge=0)
    into: int = Field(ge=0)


class Admixture(BaseModel):
    """discoal -ea: going back in time, `daughter` splits into two founders (admixture, forward in time)."""
    generations_ago: Prior
    daughter: int = Field(ge=0)
    founder1: int = Field(ge=0)
    founder2: int = Field(ge=0)
    proportion: Prior                 # share of lineages that go to founder1


class Migration(BaseModel):
    """discoal -M (all pairs, when from_pop/to_pop are empty) or -m from_pop to_pop.
    rate is the fraction of migrants per generation; the app passes 4*N*m."""
    rate: Prior
    from_pop: int | None = Field(None, ge=0)
    to_pop: int | None = Field(None, ge=0)


class AncientSample(BaseModel):
    """discoal -A: `size` of the haplotypes are sampled `generations_ago` instead of today."""
    size: int = Field(ge=1)
    population: int = Field(0, ge=0)
    generations_ago: Prior


class ConditionalRecombination(BaseModel):
    """discoal -C: keep only replicates with a recombination event between these two sites during the sweep
    (discoal repeats the simulation until one has it, so a narrow window can take long)."""
    left_site: int = Field(ge=0)
    right_site: int = Field(ge=0)


# discoal's own -P priors draw new values for every replicate inside one file. They are the only flags
# the app does not set itself, so they are the only ones allowed as extra arguments (count = numbers after it).
PRIOR_FLAGS = {"-Pt": 2, "-Pr": 2, "-Pre": 2, "-Pa": 2, "-Pu": 2, "-PuA": 2, "-Px": 2, "-Pf": 2, "-Pc": 2,
               "-Pe1": 4, "-Pe2": 4}


def parse_prior_args(text: str) -> list[str]:
    """Check and split extra discoal -P arguments, e.g. "-Pa 100 1000 -Pu 0 0.05"."""
    toks, out, i = text.split(), [], 0
    while i < len(toks):
        flag = toks[i]
        if flag not in PRIOR_FLAGS:
            raise ValueError(f"extra discoal arguments: {flag!r} is not one of {', '.join(PRIOR_FLAGS)} "
                             "(every other discoal option has its own field)")
        vals = toks[i + 1:i + 1 + PRIOR_FLAGS[flag]]
        if len(vals) < PRIOR_FLAGS[flag]:
            raise ValueError(f"extra discoal arguments: {flag} needs {PRIOR_FLAGS[flag]} numbers")
        for v in vals:
            float(v)
        out += [flag, *vals]
        i += 1 + PRIOR_FLAGS[flag]
    return out


class Sweep(BaseModel):
    mode: Literal["stochastic", "deterministic", "neutral"] = "stochastic"  # -ws / -wd / -wn
    s: Prior                                       # selection coefficient
    f0: Prior = fixed(0)                           # 0 = hard sweep; >0 = soft sweep from standing variation
    tau: Prior = fixed(0)                          # generations since the sweep ended
    position: Prior = fixed(0.5)                   # where the selected site sits, 0..1
    partial_final_freq: Prior | None = None        # -c: stop the sweep at this frequency
    recurrent_theta_a: Prior | None = None         # -uA: recurrent beneficial mutation, scaled 4N*uA
    # Everything below is optional and drawn after the fields above, so older specs give the same files.
    location: Literal["in_window", "left_of_window"] = "in_window"   # left: -ls/-ld/-ln
    left_distance_bp: Prior | None = None          # distance of an off-window sweep, bp (passed as 4*N*r*d)
    recurrent_rate: Prior | None = None            # -R (at the locus) / -L (to the side): recurrent hitchhiking
    recurrent_side: bool = False                   # True = -L
    effective_size: Prior | None = None            # -N: population size used for the sweep trajectory
    time_step: float | None = Field(None, gt=0)    # -i: sweep time increment scalar (discoal default 400)
    hide_selected_snp: bool = False                # -h: drop the selected site from partial-sweep output
    recombination_during_sweep: ConditionalRecombination | None = None   # -C

    @model_validator(mode="after")
    def _left(self):
        if self.location == "left_of_window" and self.left_distance_bp is None and self.recurrent_rate is None:
            raise ValueError("a sweep left of the window needs left_distance_bp")
        return self


class DatasetClass(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    count: int = Field(ge=1)
    sweep: Sweep | None = None                      # None = neutral
    label: str | None = None                        # ML label; classes may share one (default: the name)
    extra_args: str = ""                            # discoal -P priors only, e.g. "-Pa 100 1000"

    @field_validator("extra_args")
    @classmethod
    def _extra(cls, v):
        parse_prior_args(v)
        return v.strip()


class DatasetSpec(BaseModel):
    """A whole dataset. Parameters are drawn per file, in the order listed."""
    name: str = "my_dataset"
    description: str = ""
    seed: str = "1"                                # each file's RNG starts from "{seed}-{class}-{i}"
    sample_size: int = Field(198, ge=2)             # haplotypes per replicate
    replicates_per_file: int = Field(1, ge=1)
    sites: int = Field(1_100_000, ge=1)             # region length in bp
    N: Prior = Prior(dist="uniform_int", low=5000, high=30000)
    mu: Prior = Prior(dist="uniform", low=2.21e-9, high=2.21e-8)
    r: Prior = Prior(dist="truncated_exponential", mean=1e-8, upper=3e-8)
    demography: list[SizeChange] = []
    gene_conversion: GeneConversion | None = None
    classes: list[DatasetClass]
    folder_per_class: bool = True                   # Neutral/neutral_1.ms like the lab layout
    # Optional discoal features; each one only draws values when it is used.
    populations: list[Population] = []             # -p (two or more); sample sizes add up to sample_size
    splits: list[Split] = []                        # -ed
    admixture: list[Admixture] = []                 # -ea
    migration: list[Migration] = []                 # -M / -m
    ancient_samples: list[AncientSample] = []       # -A
    mutations_until: Prior | None = None            # -U: only mutations younger than this (generations)
    tree_output: bool = False                       # -T: Newick trees instead of haplotypes

    @field_validator("classes")
    @classmethod
    def _unique(cls, v):
        names = [c.name for c in v]
        if len(set(names)) != len(names):
            raise ValueError("class names must be different")
        if not v:
            raise ValueError("add at least one class")
        return v

    @model_validator(mode="after")
    def _sanity(self):
        if self.sample_size > 10_000:
            raise ValueError("sample_size above 10,000 is almost surely a typo")
        npop = max(1, len(self.populations))
        if len(self.populations) == 1:
            raise ValueError("populations: list two or more, or none for a single population")
        if self.populations and sum(p.sample_size for p in self.populations) != self.sample_size:
            raise ValueError(f"population sample sizes add up to {sum(p.sample_size for p in self.populations)}, "
                             f"but sample_size is {self.sample_size}")
        refs = [("demography", e.population) for e in self.demography]
        refs += [("splits", i) for e in self.splits for i in (e.population, e.into)]
        refs += [("admixture", i) for e in self.admixture for i in (e.daughter, e.founder1, e.founder2)]
        refs += [("migration", i) for e in self.migration for i in (e.from_pop, e.to_pop) if i is not None]
        refs += [("ancient_samples", e.population) for e in self.ancient_samples]
        for where, i in refs:
            if i >= npop:
                raise ValueError(f"{where}: population {i} does not exist (populations are numbered from 0)")
        if (self.splits or self.migration) and npop < 2:
            raise ValueError("splits and migration need two or more populations")
        for m in self.migration:
            if (m.from_pop is None) != (m.to_pop is None):
                raise ValueError("migration: give both from_pop and to_pop, or neither for all pairs")
        if sum(a.size for a in self.ancient_samples) >= self.sample_size:
            raise ValueError("ancient samples must be fewer than sample_size")
        for c in self.classes:
            cr = c.sweep.recombination_during_sweep if c.sweep else None
            if cr and not cr.left_site < cr.right_site <= self.sites:
                raise ValueError(f"{c.name}: recombination_during_sweep needs left_site < right_site <= sites")
        return self

    @property
    def label_names(self) -> list[str]:
        """ML labels in first-seen order."""
        return list(dict.fromkeys(c.label or c.name for c in self.classes))

    @property
    def total_files(self) -> int:
        return sum(c.count for c in self.classes)

    @classmethod
    def load(cls, path: str | Path) -> "DatasetSpec":
        return cls.model_validate_json(Path(path).read_text())

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2, exclude_none=True))


PRESET_DIR = Path(__file__).parent / "presets"


def presets() -> dict[str, DatasetSpec]:
    return {p.stem: DatasetSpec.load(p) for p in sorted(PRESET_DIR.glob("*.json"))}


def preset_descriptions() -> dict[str, str]:
    out = {}
    for p in sorted(PRESET_DIR.glob("*.json")):
        out[p.stem] = json.loads(p.read_text()).get("description", "")
    return out
