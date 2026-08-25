from poh_howtodemo.collectors import logs


def test_window_asks_docker_for_the_step_interval():
    seen = []

    def run_cmd(args):
        seen.append(args)
        return 0, "checkout слушает :3000"

    text = logs.window(run_cmd, "poh-howtodemo-o__r-12",
                       since="2026-08-25T10:00:00Z", until="2026-08-25T10:00:05Z")
    assert "слушает" in text
    args = seen[0]
    assert args[:2] == ["docker", "logs"]
    assert "--since" in args and "2026-08-25T10:00:00Z" in args
    assert "--until" in args and "2026-08-25T10:00:05Z" in args
    assert "--timestamps" in args


def test_failure_becomes_readable_text_not_exception():
    text = logs.window(lambda a: (1, "No such container"), "gone",
                       since="a", until="b")
    assert "No such container" in text


def test_stamp_is_rfc3339_utc():
    value = logs.stamp()
    assert value.endswith("Z") and "T" in value and len(value) == 20
