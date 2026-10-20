# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Describe a dataset in plain English; get a DatasetSpec back.

Claude only fills in the typed DatasetSpec (through the ``propose_spec`` tool,
whose input schema is the spec's JSON schema). It never writes discoal
commands: the compiler does that, the same way as for the form. Every proposal
is validated and run through ``compiler.check()``; problems go back to Claude
as a tool error so it can fix them. Nothing is simulated here - the caller
shows the spec to the user, who decides whether to press Generate.

Optional feature: ``pip install "discoal-studio[assistant]"`` and set
ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from pydantic import ValidationError

from .compiler import check, compile_one
from .spec import DatasetSpec, preset_descriptions, presets

MODEL = os.environ.get("DISCOAL_STUDIO_MODEL", "claude-opus-5-5")
MAX_ROUNDS = 4

SYSTEM = """You turn a population geneticist's plain-English request into a dataset spec for discoal Studio, \
an app that simulates selective-sweep datasets with the coalescent simulator discoal.

Your only output is a call to the propose_spec tool with a complete spec (JSON matching its schema) and a short \
summary. Never write discoal commands or scaled parameters: the app converts physical units itself \
(theta = 4*N*mu*L, rho = 4*N*r*L, alpha = 2*N*s, times / 4N).

Units and conventions:
- sample_size is haplotypes = 2 x diploid individuals ("99 individuals" -> 198). If the user says \
"chromosomes", "haplotypes" or "samples", use the number as given.
- sites is the region length in bp ("1.1 Mb" -> 1100000, "100 kb" -> 100000).
- N is the diploid population size; mu and r are per bp per generation.
- Every random quantity is a prior: {"dist": "fixed", "value": v}, {"dist": "uniform"|"uniform_int"|"loguniform", \
"low": a, "high": b} or {"dist": "truncated_exponential", "mean": m, "upper": u}. Use uniform_int for N when a range \
of whole numbers is given. "Log-uniform"/"log-scale" means loguniform. Bounds may be expressions over values \
drawn earlier for the same file: N, mu, r, L, n, and inside a sweep s, f0, tau (in that order), e.g. "1/(2*N)".
- One class per kind of file. A class without "sweep" is neutral. A sweep has mode stochastic (default), \
deterministic or neutral; s = selection coefficient; f0 = start frequency (fixed 0 = hard sweep, > 0 = soft sweep \
from standing variation); tau = generations since the sweep ended (0 = just finished); position = selected site \
along the region, 0..1 (0.5 = centre); partial_final_freq = the sweep stops at that frequency (partial sweep); \
recurrent_theta_a = recurrent beneficial mutation 4*N*uA.
- demography is a list of instantaneous size changes going back in time (generations_ago, new size in individuals).
- Optional discoal features, only when asked for: several populations (populations with per-population sample sizes adding up to sample_size; splits, admixture, migration with rates as fraction of migrants per generation), ancient_samples, gene_conversion by rate_per_bp, mutations_until, tree_output, and per sweep: location left_of_window with left_distance_bp, recurrent_rate (recurrent hitchhiking), effective_size, time_step, hide_selected_snp, recombination_during_sweep. A class's label sets its ML label (classes may share one). Leave extra_args empty.
- Class names: short, lower case, letters/digits/_/- only (e.g. neutral, hard, soft, sweep, partial). Keep \
the user's names and order when they give them.
- Leave out any field the user did not mention, so the app's defaults apply. When a request matches or modifies \
one of the presets below, call get_preset first and start from its exact values (including seed and name).
- If the request includes a current spec, treat the new request as an edit of it and keep everything else.

If propose_spec returns problems, fix them and call it again. If a warning reflects what the user explicitly \
asked for, call propose_spec again with the same spec and accept_warnings set to true. The summary is 1-3 plain \
sentences for the user to confirm, mentioning any assumption you made.

Presets:
"""


class AssistantError(RuntimeError):
    """Something the user should see (missing key, refusal, no usable spec)."""


@dataclass
class Draft:
    spec: DatasetSpec
    summary: str                      # Claude's words
    outline: list[str]                # facts computed from the spec itself, not from Claude
    warnings: list[str]               # compiler.check() output the user still has to accept
    rounds: int                       # API calls used
    usage: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"spec": self.spec.model_dump(exclude_none=True), "summary": self.summary,
                "outline": self.outline, "warnings": self.warnings, "rounds": self.rounds,
                "model": MODEL, "usage": self.usage}


