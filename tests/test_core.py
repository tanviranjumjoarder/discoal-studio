import csv
import filecmp
import io
import random
from pathlib import Path

import numpy as np
import pytest

from discoal_studio import analysis, engine, hpc
from discoal_studio.compiler import check, compile_one, compile_spec
from discoal_studio.priors import Prior, evaluate
from discoal_studio.runner import Runner
from discoal_studio.spec import DatasetSpec, presets

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def binary(tmp_path_factory):
    import os
    os.environ["DISCOAL_STUDIO_HOME"] = str(tmp_path_factory.mktemp("home"))
    if not engine.compiler():
        pytest.skip("no C compiler")
    return engine.build(log=lambda m: None)


def lab():
    return presets()["lab_ceu_sweep_2026"]


def tiny(spec, n):
    s = spec.model_copy(deep=True)
    for c in s.classes:
        c.count = n
    return s


# -- priors -----------------------------------------------------------------------
def test_expression_uses_drawn_values():
    assert evaluate("1/(2*N)", {"N": 10000}) == 1 / 20000
    with pytest.raises(ValueError):
        evaluate("__import__('os')", {})


def test_prior_ranges():
    rng = random.Random(1)
    lu = Prior(dist="loguniform", low=0.005, high=0.1)
    te = Prior(dist="truncated_exponential", mean=1e-8, upper=3e-8)
    assert all(0.005 <= lu.sample(rng, {}) <= 0.1 for _ in range(500))
    assert all(0 < te.sample(rng, {}) <= 3e-8 for _ in range(500))
    with pytest.raises(ValueError):
        Prior(dist="uniform", low=1)


# -- compiler ---------------------------------------------------------------------
@pytest.mark.parametrize("cls,table", [(0, "params_neutral_head.csv"), (1, "params_sweep_head.csv")])
def test_reproduces_lab_parameter_tables(cls, table):
    spec = lab()
    rows = [compile_one(spec, spec.classes[cls], i).row for i in (1, 2)]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\r\n")
    w.writeheader()
    w.writerows(rows)
    assert buf.getvalue().encode() == (DATA / table).read_bytes()


def test_all_presets_are_valid():
    for name, spec in presets().items():
        assert check(spec, sample=30) == [], name


def test_physical_to_scaled_units():
    spec = DatasetSpec.model_validate({
        "sites": 1000, "N": {"dist": "fixed", "value": 1000}, "mu": {"dist": "fixed", "value": 1e-6},
        "r": {"dist": "fixed", "value": 1e-6},
        "demography": [{"generations_ago": {"dist": "fixed", "value": 400}, "size": {"dist": "fixed", "value": 100}}],
        "classes": [{"name": "s", "count": 1, "sweep": {"s": {"dist": "fixed", "value": 0.01},
                                                      "tau": {"dist": "fixed", "value": 40}}}]})
    a = next(compile_spec(spec)).argv
    assert a[a.index("-t") + 1] == "4" and a[a.index("-r") + 1] == "4"      # 4*N*mu*L
    assert a[a.index("-en") + 1:a.index("-en") + 4] == ["0.1", "0", "0.1"]  # 400/(4N), size/N
    assert a[a.index("-ws") + 1] == "0.01" and a[a.index("-a") + 1] == "20"  # tau/(4N), 2Ns
    assert "-f" not in a                                                      # f0 = 0: hard sweep


def test_bad_input_gives_plain_warning():
    spec = tiny(presets()["quick_demo"], 3)
    spec.classes[1].sweep.f0 = Prior(dist="fixed", value=1.5)
    assert any("f0" in w for w in check(spec))


# -- running ----------------------------------------------------------------------
def _first_difference(a: Path, b: Path) -> str:
    x, y = a.read_bytes(), b.read_bytes()
    if b"\r\n" in x:
        return "made file has CRLF line endings"
    lx, ly = x.split(b"\n"), y.split(b"\n")
    for k, (p, q) in enumerate(zip(lx, ly)):
        if p != q:
            return f"line {k + 1} differs: {p[:80]!r} vs reference {q[:80]!r}"
    return f"same lines, lengths {len(lx)} vs {len(ly)}"


@pytest.mark.parametrize("rel", ["Neutral/neutral_1.ms", "Sweep/sweep_1.ms"])
def test_byte_identical_to_hpc_files(binary, tmp_path, rel):
    Runner(tiny(lab(), 1), tmp_path, workers=2, binary=binary).run()
    made, ref = tmp_path / rel, DATA / Path(rel).name
    assert filecmp.cmp(made, ref, shallow=False), _first_difference(made, ref)


def test_resume_and_shards(binary, tmp_path):
    spec = tiny(presets()["quick_demo"], 4)
    for k in range(2):
        Runner(spec, tmp_path, workers=2, binary=binary, shard=(k, 2)).run()
    assert len(list(tmp_path.rglob("*.ms"))) == 8
    (tmp_path / "Hard/hard_3.ms").unlink()
    p = Runner(spec, tmp_path, workers=2, binary=binary).run()
    assert (p.state, p.skipped, p.done) == ("done", 7, 8)
    assert (tmp_path / "manifest.json").exists() and (tmp_path / "params_hard.csv").exists()


def test_qc_and_ml_export(binary, tmp_path):
    spec = tiny(presets()["quick_demo"], 12)
    Runner(spec, tmp_path, workers=4, binary=binary).run()
    s = analysis.qc(tmp_path)
    assert np.median(s["hard"]["pi"]["values"]) < np.median(s["neutral"]["pi"]["values"])
    z = np.load(analysis.export_ml(tmp_path, snps=32))
    assert z["X"].shape == (24, 50, 32) and set(z["y"]) == {0, 1}
    assert z["X"].max() == 1


def test_hpc_export(tmp_path):
    files = hpc.export(lab(), tmp_path, tasks=20, partition="shortq7")
    script = files[1].read_text()
    assert "#SBATCH --array=0-19" in script and "--shard \"$SLURM_ARRAY_TASK_ID/20\"" in script
    assert len(files[2].read_text().splitlines()) == 6000


# -- local API --------------------------------------------------------------------
def test_api_requires_token():
    from fastapi.testclient import TestClient
    from discoal_studio.server import TOKEN, app
    c = TestClient(app)
    assert c.get("/api/info").status_code == 403
    r = c.post("/api/check", json={"spec": lab().model_dump()}, headers={"X-Token": TOKEN})
    assert r.status_code == 200 and r.json()["total_files"] == 6000
    bad = c.post("/api/check", json={"spec": {"classes": []}}, headers={"X-Token": TOKEN})
    assert bad.status_code == 422


def test_double_click_opens_app_window(monkeypatch):
    # Launching with no arguments (double-clicking the app) must ask for the native window.
    import discoal_studio.desktop as desktop
    from typer.testing import CliRunner
    from discoal_studio.cli import app
    seen = {}
    monkeypatch.setattr(desktop, "launch", lambda port=0, use_browser=False: seen.update(use_browser=use_browser))
    assert CliRunner().invoke(app, []).exit_code == 0
    assert seen == {"use_browser": False}
