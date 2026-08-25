import json

from poh_howtodemo import model, plan, run

CHAIN = json.dumps({"steps": [
    {"n": 1, "text": "Отправить GET /healthz",
     "action": {"kind": "http", "path": "/healthz"},
     "expect": {"status": 200}, "evidence": ["response"]},
    {"n": 2, "text": "Проверить, что тело содержит status=ok",
     "action": {"kind": "assert"},
     "expect": {"json_subset": {"status": "ok"}}},
    {"n": 3, "text": "Проверить, что есть поле uptime_sec",
     "action": {"kind": "assert"},
     "expect": {"contains": "uptime_sec"}},
]})


class _GH:
    def issue_body(self, repo, number):
        return "## HowToDemo\n\n1. a\n2. b\n3. c\n"

    def comments(self, repo, number): return []
    def comment(self, repo, number, body): pass
    def add_label(self, repo, number, label): pass
    def remove_labels(self, repo, number, labels): pass
    def pull_head(self, repo, number): return ("f", "abc1234")
    def get_file(self, repo, path, ref): return None
    def linked_pull(self, repo, issue): return 0


def _run(tmp_path, send, raw=CHAIN):
    return run.verify(repo="o/r", issue=12, pr_number=0,
                      base_url="http://svc:8080", root=str(tmp_path), gh=_GH(),
                      translate=lambda s: raw, send=send,
                      exec_=lambda c, cwd: (0, ""), run_git=lambda a, c: (0, ""),
                      token="t")


def test_assert_is_a_kind_the_plan_accepts():
    steps = plan.from_json(CHAIN)
    assert steps[1].action.kind == model.ASSERT


def test_assertion_is_judged_against_the_previous_response(tmp_path):
    rep = _run(tmp_path, send=lambda m, u, j: (200, '{"status": "ok", "uptime_sec": 5}'))
    assert [r.outcome for r in rep.results] == [model.PASSED] * 3
    assert rep.verdict == model.V_PASSED


def test_failing_assertion_names_the_mismatch(tmp_path):
    rep = _run(tmp_path, send=lambda m, u, j: (200, '{"status": "degraded"}'))
    assert rep.results[0].outcome == model.PASSED
    assert rep.results[1].outcome == model.FAILED
    assert "degraded" in rep.results[1].detail


def test_assertion_reuses_the_evidence_of_the_step_it_checks(tmp_path):
    rep = _run(tmp_path, send=lambda m, u, j: (200, '{"status": "ok", "uptime_sec": 5}'))
    assert rep.results[1].evidence == rep.results[0].evidence
    assert rep.results[1].on_step == 1


def test_assertion_binds_to_the_code_not_to_the_model(tmp_path):
    """Модель говорит «это утверждение», к какому шагу — решает код."""
    steps = plan.from_json(CHAIN)
    assert all(s.action.on == 0 for s in steps), "модель номер не пишет"


def test_assertion_without_anything_executed_before_is_blocked(tmp_path):
    """Сценарий начинается с утверждения — опереться не на что."""
    class _OneStep(_GH):
        def issue_body(self, repo, number):
            return "## HowToDemo\n\n1. Проверить, что status=ok\n"

    lonely = json.dumps({"steps": [
        {"n": 1, "text": "Проверить, что status=ok", "action": {"kind": "assert"},
         "expect": {"json_subset": {"status": "ok"}}}]})
    rep = run.verify(repo="o/r", issue=12, pr_number=0, base_url="",
                     root=str(tmp_path), gh=_OneStep(), translate=lambda s: lonely,
                     send=None, exec_=lambda c, cwd: (0, ""),
                     run_git=lambda a, c: (0, ""), token="t")
    assert rep.results[0].outcome == model.BLOCKED
    assert "нечего проверять" in rep.results[0].detail


def test_assertion_after_a_blocked_step_is_blocked_too(tmp_path):
    """Шаг не исполнился — утверждению о его ответе не на что опереться."""
    rep = run.verify(repo="o/r", issue=12, pr_number=0, base_url="",
                     root=str(tmp_path), gh=_GH(), translate=lambda s: CHAIN,
                     send=None, exec_=lambda c, cwd: (0, ""),
                     run_git=lambda a, c: (0, ""), token="t")
    assert rep.results[1].outcome == model.BLOCKED
