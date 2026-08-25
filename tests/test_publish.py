from poh_howtodemo import publish


def test_branch_is_one_per_issue():
    assert publish.branch_name(12) == "howtodemo/issue-12"


def test_evidence_lands_in_step_directory(tmp_path):
    ev = publish.write_evidence(str(tmp_path), 3, "response.json", b'{"a": 1}')
    assert ev.path == "evidence/step-3/response.json"
    assert (tmp_path / ev.path).read_bytes() == b'{"a": 1}'


def test_token_appears_only_in_the_push_call(tmp_path):
    """Токен живёт в одном аргументе одной команды и больше нигде."""
    calls = []

    def run_git(args, cwd):
        calls.append(args)
        return 0, "ok"

    ok = publish.push(str(tmp_path), "o/r", "howtodemo/issue-12", "ghs_secret", run_git)
    assert ok is True
    carrying = [args for args in calls if any("ghs_secret" in a for a in args)]
    assert len(carrying) == 1 and carrying[0][0] == "push"


def test_push_reports_failure_instead_of_raising(tmp_path):
    ok = publish.push(str(tmp_path), "o/r", "b", "t", lambda a, c: (1, "rejected"))
    assert ok is False
