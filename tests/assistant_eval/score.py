"""Benchmark for the plain-English assistant: field-level accuracy against expected specs.

    python tests/assistant_eval/score.py                    # live: calls Claude once per case (needs ANTHROPIC_API_KEY)
    python tests/assistant_eval/score.py --repeat 3         # 3 samples per case, to see run-to-run spread
    python tests/assistant_eval/score.py --rescore runs/X.json   # score saved responses again, no API calls
    python tests/assistant_eval/score.py --oracle           # feed the expected specs back in (scorer self-check: 100%)

Scoring: every value written in a case's "expected" is one field. Only listed fields count, so a case states
what its prompt determines and nothing else. Numbers match to 1e-9 relative error, expression strings match
ignoring spaces, {"$in": [...]} accepts any option, a dict option matches when its listed keys match,
null means "absent / neutral". Lists also score their length; classes pair up by name when the case gives
one, otherwise by position. "preset:NAME" expects every field of that preset; "reproduce" additionally
checks that the first 3 files of each class compile to the same discoal commands as the preset (byte equal).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path

from discoal_studio import assistant
from discoal_studio.compiler import compile_one
from discoal_studio.spec import DatasetSpec, presets

HERE = Path(__file__).parent


def load_cases() -> list[dict]:
    cases = json.loads((HERE / "cases.json").read_text())
    for c in cases:
        if isinstance(c["expected"], str) and c["expected"].startswith("preset:"):
            c["expected"] = presets()[c["expected"][7:]].model_dump(exclude_none=True)
            c["expected"].pop("description", None)   # free text, not a setting
    return cases


def _same(want, got) -> bool:
    if isinstance(want, dict) and "$in" in want:
        return any(_same(opt, got) for opt in want["$in"])
    if want is None:
        return got is None
    if isinstance(want, dict):
        return isinstance(got, dict) and all(_same(v, got.get(k)) for k, v in want.items())
    if isinstance(want, bool) or isinstance(got, bool):
        return want == got
    try:
        a, b = float(want), float(got)
        return a == b or abs(a - b) <= 1e-9 * max(abs(a), abs(b))
    except (TypeError, ValueError):
        return str(want).replace(" ", "") == str(got).replace(" ", "")


def compare(want, got, path: str = "") -> list[tuple[str, bool]]:
    """One (field path, correct) pair per expected leaf."""
    if isinstance(want, dict) and "$in" not in want:
        if not isinstance(got, dict):
            got = {}
        return [r for k, v in want.items() for r in compare(v, got.get(k), f"{path}.{k}".lstrip("."))]
    if isinstance(want, list):
        got = got if isinstance(got, list) else []
        out = [(f"{path}.length", len(want) == len(got))]
        used: set[int] = set()
        for i, w in enumerate(want):
            j = next((k for k, g in enumerate(got) if isinstance(w, dict) and "name" in w
                      and g.get("name") == w["name"] and k not in used), None)
            if j is None and i < len(got) and i not in used:
                j = i
            if j is not None:
                used.add(j)
            out += compare(w, got[j] if j is not None else None, f"{path}[{i}]")
        return out
    return [(path, _same(want, got))]


def reproduces(spec: DatasetSpec, preset: str) -> bool:
    ref = presets()[preset]
    if [(c.name, c.count) for c in spec.classes] != [(c.name, c.count) for c in ref.classes]:
        return False
    return all(compile_one(spec, a, i).command == compile_one(ref, b, i).command
               for a, b in zip(spec.classes, ref.classes) for i in (1, 2, 3))


def score_case(case: dict, response: dict) -> dict:
    """response: {"spec": dict} on success, or {"error": str}."""
    res = {"id": case["id"], **{k: response.get(k) for k in ("rounds", "warnings", "usage", "seconds", "error")}}
    if "spec" not in response:
        fields = compare(case["expected"], {})
        return {**res, "valid": False, "correct": 0, "total": len(fields), "accuracy": 0.0, "exact": False,
                "wrong": [p for p, _ in fields]}
    spec = DatasetSpec.model_validate(response["spec"])
    fields = compare(case["expected"], spec.model_dump())
    ok = sum(c for _, c in fields)
    res.update(valid=True, correct=ok, total=len(fields), accuracy=ok / len(fields),
               exact=ok == len(fields), wrong=[p for p, c in fields if not c])
    if case.get("reproduce"):
        res["byte_identical"] = reproduces(spec, case["reproduce"])
    return res


def ask(case: dict) -> dict:
    t0 = time.time()
    try:
        d = assistant.draft(case["prompt"])
        return {**d.as_dict(), "seconds": round(time.time() - t0, 1)}
    except assistant.AssistantError as e:
        return {"error": str(e), "seconds": round(time.time() - t0, 1)}


def report(rows: list[dict]) -> dict:
    n = len(rows)
    total = sum(r["total"] for r in rows)
    summary = {
        "cases": n,
        "valid_rate": sum(r["valid"] for r in rows) / n,
        "exact_rate": sum(r["exact"] for r in rows) / n,
        "field_accuracy_micro": sum(r["correct"] for r in rows) / total,
        "field_accuracy_macro": statistics.mean(r["accuracy"] for r in rows),
        "accepted_with_warnings": sum(bool(r.get("warnings")) for r in rows),
        "byte_identical": [r["byte_identical"] for r in rows if "byte_identical" in r],
    }
    if any(r.get("rounds") for r in rows):
        summary["mean_rounds"] = statistics.mean(r["rounds"] or 0 for r in rows)
    width = max(len(r["id"]) for r in rows)
    for r in rows:
        flag = "exact" if r["exact"] else ("INVALID: " + (r.get("error") or "")[:60] if not r["valid"]
                                           else "wrong: " + ", ".join(r["wrong"][:4]))
        extra = "" if "byte_identical" not in r else f"  byte-identical={r['byte_identical']}"
        print(f"{r['id']:<{width}}  {r['correct']:>2}/{r['total']:<2}  {flag}{extra}")
    print(json.dumps(summary, indent=2))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--cases", help="comma-separated case ids")
    ap.add_argument("--rescore", type=Path, help="score a saved run file instead of calling the API")
    ap.add_argument("--oracle", action="store_true", help="use the expected specs as responses")
    a = ap.parse_args(argv)

    cases = load_cases()
    if a.cases:
        keep = set(a.cases.split(","))
        cases = [c for c in cases if c["id"] in keep]
    by_id = {c["id"]: c for c in cases}

    if a.rescore:
        saved = json.loads(a.rescore.read_text())
        responses = [(r["id"], r["response"]) for r in saved["responses"] if r["id"] in by_id]
    elif a.oracle:
        responses = [(c["id"], {"spec": _oracle(c)}) for c in cases]
    else:
        reason = assistant.available()
        if reason:
            print(reason, file=sys.stderr)
            return 2
        responses = []
        for _ in range(a.repeat):
            for c in cases:
                print(f"... {c['id']}", file=sys.stderr)
                responses.append((c["id"], ask(c)))

    rows = [score_case(by_id[i], r) for i, r in responses]
    summary = report(rows)
    if not (a.rescore or a.oracle):
        runs = HERE / "runs"
        runs.mkdir(exist_ok=True)
        f = runs / f"{assistant.MODEL}_{dt.datetime.now():%Y%m%d-%H%M%S}.json"
        f.write_text(json.dumps({"model": assistant.MODEL, "summary": summary, "rows": rows,
                                 "responses": [{"id": i, "response": r} for i, r in responses]}, indent=1))
        print(f"saved {f}", file=sys.stderr)
    return 0


def _oracle(case: dict) -> dict:
    """A concrete spec that satisfies the case, for --oracle."""
    if case.get("reproduce"):
        return presets()[case["reproduce"]].model_dump(exclude_none=True)
    spec = _fill(case["expected"])
    for i, c in enumerate(spec["classes"]):
        c.setdefault("name", f"class{i}")
        if "sweep" in c:
            c["sweep"].setdefault("s", {"dist": "fixed", "value": 0.01})
    return spec


def _fill(expected):
    """Turn an expected pattern into a concrete spec (first $in option), for --oracle."""
    if isinstance(expected, dict):
        if "$in" in expected:
            return _fill(expected["$in"][0])
        out = {k: _fill(v) for k, v in expected.items() if v is not None}
        if "dist" in out and len(out) == 1:   # a pattern that only fixed the distribution
            out.update({"fixed": {"value": 0.05}, "truncated_exponential": {"mean": 1, "upper": 2}}
                       .get(out["dist"], {"low": 0.01, "high": 0.2}))
        return out
    if isinstance(expected, list):
        return [_fill(x) for x in expected]
    return expected


if __name__ == "__main__":
    sys.exit(main())
