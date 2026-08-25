from poh_howtodemo.github import RestGitHub


def test_token_provider_receives_the_repository():
    """Harness объявляет auth_token(repo: str) — зовём его так же."""
    seen = []
    gh = RestGitHub(lambda repo: seen.append(repo) or "ghs_x")
    headers = gh._headers("po-helper-org/poh-demo-checkout")
    assert seen == ["po-helper-org/poh-demo-checkout"]
    assert headers["Authorization"] == "Bearer ghs_x"


# --- поиск PR задачи ---

from poh_howtodemo import github


def _event(number, state="open", body="", pull=True):
    src = {"number": number, "state": state, "body": body}
    if pull:
        src["pull_request"] = {}
    return {"event": "cross-referenced", "source": {"issue": src}}


def test_closing_keyword_wins_over_a_mere_mention():
    events = [_event(10, body="упоминаю #12 в обсуждении"),
              _event(11, body="Closes #12")]
    assert github.pick_pull(events, 12) == 11


def test_newest_open_pull_when_nobody_closes():
    assert github.pick_pull([_event(10), _event(11)], 12) == 11


def test_closed_pulls_are_ignored():
    assert github.pick_pull([_event(10, state="closed", body="Closes #12")], 12) == 0


def test_cross_referenced_issues_are_not_pulls():
    assert github.pick_pull([_event(10, pull=False, body="Closes #12")], 12) == 0


def test_closing_another_issue_is_not_our_pull():
    assert github.pick_pull([_event(10, body="Closes #99")], 12) == 10


def test_no_events_means_no_pull():
    assert github.pick_pull([], 12) == 0
