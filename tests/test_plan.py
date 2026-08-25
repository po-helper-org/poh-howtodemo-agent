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
        plan.build(["a", "b"], translate, issue=12)


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

    steps = plan.build(["блок целиком"], translate, issue=12, strict=False)
    assert len(steps) == 2


def test_free_form_still_requires_at_least_one_step():
    with pytest.raises(plan.PlanError, match="ни одного шага"):
        plan.build(["блок целиком"], lambda s: json.dumps({"steps": []}), issue=12,
                   strict=False)


def test_strict_is_the_default():
    def translate(_scenario):
        return json.dumps({"steps": [{"n": 1, "text": "a", "action": {"kind": "unmapped"}}]})

    with pytest.raises(plan.PlanError):
        plan.build(["a", "b"], translate, issue=12)


def test_source_is_computed_by_code_not_taken_from_the_model():
    """Живой прогон: модель написала «Issue #1» на Issue #100."""
    raw = json.dumps({"steps": [
        {"n": 1, "text": "шаг", "action": {"kind": "unmapped"},
         "source": "Issue #1, шаг 1"},
    ]})
    steps = plan.build(["шаг"], lambda s: raw, issue=100)
    assert steps[0].source == "Issue #100, шаг 1"


def test_source_follows_the_plan_step_number():
    raw = json.dumps({"steps": [
        {"n": 1, "text": "a", "action": {"kind": "unmapped"}},
        {"n": 2, "text": "b", "action": {"kind": "unmapped"}},
    ]})
    steps = plan.build(["блок"], lambda s: raw, issue=7, strict=False)
    assert [s.source for s in steps] == ["Issue #7, шаг 1", "Issue #7, шаг 2"]


def test_system_prompt_travels_with_the_package():
    """Промпт — часть договора с моделью. Копия у потребителя отстанет."""
    text = plan.system_prompt()
    assert "unmapped" in text and "json_subset" in text
    assert "steps" in text
