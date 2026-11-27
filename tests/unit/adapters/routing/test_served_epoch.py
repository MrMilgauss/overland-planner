"""`ValhallaRoutingProvider.served_epoch()` against a scripted engine behind the transport seam (D301, D314).

The epoch is read from `/status` at every call: one attempt, never raising, never the cached identity.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from overland_planner.adapters.routing.valhalla_routing_provider import ValhallaRoutingProvider


class Engine:
    def __init__(self, version: str = "3.9.1", epoch: Any = 1_000) -> None:
        self.version, self.epoch, self.fail_with = version, epoch, None
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if isinstance(self.fail_with, Exception):
            raise self.fail_with
        if isinstance(self.fail_with, int):
            return httpx.Response(self.fail_with, text="down")
        if self.fail_with == "garbage":
            return httpx.Response(200, text="<html>")
        return httpx.Response(200, json={"version": self.version, "tileset_last_modified": self.epoch})


def provider_on(engine: Engine) -> ValhallaRoutingProvider:
    return ValhallaRoutingProvider(
        "http://engine",
        expected_version="3.9.1",
        max_matrix_pairs=2500,
        concurrency=2,
        snap_m=250,
        sleep=lambda _: None,
        transport=httpx.MockTransport(engine),
    )


def test_the_epoch_is_the_status_read_now_not_the_cached_identity() -> None:
    engine = Engine(epoch=1_000)
    provider = provider_on(engine)
    assert provider.provider_id == "valhalla:3.9.1:1000"  # the identity is cached from here
    engine.version, engine.epoch = "3.10.0", 2_000  # the engine changed version and map between two reads
    assert provider.served_epoch() == 2_000
    assert provider.served_id() == 2_000
    assert provider.provider_id == "valhalla:3.9.1:1000"  # and the identity stays what a probe last saw


@pytest.mark.parametrize(
    "fault",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), 500, 503, "garbage"],
    ids=["refused", "timeout", "500", "503", "not json"],
)
def test_a_failing_engine_gives_no_epoch_after_one_attempt(fault: Any) -> None:
    engine = Engine()
    engine.fail_with = fault
    assert provider_on(engine).served_epoch() is None
    assert engine.calls == 1


@pytest.mark.parametrize("epoch", ["1793", 1793.5, None, True, [1], "abc"], ids=repr)
def test_an_epoch_that_is_not_an_integer_is_no_epoch(epoch: Any) -> None:
    assert provider_on(Engine(epoch=epoch)).served_epoch() is None
