"""Every discoal option the spec exposes: argv, validation, real runs."""
import subprocess

import numpy as np
import pytest
from pydantic import ValidationError

from discoal_studio import analysis, engine
from discoal_studio.compiler import check, compile_one
from discoal_studio.runner import Runner
from discoal_studio.spec import DatasetSpec, presets

F = lambda v: {"dist": "fixed", "value": v}  # noqa: E731
BASE = dict(sample_size=20, sites=20000, N=F(10000), mu=F(1e-8), r=F(1e-8), seed="opt")
SW = {"s": F(0.02)}


def argv(**kw):
    spec = DatasetSpec.model_validate({**BASE, **kw})
    return compile_one(spec, spec.classes[-1], 1).argv


def after(a, flag, n):
    i = a.index(flag)
    return a[i + 1:i + 1 + n]


def test_population_structure_flags():
    a = argv(populations=[{"name": "a", "sample_size": 12}, {"name": "b", "sample_size": 8}],
             demography=[{"generations_ago": F(400), "size": F(2000), "population": 1}],
             splits=[{"generations_ago": F(4000), "population": 1, "into": 0}],
             migration=[{"rate": F(1e-4)}, {"rate": F(5e-5), "from_pop": 0, "to_pop": 1}],
             ancient_samples=[{"size": 2, "population": 1, "generations_ago": F(1000)}],
             classes=[{"name": "n", "count": 1}])
    assert after(a, "-p", 3) == ["2", "12", "8"]
    assert after(a, "-en", 3) == ["0.01", "1", "0.2"]
    assert after(a, "-ed", 3) == ["0.1", "1", "0"]
    assert after(a, "-M", 1) == ["4"] and after(a, "-m", 3) == ["0", "1", "2"]
    assert after(a, "-A", 3) == ["2", "1", "0.025"]
    assert a.index("-p") < a.index("-M")          # discoal needs -p before -m/-M


def test_admixture_gene_conversion_until_trees():
    a = argv(populations=[{"sample_size": 10}, {"sample_size": 5}, {"sample_size": 5}],
             admixture=[{"generations_ago": F(400), "daughter": 0, "founder1": 1, "founder2": 2, "proportion": F(0.3)}],
             gene_conversion={"rate_per_bp": 1e-8, "mean_tract_length": 300},
             mutations_until=F(2000), tree_output=True, classes=[{"name": "n", "count": 1}])
    assert after(a, "-ea", 5) == ["0.01", "0", "1", "2", "0.3"]
    assert after(a, "-g", 2) == ["8", "300"] and "-gr" not in a
    assert after(a, "-U", 1) == ["0.05"] and "-T" in a


def test_sweep_options():
    a = argv(classes=[{"name": "s", "count": 1, "sweep": {**SW, "effective_size": F("N"), "time_step": 200,
                                                          "partial_final_freq": F(0.6), "hide_selected_snp": True,
                                                          "recombination_during_sweep": {"left_site": 100, "right_site": 900}}}])
    assert after(a, "-N", 1) == ["10000"] and after(a, "-i", 1) == ["200"] and "-h" in a
    assert after(a, "-c", 1) == ["0.6"] and after(a, "-C", 2) == ["100", "900"]
    left = argv(classes=[{"name": "s", "count": 1, "sweep": {**SW, "mode": "deterministic", "location": "left_of_window",
                                                             "left_distance_bp": F(5000)}}])
    assert after(left, "-ld", 2) == ["0", "2"] and "-x" not in left and "-wd" not in left
    for side, flag in ((False, "-R"), (True, "-L")):
        r = argv(classes=[{"name": "s", "count": 1, "sweep": {**SW, "recurrent_rate": F(0.05), "recurrent_side": side}}])
        assert after(r, flag, 3) == ["0.05", "-a", "400"] and "-ws" not in r and "-x" not in r
    p = argv(classes=[{"name": "s", "count": 1, "sweep": SW, "extra_args": "-Pa 100 1000 -Pe1 0 1 0.1 2"}])
    assert p[-8:] == ["-Pa", "100", "1000", "-Pe1", "0", "1", "0.1", "2"]


