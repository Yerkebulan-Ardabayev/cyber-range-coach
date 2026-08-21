from __future__ import annotations

import asyncio
import socket
from contextlib import suppress

import pytest

from cyber_range_coach.services.relay import RelayManager


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_relay_rejects_unapproved_source_ip() -> None:
    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(100)
        writer.write(data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
    upstream_port = int(upstream.sockets[0].getsockname()[1])
    relay_port = free_port()
    manager = RelayManager("127.0.0.1", relay_port, relay_port, ttl_seconds=60)
    await manager.start(1, "127.0.0.1", upstream_port, "192.0.2.55")
    reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
    writer.write(b"secret")
    await writer.drain()
    try:
        rejected = await asyncio.wait_for(reader.read(), timeout=1)
    except ConnectionResetError:
        rejected = b""
    assert rejected == b""
    writer.close()
    with suppress(ConnectionResetError):
        await writer.wait_closed()
    await manager.stop_all()
    upstream.close()
    await upstream.wait_closed()


@pytest.mark.asyncio
async def test_relay_expires_after_ttl() -> None:
    upstream = await asyncio.start_server(lambda _reader, writer: writer.close(), "127.0.0.1", 0)
    upstream_port = int(upstream.sockets[0].getsockname()[1])
    relay_port = free_port()
    manager = RelayManager("127.0.0.1", relay_port, relay_port, ttl_seconds=0)
    await manager.start(2, "127.0.0.1", upstream_port, "192.0.2.55")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert manager.get(2) is None
    upstream.close()
    await upstream.wait_closed()
