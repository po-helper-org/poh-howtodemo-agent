from poh_howtodemo import model, verdict

EV = [model.Evidence(name="response", path="evidence/step-1/response.json")]


def _step(**kw):
    base = dict(n=1, text="GET /healthz",
                action=model.Action(kind=model.HTTP, path="/healthz"),
                expect=model.Expect(status=200, json_subset={"status": "ok"}))
    base.update(kw)
    return model.Step(**base)


def test_passed_needs_action_expectation_and_evidence():
    obs = model.Observation(ok=True, status=200, json_body={"status": "ok", "uptime_sec": 5})
    assert verdict.judge(_step(), obs, EV).outcome == model.PASSED


def test_missing_evidence_is_not_passed():
    """Совпавшее ожидание без улик — не зачёт: доказать нечем."""
    obs = model.Observation(ok=True, status=200, json_body={"status": "ok"})
    res = verdict.judge(_step(), obs, [])
    assert res.outcome == model.FAILED and "улик" in res.detail


def test_wrong_field_names_expected_and_actual():
    obs = model.Observation(ok=True, status=200, json_body={"ok": True})
    res = verdict.judge(_step(), obs, EV)
    assert res.outcome == model.FAILED
    assert "status" in res.detail and "ok" in res.detail


def test_unmapped_is_skipped_not_failed():
    step = _step(action=model.Action(kind=model.UNMAPPED), expect=model.Expect())
    assert verdict.judge(step, None, []).outcome == model.SKIPPED


def test_no_environment_is_blocked():
    assert verdict.judge(_step(), None, []).outcome == model.BLOCKED


def test_empty_expectation_never_passes():
    """Шаг без ожидания нечем проверить — молча зачесть его нельзя."""
    step = _step(expect=model.Expect())
    obs = model.Observation(ok=True, status=200)
    assert verdict.judge(step, obs, EV).outcome == model.BLOCKED


def test_overall_partial_when_something_skipped():
    ok = model.StepResult(n=1, text="a", outcome=model.PASSED)
    skipped = model.StepResult(n=2, text="b", outcome=model.SKIPPED)
    assert verdict.overall([ok, skipped]) == model.V_PARTIAL


def test_overall_failed_beats_partial():
    bad = model.StepResult(n=1, text="a", outcome=model.FAILED)
    skipped = model.StepResult(n=2, text="b", outcome=model.SKIPPED)
    assert verdict.overall([bad, skipped]) == model.V_FAILED
