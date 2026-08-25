from poh_howtodemo import env

SERVICE = {"port": 3000, "start": "node src/server.mjs", "health_path": "/healthz",
           "image": "node:22-slim"}


class _Docker:
    def __init__(self, fail_on=""):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, args):
        self.calls.append(args)
        if self.fail_on and self.fail_on in " ".join(args):
            return 1, "не вышло"
        return 0, "ok"

    def flat(self):
        return [" ".join(a) for a in self.calls]


def _stand(docker, statuses):
    it = iter(statuses)

    def probe(url):
        value = next(it)
        if isinstance(value, Exception):
            raise value
        return value

    return env.EphemeralStand(run_cmd=docker, probe=probe,
                              token_provider=lambda repo: "ghs_x", network="net")


def test_container_name_never_collides_with_delivery_prod():
    name = env.container_name("po-helper-org/poh-demo-checkout", 12)
    assert name != "poh-delivery-prod"
    assert "poh-demo-checkout" in name and name.endswith("-12")


def test_up_starts_container_and_reports_url():
    docker = _Docker()
    stand = _stand(docker, [200])
    got = stand.up("o/r", 12, "abc123", SERVICE)
    assert got.ok is True
    assert got.url == f"http://{env.container_name('o/r', 12)}:3000"


def test_container_is_ephemeral_not_restarting():
    docker = _Docker()
    _stand(docker, [200]).up("o/r", 12, "abc123", SERVICE)
    run_line = next(c for c in docker.flat() if "docker run" in c)
    assert "--rm" in run_line
    assert "--restart" not in run_line


def test_stale_container_is_reaped_before_start():
    docker = _Docker()
    _stand(docker, [200]).up("o/r", 12, "abc123", SERVICE)
    flat = docker.flat()
    rm_index = next(i for i, c in enumerate(flat) if "docker rm -f" in c)
    run_index = next(i for i, c in enumerate(flat) if "docker run" in c)
    assert rm_index < run_index


def test_no_start_command_means_no_container_at_all():
    docker = _Docker()
    got = _stand(docker, []).up("o/r", 12, "abc123", {"port": 3000})
    assert got.ok is False and "service.start" in got.detail
    assert not any("docker run" in c for c in docker.flat())


def test_probe_retries_until_ready():
    docker = _Docker()
    stand = _stand(docker, [OSError("отказ"), 503, 204])
    stand.poll_seconds = 0
    got = stand.up("o/r", 12, "abc123", SERVICE)
    assert got.ok is True


def test_failed_readiness_carries_container_logs():
    docker = _Docker()
    stand = _stand(docker, [OSError("отказ")] * 50)
    stand.ready_timeout = 0.05
    stand.poll_seconds = 0.01
    got = stand.up("o/r", 12, "abc123", SERVICE)
    assert got.ok is False
    assert any("docker logs" in c for c in docker.flat())


def test_down_removes_container():
    docker = _Docker()
    _stand(docker, []).down("o/r", 12)
    assert any("docker rm -f" in c and env.container_name("o/r", 12) in c
               for c in docker.flat())


def test_token_is_only_in_the_remote_url():
    docker = _Docker()
    _stand(docker, [200]).up("o/r", 12, "abc123", SERVICE)
    carrying = [c for c in docker.flat() if "ghs_x" in c]
    assert len(carrying) == 1 and "remote add" in carrying[0]
