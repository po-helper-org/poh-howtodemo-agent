from poh_howtodemo import model
from poh_howtodemo.collectors import cli, http


def test_http_parses_json_body():
    obs = http.run(model.Action(kind=model.HTTP, method="GET", path="/healthz"),
                   "http://svc:8080",
                   send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert obs.ok and obs.status == 200 and obs.json_body == {"status": "ok"}


def test_http_failure_is_data_not_exception():
    def boom(*_args, **_kw):
        raise OSError("connection refused")

    obs = http.run(model.Action(kind=model.HTTP, path="/x"), "http://svc:8080", send=boom)
    assert obs.ok is False and "connection refused" in obs.error


def test_http_keeps_text_when_body_is_not_json():
    obs = http.run(model.Action(kind=model.HTTP, path="/"), "http://svc:8080",
                   send=lambda m, u, j: (404, "не найдено"))
    assert obs.ok is True and obs.status == 404 and obs.json_body == {}
    assert obs.text == "не найдено"


def test_cli_captures_exit_code_and_output():
    obs = cli.run(model.Action(kind=model.CLI, command="node --test"), "/w",
                  exec_=lambda c, cwd: (1, "1 failing"))
    assert obs.ok is True and obs.exit_code == 1 and "1 failing" in obs.text