@pytest.mark.parametrize("bad, msg", [
    (dict(populations=[{"sample_size": 10}, {"sample_size": 5}]), "add up to 15"),
    (dict(populations=[{"sample_size": 20}]), "two or more"),
    (dict(demography=[{"generations_ago": F(1), "size": F(1), "population": 1}]), "population 1 does not exist"),
    (dict(migration=[{"rate": F(1e-4)}]), "two or more populations"),
    (dict(ancient_samples=[{"size": 20, "generations_ago": F(1)}]), "fewer than sample_size"),
    (dict(gene_conversion={"mean_tract_length": 300}), "either"),
    (dict(classes=[{"name": "n", "count": 1, "extra_args": "-d 1 2"}]), "not one of"),
    (dict(classes=[{"name": "n", "count": 1, "extra_args": "-Pa 1"}]), "needs 2 numbers"),
    (dict(classes=[{"name": "s", "count": 1, "sweep": {**SW, "location": "left_of_window"}}]), "left_distance_bp"),
])
def test_validation(bad, msg):
    with pytest.raises(ValidationError, match=msg):
        DatasetSpec.model_validate({**BASE, "classes": [{"name": "n", "count": 1}], **bad})


def test_unused_options_change_nothing():
    """Empty new fields must keep every preset's commands and seeds."""
    for name, spec in presets().items():
        d = spec.model_dump()
        d.update(populations=[], splits=[], admixture=[], migration=[], ancient_samples=[], tree_output=False)
        same = DatasetSpec.model_validate(d)
        for c, c2 in zip(spec.classes, same.classes):
            assert compile_one(spec, c, 7).command == compile_one(same, c2, 7).command, name


def test_warnings_for_slow_or_special_options():
    spec = DatasetSpec.model_validate({**BASE, "tree_output": True, "classes": [
        {"name": "r", "count": 1, "sweep": {**SW, "recurrent_rate": F(0.05)}}]})
    w = " ".join(check(spec))
    assert "crashes" not in w and "default sweep population size" in w and "trees" in w


@pytest.fixture(scope="module")
def binary():
    b = engine.find()
    if b is None:
        pytest.skip("discoal not built")
    return b


@pytest.mark.parametrize("extra", [
    dict(populations=[{"sample_size": 10}, {"sample_size": 10}], migration=[{"rate": F(1e-4)}],
         splits=[{"generations_ago": F(4000), "population": 1, "into": 0}]),
    dict(populations=[{"sample_size": 10}, {"sample_size": 5}, {"sample_size": 5}],
         admixture=[{"generations_ago": F(400), "daughter": 0, "founder1": 1, "founder2": 2, "proportion": F(0.3)}],
         splits=[{"generations_ago": F(8000), "population": 2, "into": 1}]),
    dict(ancient_samples=[{"size": 4, "generations_ago": F(1000)}], mutations_until=F(2000),
         gene_conversion={"rate_per_bp": 1e-8, "mean_tract_length": 300}),
    dict(classes=[{"name": "s", "count": 1, "sweep": {**SW, "location": "left_of_window", "left_distance_bp": F(5000)}}]),
    dict(classes=[{"name": "s", "count": 1, "sweep": {**SW, "effective_size": F("N"), "partial_final_freq": F(0.6),
                                                      "hide_selected_snp": True, "time_step": 200,
                                                      "recombination_during_sweep": {"left_site": 2000, "right_site": 18000}}}]),
    dict(classes=[{"name": "s", "count": 1, "sweep": SW, "extra_args": "-Pa 100 1000 -Px 0.4 0.6"}], replicates_per_file=3),
], ids=["split-migration", "admixture", "ancient-U-g", "left-sweep", "partial-N-i-h-C", "P-priors"])
def test_discoal_accepts(binary, extra):
    spec = DatasetSpec.model_validate({**BASE, "classes": [{"name": "n", "count": 1}], **extra})
    j = compile_one(spec, spec.classes[-1], 1)
    p = subprocess.run(j.argv, executable=str(binary), capture_output=True, timeout=120)
    assert p.returncode == 0, p.stderr.decode()[-300:]
    assert p.stdout.decode().count("segsites:") == spec.replicates_per_file


def test_shared_ml_label(binary, tmp_path):
    spec = DatasetSpec.model_validate({**BASE, "sample_size": 10, "sites": 5000, "classes": [
        {"name": "neutral", "count": 2},
        {"name": "hard", "count": 2, "label": "sweep", "sweep": SW},
        {"name": "soft", "count": 2, "label": "sweep", "sweep": {**SW, "f0": F(0.05)}}]})
    Runner(spec, tmp_path, workers=2, binary=binary).run()
    z = np.load(analysis.export_ml(tmp_path, snps=16, workers=2))
    assert list(z["classes"]) == ["neutral", "sweep"]
    assert sorted(z["y"].tolist()) == [0, 0, 1, 1, 1, 1]
    assert set(z["source_class"]) == {"neutral", "hard", "soft"} and "Joarder" in str(z["made_with"])
