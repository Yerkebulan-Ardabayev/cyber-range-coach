"""Find the owner's own range in the local /24 by service fingerprint.

Scope is deliberately narrow (spec 11.3 Ж): only the Mac's own /24, only TCP
connects to the two known range ports, at most one full sweep per minute.
A host counts as the range only when a port answers with the expected
application fingerprint, so a foreign service on 8080 or 3000 is ignored.
"""
import ipaddress
import json
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

DEFAULT_HOST = "192.168.10.10"
UNKNOWN_HOST = "АДРЕС-СТЕНДА"
_DEFAULT_PATTERN = re.compile(re.escape(DEFAULT_HOST) + r"(?!\d)")
PORTS = (8080, 3000)
SWEEP_INTERVAL_SECONDS = 60.0
CONNECT_TIMEOUT_SECONDS = 0.4
HTTP_TIMEOUT_SECONDS = 1.5


def http_get(host, port, path, timeout=HTTP_TIMEOUT_SECONDS):
    """Return (status, headers_text, body) of one plain GET, or (None, '', '')."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            request = (
                "GET " + path + " HTTP/1.1\r\n"
                "Host: " + host + ":" + str(port) + "\r\n"
                "Connection: close\r\n\r\n"
            )
            connection.sendall(request.encode("ascii"))
            chunks = []
            while sum(len(part) for part in chunks) <= 131072:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError:
        return None, "", ""
    raw = b"".join(chunks).decode("utf-8", "replace")
    head, _, body = raw.partition("\r\n\r\n")
    first_line = head.split("\r\n", 1)[0].split()
    try:
        status = int(first_line[1]) if len(first_line) >= 2 and first_line[0].startswith("HTTP/") else None
    except ValueError:
        status = None
    return status, head, body


def is_webgoat(host, port=8080):
    status, head, _body = http_get(host, port, "/WebGoat/")
    if status != 302:
        return False
    for line in head.split("\r\n")[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "location" and "/WebGoat/login" in value:
            return True
    return False


def is_juice_shop(host, port=3000):
    status, _head, body = http_get(host, port, "/")
    return status == 200 and "OWASP Juice Shop" in body


def fingerprint(host):
    """Services of the range that really answer on host, e.g. {'webgoat'}."""
    found = set()
    if is_webgoat(host):
        found.add("webgoat")
    if is_juice_shop(host):
        found.add("juice-shop")
    return found


def own_ipv4():
    """Address of the interface that carries the default route (no packet is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def subnet_candidates(own_address):
    if not own_address:
        return []
    address = ipaddress.ip_address(own_address)
    if not address.is_private or address.is_loopback:
        return []
    network = ipaddress.ip_network(own_address + "/24", strict=False)
    return [str(host) for host in network.hosts() if str(host) != own_address]


def port_open(host, port, timeout=CONNECT_TIMEOUT_SECONDS):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class RangeLocator:
    """Remembers the last found range host and rediscovers it when it moves."""

    def __init__(self, cache_path, pinned_host=None, clock=time.monotonic,
                 fingerprint=fingerprint, own_address=own_ipv4, port_open=port_open):
        self.cache_path = cache_path
        self.pinned_host = pinned_host
        self.clock = clock
        self.fingerprint = fingerprint
        self.own_address = own_address
        self.port_open = port_open
        self.last_sweep = None
        self.lock = threading.Lock()

    def remembered(self):
        if self.pinned_host:
            return self.pinned_host
        try:
            with open(self.cache_path, encoding="utf-8") as source:
                host = json.load(source).get("host")
            ipaddress.ip_address(host)
            return host
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def current(self):
        """Host for lab texts: the last found one, without any network activity.

        Before the first successful search the old default is never shown,
        a neutral placeholder tells the learner to open the Range page first.
        """
        return self.remembered() or UNKNOWN_HOST

    def _remember(self, host):
        payload = json.dumps({"host": host}, ensure_ascii=False)
        temporary = str(self.cache_path) + ".tmp"
        with open(temporary, "w", encoding="utf-8") as target:
            target.write(payload)
        os.replace(temporary, str(self.cache_path))

    def locate(self):
        """Return {'host', 'services', 'source'}; host is None when nothing answers.

        source: pinned, remembered, sweep, rate_limited or not_found.
        """
        with self.lock:
            if self.pinned_host:
                return {"host": self.pinned_host, "services": sorted(self.fingerprint(self.pinned_host)), "source": "pinned"}
            known = self.remembered()
            if known:
                services = self.fingerprint(known)
                if services:
                    return {"host": known, "services": sorted(services), "source": "remembered"}
            now = self.clock()
            if self.last_sweep is not None and now - self.last_sweep < SWEEP_INTERVAL_SECONDS:
                return {"host": None, "services": [], "source": "rate_limited", "previous": known}
            self.last_sweep = now
            candidates = subnet_candidates(self.own_address())
            with ThreadPoolExecutor(max_workers=64) as pool:
                answered = list(pool.map(lambda host: any(self.port_open(host, port) for port in PORTS), candidates))
            reachable = [host for index, host in enumerate(candidates) if answered[index]]
            best = None
            for host in reachable:
                services = self.fingerprint(host)
                if services and (best is None or len(services) > len(best[1])):
                    best = (host, services)
            if best is None:
                return {"host": None, "services": [], "source": "not_found", "previous": known}
            self._remember(best[0])
            return {"host": best[0], "services": sorted(best[1]), "source": "sweep", "previous": known}


def localize(value, host, skip_keys=("target_id",)):
    """Replace the default range address in lab texts with the found host.

    `target_id` keeps the original target: it is the stable identity used for
    mastery bookkeeping, so a moved laptop never counts as a second target.
    """
    if isinstance(value, dict) and "target" in value and "target_id" not in value:
        value = dict(value, target_id=value["target"])
    if host == DEFAULT_HOST:
        return value
    if isinstance(value, str):
        return _DEFAULT_PATTERN.sub(host, value)
    if isinstance(value, list):
        return [localize(item, host, skip_keys) for item in value]
    if isinstance(value, dict):
        return {
            key: (item if key in skip_keys else localize(item, host, skip_keys))
            for key, item in value.items()
        }
    return value
