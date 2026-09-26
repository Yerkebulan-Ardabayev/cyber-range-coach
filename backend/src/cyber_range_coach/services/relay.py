from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass, field

from ..errors import AppError
from ..models import LinuxHost

logger = logging.getLogger(__name__)


def validate_relay_source_ip(value: str) -> str:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError as exc:
        raise AppError(400, "invalid_vm_ip", "Нужен фактический IP Linux VM.") from exc
    if parsed.is_unspecified or parsed.is_multicast or parsed.is_loopback:
        raise AppError(400, "invalid_vm_ip", "Нужен отдельный IP Linux VM, не loopback.")
    return str(parsed)


def configured_relay_source_ip(host: LinuxHost) -> str:
    return validate_relay_source_ip(host.relay_source_ip or host.host)


@dataclass
class RelayHandle:
    target_id: int
    bind_host: str
    port: int
    upstream_host: str
    upstream_port: int
    allowed_source_ip: str
    server: asyncio.AbstractServer
    connections: set[asyncio.Task[None]] = field(default_factory=set)
    timeout_task: asyncio.Task[None] | None = None


class RelayManager:
    def __init__(self, bind_host: str, port_start: int, port_end: int, ttl_seconds: int):
        self.bind_host = bind_host
        self.port_start = port_start
        self.port_end = port_end
        self.ttl_seconds = ttl_seconds
        self._handles: dict[int, RelayHandle] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        target_id: int,
        upstream_host: str,
        upstream_port: int,
        allowed_source_ip: str,
        bind_host: str | None = None,
        port: int | None = None,
    ) -> RelayHandle:
        """Start or reuse the relay of a target.

        bind_host narrows the listener to the Windows address the Linux VM
        reaches (spec 11.3 Zh): the WSL firewall rule allows 172.16.0.0/12 in
        any profile, so a listener on 0.0.0.0 would also be open on Wi-Fi.
        """
        allowed_source_ip = validate_relay_source_ip(allowed_source_ip)
        listen_host = bind_host or self.bind_host
        parsed_upstream = ipaddress.ip_address(upstream_host)
        if not parsed_upstream.is_loopback:
            raise AppError(
                400, "unsafe_upstream", "Relay может обращаться только к loopback Windows."
            )
        if port is not None and not self.port_start <= port <= self.port_end:
            raise AppError(400, "relay_port_out_of_range", "Порт relay вне разрешённого диапазона.")
        async with self._lock:
            existing = self._handles.get(target_id)
            if existing:
                if (
                    existing.allowed_source_ip == allowed_source_ip
                    and existing.bind_host == listen_host
                    and (port is None or existing.port == port)
                ):
                    return existing
                # WSL came back with a new address (spec 11.3 Zh): the old
                # relay only accepts the previous one, so it is replaced.
                await self._close(existing)
            # An active lab tells the learner its relay port, so a restored
            # relay must come back on exactly that port.
            candidates = [port] if port is not None else range(self.port_start, self.port_end + 1)
            for candidate in candidates:
                try:
                    server = await asyncio.start_server(
                        lambda reader, writer: self._accept(
                            target_id,
                            reader,
                            writer,
                            upstream_host,
                            upstream_port,
                            allowed_source_ip,
                        ),
                        listen_host,
                        candidate,
                        reuse_address=False,
                    )
                except OSError:
                    continue
                handle = RelayHandle(
                    target_id=target_id,
                    bind_host=listen_host,
                    port=candidate,
                    upstream_host=upstream_host,
                    upstream_port=upstream_port,
                    allowed_source_ip=allowed_source_ip,
                    server=server,
                )
                self._handles[target_id] = handle
                handle.timeout_task = asyncio.create_task(self._expire(target_id))
                return handle
        if port is not None:
            raise AppError(
                503,
                "relay_port_busy",
                "Порт relay этой лабы занят другой программой. Начните чистую попытку.",
            )
        raise AppError(503, "relay_ports_exhausted", "Нет свободного безопасного relay-порта.")

    async def _expire(self, target_id: int) -> None:
        try:
            await asyncio.sleep(self.ttl_seconds)
            await self.stop(target_id)
        except asyncio.CancelledError:
            return

    async def _accept(
        self,
        target_id: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        upstream_host: str,
        upstream_port: int,
        allowed_source_ip: str,
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = str(peer[0]) if isinstance(peer, tuple) and peer else ""
        if peer_ip != allowed_source_ip:
            writer.close()
            await writer.wait_closed()
            return
        task = asyncio.current_task()
        handle = self._handles.get(target_id)
        if task and handle:
            handle.connections.add(task)
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                upstream_host, upstream_port
            )
            await asyncio.gather(
                self._pipe(reader, upstream_writer),
                self._pipe(upstream_reader, writer),
            )
        except OSError:
            writer.close()
            await writer.wait_closed()
        finally:
            if task and handle:
                handle.connections.discard(task)

    @staticmethod
    async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while data := await reader.read(65_536):
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError as exc:
                logger.debug("Relay peer closed during shutdown: %s", type(exc).__name__)

    async def stop(self, target_id: int) -> None:
        async with self._lock:
            handle = self._handles.pop(target_id, None)
        if handle is None:
            return
        await self._close(handle)

    async def _close(self, handle: RelayHandle) -> None:
        self._handles.pop(handle.target_id, None)
        handle.server.close()
        await handle.server.wait_closed()
        if handle.timeout_task and handle.timeout_task is not asyncio.current_task():
            handle.timeout_task.cancel()
        for task in tuple(handle.connections):
            task.cancel()
        if handle.connections:
            await asyncio.gather(*handle.connections, return_exceptions=True)
        if handle.timeout_task and handle.timeout_task is not asyncio.current_task():
            await asyncio.gather(handle.timeout_task, return_exceptions=True)

    async def stop_all(self) -> None:
        for target_id in tuple(self._handles):
            await self.stop(target_id)

    def get(self, target_id: int) -> RelayHandle | None:
        return self._handles.get(target_id)
