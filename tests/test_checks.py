import json

from poh_howtodemo import checks


class _GH:
    def __init__(self, content):
        self.content = content
        self.asked = []

    def get_file(self, repo, path, ref):
        self.asked.append((repo, path, ref))
        return self.content


def test_reads_service_from_target_repository():
    gh = _GH(json.dumps({"service": {"port": 3000, "start": "node src/server.mjs",
                                     "health_path": "/healthz"}}))
    service = checks.read(gh, "o/r", "abc123")
    assert service["port"] == 3000 and service["start"] == "node src/server.mjs"
    assert gh.asked == [("o/r", ".delivery/checks.json", "abc123")]


def test_absent_file_is_empty_contract_not_an_error():
    assert checks.read(_GH(None), "o/r", "abc123") == {}


def test_broken_json_is_empty_contract():
    assert checks.read(_GH("{не json"), "o/r", "abc123") == {}


def test_checks_array_is_ignored():
    """Проверки Delivery нас не касаются: шаги приходят из сценария."""
    raw = json.dumps({"service": {"start": "x"}, "checks": [{"name": "quote"}]})
    assert checks.service_of(json.loads(raw)) == {"start": "x"}
