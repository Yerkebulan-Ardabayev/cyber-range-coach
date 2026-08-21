from __future__ import annotations

import json

import pytest

from cyber_range_coach.services.commands import CommandResult
from cyber_range_coach.services.docker import DockerDiscovery


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def run(self, executable: str, *args: str, **_kwargs: object) -> CommandResult:
        argv = (executable, *args)
        self.calls.append(argv)
        if args[0] == "version":
            return CommandResult(argv, 0, '{"Version":"test"}', "")
        if args[:2] == ("ps", "--no-trunc"):
            return CommandResult(
                argv,
                0,
                json.dumps(
                    {
                        "ID": "a" * 64,
                        "Image": "bkimminich/juice-shop",
                        "Names": "juice",
                        "State": "running",
                    }
                )
                + "\n",
                "",
            )
        if args[0] == "inspect":
            payload = [
                {
                    "Id": "a" * 64,
                    "Image": "sha256:" + "b" * 64,
                    "Name": "/juice",
                    "Config": {"Image": "bkimminich/juice-shop"},
                    "State": {"Status": "running", "StartedAt": "2026-08-20T00:00:00Z"},
                    "NetworkSettings": {
                        "Ports": {"3000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3000"}]}
                    },
                }
            ]
            return CommandResult(argv, 0, json.dumps(payload), "")
        if args[0] == "port":
            return CommandResult(argv, 0, "3000/tcp -> 0.0.0.0:3000\n", "")
        raise AssertionError(argv)


@pytest.mark.asyncio
async def test_discovery_is_read_only_and_warns_about_all_interfaces() -> None:
    runner = FakeRunner()
    discovery = DockerDiscovery(runner)
    targets = await discovery.discover()
    assert len(targets) == 1
    assert targets[0].detected_kind == "juice_shop"
    assert targets[0].ports[0].loopback_endpoint == "http://127.0.0.1:3000"
    assert "всех интерфейсах" in targets[0].warnings[0]
    mutating = {"run", "start", "stop", "restart", "rm", "pull", "volume", "compose"}
    assert not any(mutating.intersection(call[1:]) for call in runner.calls)
    assert ("docker", "port", "a" * 64) in runner.calls
