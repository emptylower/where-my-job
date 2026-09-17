# tests/unit/rules/test_runner.py
import multiprocessing as mp
import time
from dataclasses import replace
import pytest
from where_my_job.rules.runner import evaluate_batch, EvalTimeout
from where_my_job.rules.eval import compile_scoring
from tests.conftest import load_fixture
from tests.unit.rules.test_fields import _fact

def test_batch_returns_results_in_order():
    sc = compile_scoring(load_fixture("scoring.minimal.json"))
    facts = [_fact(title="AI产品经理"), _fact(title="会计")]
    out = evaluate_batch(sc, facts, campus_exclude=False, timeout_sec=10)
    assert [r.dir for r in out] == ["AI产品经理", None]
    assert out[0].reasons[0]["rule_id"] == "base"

def test_real_regex_timeout_reaps_worker():
    cfg = {"schema_version": 2, "profile_revision": "synthetic",
           "classify": [{"dir": "X", "when": {"field": "title", "match": "(a+)+$"}}],
           "score": {"X": {"base": 1, "base_reason": "test"}},
           "tiers": {"A": 1}, "fallback_tier": "D"}
    before = {p.pid for p in mp.active_children()}
    started = time.monotonic()
    with pytest.raises(EvalTimeout):
        evaluate_batch(compile_scoring(cfg), [replace(_fact(), title="a" * 18000 + "!")],
                       campus_exclude=False, timeout_sec=0.25)
    assert time.monotonic() - started < 2.0
    assert {p.pid for p in mp.active_children()} <= before

def test_non_positive_timeout_rejected():
    sc = compile_scoring(load_fixture("scoring.minimal.json"))
    with pytest.raises(EvalTimeout):
        evaluate_batch(sc, [_fact()], campus_exclude=False, timeout_sec=0)
