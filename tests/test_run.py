import json

from poh_howtodemo import model, run

BODY = """## HowToDemo

1. Отправить `GET /healthz`, увидеть 200 и `status=ok`.
2. Проверить входящее письмо.
"""

PLAN = json.dumps({"steps": [
    {"n": 1, "text": "GET /healthz", "action": {"kind": "http", "path": "/healthz"},
     "expect": {"status": 200, "json_subset": {"status": "ok"}},
     "evidence": ["response"], "source": "Issue #12, шаг 1"},
    {"n": 2, "text": "проверяю письмо", "action": {"kind": "unmapped"}, "expect": {},
     "source": "Issue #12, шаг 2"},
]})


class _GH:
    def __init__(self):
        self.comments_posted = []
        self.labels = []

    def issue_body(self, repo, number): return BODY
    def comments(self, repo, number): return []
    def comment(self, repo, number, body): self.comments_posted.append(body)
    def add_label(self, repo, number, label): self.labels.append(label)
    def remove_labels(self, repo, number, labels): pass
    def pull_head(self, repo, number): return ("feature/12", "3a1f0c2")


def _run(gh, tmp_path, send):
    return run.verify(repo="o/r", issue=12, pr_number=45, base_url="http://svc:8080",
                      root=str(tmp_path), gh=gh, translate=lambda s: PLAN, send=send,
                      exec_=lambda c, cwd: (0, ""), run_git=lambda a, c: (0, ""),
                      token="t")


def test_green_http_step_and_unmapped_give_partial(tmp_path):
    gh = _GH()
    rep = _run(gh, tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert rep.verdict == model.V_PARTIAL
    assert rep.results[0].outcome == model.PASSED
    assert rep.results[1].outcome == model.SKIPPED


def test_evidence_is_written_for_executed_step(tmp_path):
    rep = _run(_GH(), tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert rep.results[0].evidence
    assert (tmp_path / rep.results[0].evidence[0].path).exists()


def test_mismatch_gives_failed_verdict(tmp_path):
    rep = _run(_GH(), tmp_path, send=lambda m, u, j: (200, '{"status": "degraded"}'))
    assert rep.verdict == model.V_FAILED
    assert "degraded" in rep.results[0].detail


def test_no_environment_blocks_http_steps(tmp_path):
    rep = run.verify(repo="o/r", issue=12, pr_number=0, base_url="", root=str(tmp_path),
                     gh=_GH(), translate=lambda s: PLAN, send=None,
                     exec_=lambda c, cwd: (0, ""), run_git=lambda a, c: (0, ""), token="t")
    assert rep.results[0].outcome == model.BLOCKED
    assert rep.verdict == model.V_PARTIAL


def test_missing_scenario_returns_no_scenario(tmp_path):
    class _Empty(_GH):
        def issue_body(self, repo, number): return "просто текст"

    rep = _run(_Empty(), tmp_path, send=lambda m, u, j: (200, "{}"))
    assert rep.verdict == model.V_NO_SCENARIO
    assert rep.results == []
