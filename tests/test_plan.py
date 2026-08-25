import json

import pytest

from poh_howtodemo import model, plan

RAW = json.dumps({"steps": [
    {"n": 1, "text": "GET /healthz",
     "action": {"kind": "http", "method": "GET", "path": "/healthz"},
     "expect": {"status": 200, "json_subset": {"status": "ok"}},
     "evidence": ["response"], "source": "Issue #12, шаг 1"},
    {"n": 2, "text": "проверяю письмо", "action": {"kind": "unmapped"},
     "expect": {}, "evidence": [], "source": "Issue #12, шаг 2"},
]})


def test_unmapped_step_survives_and_is_not_an_error():
    """Неисполнимый шаг — штатный исход. План с ним валиден."""
    steps = plan.from_json(RAW)
    assert steps[1].action.kind == model.UNMAPPED
    assert steps[1].expect.is_empty()


def test_http_step_carries_expectation():
    steps = plan.from_json(RAW)
    assert steps[0].action.path == "/healthz"
    assert steps[0].expect.json_subset == {"status": "ok"}


def test_unknown_kind_is_rejected():
    bad = json.dumps({"steps": [{"n": 1, "text": "x", "action": {"kind": "telepathy"}}]})
    with pytest.raises(plan.PlanError, match="telepathy"):
        plan.from_json(bad)


def test_plan_must_cover_every_step():
    """Модель обязана вернуть столько же шагов, сколько в сценарии."""
    def translate(_steps):
        return json.dumps({"steps": [{"n": 1, "text": "a", "action": {"kind": "unmapped"}}]})

    with pytest.raises(plan.PlanError, match="2"):
        plan.build(["a", "b"], translate)


def test_roundtrip_is_stable():
    steps = plan.from_json(RAW)
    assert plan.from_json(plan.to_json(steps)) == steps


def test_free_form_scenario_may_expand_into_several_steps():
    """Блок curl с двумя запросами — законно два шага из одного элемента."""
    def translate(_scenario):
        return json.dumps({"steps": [
            {"n": 1, "text": "первый curl", "action": {"kind": "http", "path": "/quote"}},
            {"n": 2, "text": "второй curl", "action": {"kind": "http", "path": "/quote"}},
        ]})

    steps = plan.build(["блок целиком"], translate, strict=False)
    assert len(steps) == 2


def test_free_form_still_requires_at_least_one_step():
    with pytest.raises(plan.PlanError, match="ни одного шага"):
        plan.build(["блок целиком"], lambda s: json.dumps({"steps": []}), strict=False)


def test_strict_is_the_default():
    def translate(_scenario):
        return json.dumps({"steps": [{"n": 1, "text": "a", "action": {"kind": "unmapped"}}]})

    with pytest.raises(plan.PlanError):
        plan.build(["a", "b"], translate)
