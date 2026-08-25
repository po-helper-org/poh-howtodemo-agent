import pytest

from poh_howtodemo import ports


class _Fake:
    def issue_body(self, repo, number): return "тело"
    def comments(self, repo, number): return [(1, "текст")]
    def comment(self, repo, number, body): return None
    def add_label(self, repo, number, label): return None
    def remove_labels(self, repo, number, labels): return None
    def pull_head(self, repo, number): return ("feature/x", "abc123")


def test_ports_must_be_configured_before_use():
    ports.configure(github=None, llm=None, shell=None)
    with pytest.raises(RuntimeError, match="не подставлен"):
        ports.github()


def test_configure_supplies_implementation():
    ports.configure(github=_Fake())
    assert ports.github().issue_body("o/r", 1) == "тело"
    ports.configure(github=None)
