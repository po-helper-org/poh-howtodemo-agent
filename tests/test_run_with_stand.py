import json

from poh_howtodemo import model, run

BODY = """## HowToDemo

1. Отправить `GET /healthz`, увидеть 200 и `status=ok`.
"""

PLAN = json.dumps({"steps": [
    {"n": 1, "text": "GET /healthz", "action": {"kind": "http", "path": "/healthz"},
     "expect": {"status": 200, "json_subset": {"status": "ok"}},
     "evidence": ["response", "service_log"], "source": "Issue #12, шаг 1"},
]})


class _GH:
    def issue_body(self, repo, number): return BODY
    def comments(self, repo, number): return []
    def comment(self, repo, number, body): pass
    def add_label(self, repo, number, label): pass
    def remove_labels(self, repo, number, labels): pass
    def pull_head(self, repo, number): return ("feature/12", "3a1f0c2")
    def get_file(self, repo, path, ref): return None


class _Stand:
    def __init__(self, ok=True):
        self.ok = ok
        self.upped = []
        self.downed = []

    def up(self, repo, issue, sha, service):
        self.upped.append((repo, issue, sha))
        if not self.ok:
            return model.Stand(ok=False, detail="нечем поднимать")
        return model.Stand(ok=True, url="http://stand:3000",
                           container="poh-howtodemo-o__r-12",
                           workdir="/workspaces/howtodemo/o__r-12/3a1f0c2")

    def down(self, repo, issue):
        self.downed.append((repo, issue))


def _run(stand, tmp_path, send, docker=lambda a: (0, "лог сервиса")):
    return run.verify(repo="o/r", issue=12, pr_number=45, base_url="",
                      root=str(tmp_path), gh=_GH(), translate=lambda s: PLAN,
                      send=send, exec_=lambda c, cwd: (0, ""),
                      run_git=lambda a, c: (0, ""), token="t",
                      stand=stand, sha="3a1f0c2", service={"start": "node x"},
                      run_docker=docker)


def test_stand_supplies_base_url_and_step_runs(tmp_path):
    stand = _Stand()
    rep = _run(stand, tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert stand.upped == [("o/r", 12, "3a1f0c2")]
    assert rep.results[0].outcome == model.PASSED


def test_service_log_is_attached_to_the_step(tmp_path):
    rep = _run(_Stand(), tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    names = [ev.name for ev in rep.results[0].evidence]
    assert "service_log.txt" in names
    log_ev = next(ev for ev in rep.results[0].evidence if ev.name == "service_log.txt")
    assert (tmp_path / log_ev.path).read_text().strip() == "лог сервиса"


def test_stand_is_always_torn_down(tmp_path):
    stand = _Stand()
    _run(stand, tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert stand.downed == [("o/r", 12)]


def test_stand_is_torn_down_even_when_a_step_explodes(tmp_path):
    stand = _Stand()

    def boom(*_a, **_kw):
        raise OSError("сеть легла")

    rep = _run(stand, tmp_path, send=boom)
    assert stand.downed == [("o/r", 12)]
    assert rep.results[0].outcome == model.FAILED


def test_stand_that_did_not_come_up_blocks_steps_but_not_the_run(tmp_path):
    stand = _Stand(ok=False)
    rep = _run(stand, tmp_path, send=lambda m, u, j: (200, "{}"))
    assert rep.results[0].outcome == model.BLOCKED
    assert rep.verdict == model.V_PARTIAL
    assert stand.downed == [("o/r", 12)]


CLI_PLAN = json.dumps({"steps": [
    {"n": 1, "text": "Запустить тесты", "action": {"kind": "cli", "command": "npm test"},
     "expect": {"exit_code": 0}, "evidence": ["command"], "source": "x"},
]})


def _run_cli(stand, tmp_path, exec_):
    return run.verify(repo="o/r", issue=12, pr_number=45, base_url="",
                      root=str(tmp_path), gh=_GH(), translate=lambda s: CLI_PLAN,
                      send=None, exec_=exec_, run_git=lambda a, c: (0, ""),
                      token="t", stand=stand, sha="3a1f0c2",
                      service={"start": "node x"}, run_docker=lambda a: (0, ""))


def test_command_does_not_run_without_a_working_copy(tmp_path):
    """Без стенда нет и рабочей копии — команда не запускается, а не падает."""
    def must_not_run(command, cwd):
        raise AssertionError("команда не должна запускаться без рабочей копии")

    rep = _run_cli(_Stand(ok=False), tmp_path, must_not_run)
    assert rep.results[0].outcome == model.BLOCKED
    assert "не запускался" in rep.results[0].detail


def test_command_runs_in_the_working_copy(tmp_path):
    seen = {}

    def exec_(command, cwd):
        seen.update(command=command, cwd=cwd)
        return 0, "ok"

    rep = _run_cli(_Stand(), tmp_path, exec_)
    assert seen["cwd"] == "/workspaces/howtodemo/o__r-12/3a1f0c2"
    assert rep.results[0].outcome == model.PASSED