def available() -> str | None:
    """None if the assistant can run, otherwise a reason to show the user."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return 'The assistant needs the Anthropic SDK: pip install "discoal-studio[assistant]"'
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return "Set ANTHROPIC_API_KEY to use the assistant (the form works without it)."
    return None


def _schema() -> dict:
    s = DatasetSpec.model_json_schema(ref_template="#/$defs/{model}")
    defs = s.pop("$defs", {})
    defs["DatasetSpec"] = s
    return {
        "type": "object",
        "properties": {
            "spec": {"$ref": "#/$defs/DatasetSpec"},
            "summary": {"type": "string", "description": "1-3 plain sentences describing the dataset for the user"},
            "accept_warnings": {"type": "boolean",
                                "description": "true only when the remaining warnings are what the user asked for"},
        },
        "required": ["spec", "summary"],
        "$defs": defs,
    }


def tools() -> list[dict]:
    return [
        {"name": "get_preset",
         "description": "Return the full spec of a built-in preset, to copy or modify.",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string", "enum": sorted(presets())}},
                          "required": ["name"]}},
        {"name": "propose_spec",
         "description": "Propose the finished dataset spec. The app validates it and checks it by drawing "
                        "parameters; problems come back as an error to fix.",
         "input_schema": _schema()},
    ]


def system_prompt() -> str:
    return SYSTEM + "\n".join(f"- {k}: {v}" for k, v in preset_descriptions().items())


def outline(spec: DatasetSpec) -> list[str]:
    """Plain facts read straight off the spec, so the user can check Claude's summary against them."""
    hap = spec.sample_size
    lines = [f"{spec.total_files:,} files of {spec.replicates_per_file} replicate(s); "
             f"{hap} haplotypes ({hap / 2:g} diploid individuals); {spec.sites:,} bp",
             f"N {spec.N.describe()} · μ {spec.mu.describe()} · r {spec.r.describe()} · seed {spec.seed!r}"]
    for ev in spec.demography:
        lines.append(f"size change to {ev.size.describe()} at {ev.generations_ago.describe()} generations ago")
    if spec.gene_conversion:
        gc = spec.gene_conversion
        lines.append(f"gene conversion ratio {gc.conversion_to_crossover_ratio:g}, tract {gc.mean_tract_length:g} bp")
    for c in spec.classes:
        if not c.sweep:
            lines.append(f"{c.name}: {c.count:,} neutral files")
            continue
        sw = c.sweep
        kind = "hard" if sw.f0.dist == "fixed" and float(sw.f0.value) == 0 else "soft"
        bits = [f"{c.name}: {c.count:,} {kind} sweep files ({sw.mode})", f"s {sw.s.describe()}"]
        if kind == "soft":
            bits.append(f"f0 {sw.f0.describe()}")
        bits += [f"ended {sw.tau.describe()} gen ago", f"position {sw.position.describe()}"]
        if sw.partial_final_freq:
            bits.append(f"partial, stops at {sw.partial_final_freq.describe()}")
        if sw.recurrent_theta_a:
            bits.append(f"recurrent θA {sw.recurrent_theta_a.describe()}")
        lines.append(", ".join(bits))
    return lines


def review(raw: dict) -> tuple[DatasetSpec | None, list[str], list[str]]:
    """Validate a proposed spec dict. Returns (spec or None, errors, warnings)."""
    try:
        spec = DatasetSpec.model_validate(raw)
    except ValidationError as e:
        return None, ["{}: {}".format(".".join(str(x) for x in err["loc"]) or "spec", err["msg"])
                      for err in e.errors()], []
    errors = []
    for c in spec.classes:  # a spec that cannot compile is an error, never an acceptable warning
        for i in range(1, min(c.count, 20) + 1):
            try:
                compile_one(spec, c, i)
            except Exception as e:  # noqa: BLE001 - bad expressions, N <= 0, ...
                errors.append(f"{c.name}: {e}")
                break
    if errors:
        return spec, errors, []
    return spec, [], check(spec)


def _client():
    try:
        import anthropic
    except ImportError as e:
        raise AssistantError(available()) from e
    return anthropic.Anthropic()


def _call(client, messages: list) -> object:
    import anthropic
    try:
        return client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=system_prompt(), tools=tools(), messages=messages,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise AssistantError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.") from e
    except anthropic.RateLimitError as e:
        raise AssistantError("The Anthropic API is rate limiting this key; try again in a minute.") from e
    except anthropic.APIStatusError as e:
        raise AssistantError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AssistantError("Could not reach the Anthropic API (offline?).") from e


def draft(prompt: str, current: dict | None = None, client=None, max_rounds: int = MAX_ROUNDS) -> Draft:
    """Ask Claude for a spec matching ``prompt`` (optionally an edit of ``current``)."""
    if not prompt.strip():
        raise AssistantError("Describe the dataset first.")
    if client is None:
        reason = available()
        if reason:
            raise AssistantError(reason)
        client = _client()
    text = prompt.strip()
    if current:
        text = f"Current spec:\n```json\n{json.dumps(current, indent=1)}\n```\n\nRequest: {text}"
    messages: list = [{"role": "user", "content": text}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    last: tuple[DatasetSpec, str, list[str]] | None = None
    said = ""

    for rounds in range(1, max_rounds + 1):
        resp = _call(client, messages)
        for k in usage:
            usage[k] += getattr(resp.usage, k, 0) or 0
        if resp.stop_reason == "refusal":
            raise AssistantError("Claude declined this request.")
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            if last:
                break
            said = " ".join(b.text for b in resp.content if b.type == "text").strip() or said
            messages.append({"role": "user", "content": "Please call propose_spec with the spec."})
            continue

        results = []
        for b in calls:
            if b.name == "get_preset":
                p = presets().get(b.input.get("name", ""))
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": p is None,
                                "content": p.model_dump_json(exclude_none=True) if p else "no such preset"})
                continue
            if b.name != "propose_spec":
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                "content": f"unknown tool {b.name}"})
                continue
            spec, errors, warnings = review(b.input.get("spec") or {})
            summary = str(b.input.get("summary", "")).strip()
            if spec and not errors:
                last = (spec, summary, warnings)
                if not warnings or b.input.get("accept_warnings"):
                    return Draft(spec, summary, outline(spec), warnings, rounds, usage)
            problems = [f"error: {e}" for e in errors] + [f"warning: {w}" for w in warnings]
            results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                            "content": "Please fix and call propose_spec again:\n" + "\n".join(problems)})
        messages.append({"role": "user", "content": results})

    if last:  # out of rounds with a valid spec: hand it over with its warnings for the user to judge
        spec, summary, warnings = last
        return Draft(spec, summary, outline(spec), warnings, rounds, usage)
    raise AssistantError(said or "Could not turn that into a valid spec; try rephrasing or use the form.")
