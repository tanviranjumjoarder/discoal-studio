import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from discoal_studio import assistant
from discoal_studio.spec import presets

pytest.importorskip("anthropic")


def tool_use(name, inp, i=1):
    return NS(type="tool_use", id=f"tu_{i}", name=name, input=inp)


def reply(*blocks):
    return NS(content=list(blocks), stop_reason="tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn",
              usage=NS(input_tokens=10, output_tokens=5))


class FakeClient:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw["messages"], default=lambda o: o.__dict__)))
        return self.replies.pop(0)


LAB = presets()["lab_ceu_sweep_2026"].model_dump(exclude_none=True)


def test_valid_spec_returns_draft_with_outline():
    c = FakeClient(reply(tool_use("propose_spec", {"spec": LAB, "summary": "The lab set."})))
    d = assistant.draft("the lab dataset", client=c)
    assert d.spec.model_dump(exclude_none=True) == LAB
    assert d.rounds == 1 and d.warnings == [] and d.summary == "The lab set."
    assert any("99 diploid" in line for line in d.outline)


def test_errors_and_warnings_are_fed_back():
    bad = {"classes": [{"name": "s", "count": 5, "sweep": {"s": {"dist": "fixed", "value": 0.01},
                                                           "f0": {"dist": "fixed", "value": "1/(2*Q)"}}}]}
    weak = {"classes": [{"name": "s", "count": 5, "sweep": {"s": {"dist": "fixed", "value": 1e-9}}}]}
    c = FakeClient(reply(tool_use("propose_spec", {"spec": bad, "summary": "x"}, 1)),
                   reply(tool_use("propose_spec", {"spec": weak, "summary": "x"}, 2)),
                   reply(tool_use("propose_spec", {"spec": weak, "summary": "weak on purpose",
                                                   "accept_warnings": True}, 3)))
    d = assistant.draft("weak sweeps", client=c)
    assert d.rounds == 3 and any("nearly neutral" in w for w in d.warnings)
    fed = [m for m in c.calls[1] if m["role"] == "user" and isinstance(m["content"], list)]
    assert "'Q' is not known" in fed[-1]["content"][0]["content"]
    assert "nearly neutral" in c.calls[2][-1]["content"][0]["content"]


def test_get_preset_and_current_spec_are_passed():
    c = FakeClient(reply(tool_use("get_preset", {"name": "lab_ceu_sweep_2026"}, 1)),
                   reply(tool_use("propose_spec", {"spec": LAB, "summary": "ok"}, 2)))
    assistant.draft("same as the lab one", current={"name": "x"}, client=c)
    assert "Current spec" in c.calls[0][0]["content"]
    assert '"20261001"' in c.calls[1][-1]["content"][0]["content"]


def test_no_tool_call_is_an_error_after_retries():
    c = FakeClient(*[reply(NS(type="text", text="I need more detail.")) for _ in range(2)])
    with pytest.raises(assistant.AssistantError, match="more detail"):
        assistant.draft("hmm", client=c, max_rounds=2)


def test_schema_and_tools_are_well_formed():
    t = {x["name"]: x for x in assistant.tools()}
    s = t["propose_spec"]["input_schema"]
    assert s["properties"]["spec"]["$ref"] == "#/$defs/DatasetSpec" and "Prior" in s["$defs"]
    assert "lab_ceu_sweep_2026" in assistant.system_prompt()


def test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from discoal_studio import server
    monkeypatch.setattr(assistant, "draft", lambda p, current=None: assistant.Draft(
        presets()["quick_demo"], "demo", [], [], 1))
    r = TestClient(server.app).post("/api/assistant", json={"prompt": "demo", "spec": LAB},
                                    headers={"X-Token": server.TOKEN})
    assert r.status_code == 200 and r.json()["spec"]["name"] == "quick_demo"


def _score():
    p = Path(__file__).parent / "assistant_eval" / "score.py"
    spec = importlib.util.spec_from_file_location("score", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_eval_scorer_oracle_is_perfect(capsys):
    assert _score().main(["--oracle"]) == 0
    assert '"field_accuracy_micro": 1.0' in capsys.readouterr().out


def test_eval_scorer_counts_wrong_fields():
    m = _score()
    case = next(c for c in m.load_cases() if c["id"] == "lab_in_words")
    wrong = json.loads(json.dumps(LAB))
    wrong["sample_size"] = 99                     # individuals instead of haplotypes
    wrong["classes"][1]["sweep"]["f0"]["low"] = "1/(2 * N)"   # spacing must not matter
    r = m.score_case(case, {"spec": wrong})
    assert r["wrong"] == ["sample_size"] and r["byte_identical"] is False
    assert m.score_case(case, {"error": "x"})["valid"] is False


def test_mcp_server_tools():
    pytest.importorskip("mcp")
    from discoal_studio.mcp_server import server
    names = [t.name for t in asyncio.run(server.list_tools())]
    assert names == ["list_presets", "draft_spec", "check_spec", "estimate", "run_dataset", "status", "qc"]
    out = asyncio.run(server.call_tool("check_spec", {"spec": LAB}))
    data = json.loads(out.content[0].text)
    assert data["valid"] and data["total_files"] == 6000 and data["examples"][0].startswith("discoal 198 1 1100000")
