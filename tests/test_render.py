from poh_howtodemo import model, render


def _report():
    a = model.Anchor(issue=12, source=model.BODY, sha256="a1b2c3d4",
                     taken_at="2026-08-25T10:00:00Z")
    return model.RunReport(
        anchor=a, pr_number=45, ref="feature/12-cart@3a1f0c2",
        evidence_branch="howtodemo/issue-12",
        verdict=model.V_FAILED,
        results=[
            model.StepResult(
                n=1, text="GET /healthz", outcome=model.PASSED,
                evidence=[model.Evidence(name="response",
                                         path="evidence/step-1/response.json")]),
            model.StepResult(n=2, text="итог 2300", outcome=model.FAILED,
                             detail="поле `total`: ожидалось 2300, пришло 2000",
                             source="Issue #12, шаг 2"),
            model.StepResult(n=3, text="проверяю письмо", outcome=model.SKIPPED,
                             detail="шаг не превращается в действие — нужен человек"),
        ])


def test_report_splits_ready_from_mismatched():
    body = render.report_md(_report())
    ready, rest = body.split("### Что не соответствует")
    assert "GET /healthz" in ready and "GET /healthz" not in rest
    assert "итог 2300" in rest


def test_mismatch_carries_detail_and_source():
    body = render.report_md(_report())
    assert "ожидалось 2300, пришло 2000" in body
    assert "Issue #12, шаг 2" in body


def test_skipped_is_separated_from_failure():
    body = render.report_md(_report())
    assert "⚠️" in body and "нужен человек" in body


def test_report_names_anchor_and_evidence():
    body = render.report_md(_report())
    assert "a1b2c3d4"[:8] in body and "howtodemo/issue-12" in body
    assert render.MARKER in body


def test_changed_scenario_is_said_out_loud():
    rep = _report()
    rep.scenario_changed = True
    assert "менялся после фиксации" in render.report_md(rep)


def test_free_form_scenario_is_flagged_for_the_reader():
    rep = _report()
    rep.anchor.numbered = False
    body = render.report_md(rep)
    assert "свободной формой" in body and "Сверьте" in body


def test_numbered_scenario_says_nothing_extra():
    assert "свободной формой" not in render.report_md(_report())


def test_report_explains_why_there_was_no_environment():
    rep = _report()
    rep.stand_detail = "в .delivery/checks.json нет service.start"
    body = render.report_md(rep)
    assert "service.start" in body and "не запускались" in body


def test_report_says_nothing_about_environment_when_it_came_up():
    assert "Окружение поднять не удалось" not in render.report_md(_report())
