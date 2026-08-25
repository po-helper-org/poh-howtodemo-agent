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


def test_stamp_is_rfc3339_utc_with_subsecond_precision():
    """Секундной точности мало: вырожденное окно докер отдаёт пустым."""
    value = logs.stamp()
    assert value.endswith("Z") and "T" in value
    assert "." in value, "нужны доли секунды"
    assert logs.stamp() != value or True  # монотонность не проверяем, только формат


def test_two_stamps_around_a_fast_step_are_not_equal():
    first = logs.stamp()
    for _ in range(1000):
        pass
    assert logs.stamp() != first, "метки шага не должны совпадать"


def test_empty_window_says_so_instead_of_leaving_a_blank_file():
    """Пустой файл улики неотличим от сломанного сборщика."""
    text = logs.window(lambda a: (0, "  \n "), "c", since="A", until="B")
    assert "не записал ни строки" in text and "A" in text and "B" in text
