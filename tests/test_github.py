from poh_howtodemo.github import RestGitHub


def test_token_provider_receives_the_repository():
    """Harness объявляет auth_token(repo: str) — зовём его так же."""
    seen = []
    gh = RestGitHub(lambda repo: seen.append(repo) or "ghs_x")
    headers = gh._headers("po-helper-org/poh-demo-checkout")
    assert seen == ["po-helper-org/poh-demo-checkout"]
    assert headers["Authorization"] == "Bearer ghs_x"
