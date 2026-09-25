#!/usr/bin/env python3
"""Range auto-discovery for v1 (spec 11.3 Ж, AC-11-9 emulation part).

Runs on the system Python 3.9 used by start.command, stdlib only.
"""
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import range_discovery
from range_discovery import (
    RangeLocator,
    is_juice_shop,
    is_webgoat,
    localize,
    subnet_candidates,
)


def stub_server(status, headers=(), body=""):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            payload = body.encode("utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class FingerprintTest(unittest.TestCase):
    def check(self, probe, server):
        try:
            return probe("127.0.0.1", server.server_address[1])
        finally:
            server.shutdown()
            server.server_close()

    def test_webgoat_redirect_to_login_is_accepted(self):
        server = stub_server(302, [("Location", "http://x:8080/WebGoat/login")])
        self.assertTrue(self.check(is_webgoat, server))

    def test_foreign_redirect_on_8080_is_rejected(self):
        server = stub_server(302, [("Location", "http://x:8080/admin/login")])
        self.assertFalse(self.check(is_webgoat, server))

    def test_foreign_200_on_8080_is_rejected(self):
        server = stub_server(200, body="<title>WebGoat</title>")
        self.assertFalse(self.check(is_webgoat, server))

    def test_juice_shop_title_is_accepted(self):
        server = stub_server(200, body="<html><title>OWASP Juice Shop</title></html>")
        self.assertTrue(self.check(is_juice_shop, server))

    def test_foreign_page_on_3000_is_rejected(self):
        server = stub_server(200, body="<html><title>Grafana</title></html>")
        self.assertFalse(self.check(is_juice_shop, server))

    def test_closed_port_is_rejected(self):
        server = stub_server(200)
        port = server.server_address[1]
        server.shutdown()
        server.server_close()
        self.assertFalse(is_juice_shop("127.0.0.1", port))


class FakeNetwork:
    """Emulated /24: which hosts have a range port open and what answers there."""

    def __init__(self, own, open_hosts, services):
        self.own = own
        self.open_hosts = set(open_hosts)
        self.services = services
        self.connects = []
        self.fingerprinted = []
        self.now = 1000.0

    def port_open(self, host, port):
        self.connects.append((host, port))
        return host in self.open_hosts

    def fingerprint(self, host):
        self.fingerprinted.append(host)
        return set(self.services.get(host, ()))

    def locator(self, cache):
        return RangeLocator(
            cache, clock=lambda: self.now, fingerprint=self.fingerprint,
            own_address=lambda: self.own, port_open=self.port_open,
        )


class LocatorTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cache = Path(self.directory.name) / "range_host.json"

    def tearDown(self):
        self.directory.cleanup()

    def test_laptop_moved_is_found_and_remembered(self):
        self.cache.write_text(json.dumps({"host": "192.168.10.10"}))
        net = FakeNetwork("192.168.10.3", ["192.168.10.5", "192.168.10.11"], {
            "192.168.10.5": (),  # someone else's service on 8080
            "192.168.10.11": ("webgoat", "juice-shop"),
        })
        found = net.locator(self.cache).locate()
        self.assertEqual(found["host"], "192.168.10.11")
        self.assertEqual(found["source"], "sweep")
        self.assertEqual(found["previous"], "192.168.10.10")
        self.assertEqual(json.loads(self.cache.read_text())["host"], "192.168.10.11")

    def test_remembered_host_is_checked_first_without_sweep(self):
        self.cache.write_text(json.dumps({"host": "192.168.10.11"}))
        net = FakeNetwork("192.168.10.3", ["192.168.10.11"], {"192.168.10.11": ("webgoat",)})
        found = net.locator(self.cache).locate()
        self.assertEqual((found["host"], found["source"]), ("192.168.10.11", "remembered"))
        self.assertEqual(net.connects, [])

    def test_foreign_services_only_means_not_found(self):
        net = FakeNetwork("192.168.10.3", ["192.168.10.5", "192.168.10.6"], {})
        found = net.locator(self.cache).locate()
        self.assertIsNone(found["host"])
        self.assertEqual(found["source"], "not_found")
        self.assertFalse(self.cache.exists())

    def test_host_with_both_services_wins(self):
        net = FakeNetwork("192.168.10.3", ["192.168.10.7", "192.168.10.11"], {
            "192.168.10.7": ("juice-shop",),
            "192.168.10.11": ("webgoat", "juice-shop"),
        })
        self.assertEqual(net.locator(self.cache).locate()["host"], "192.168.10.11")

    def test_full_sweep_at_most_once_per_minute(self):
        net = FakeNetwork("192.168.10.3", [], {})
        locator = net.locator(self.cache)
        self.assertEqual(locator.locate()["source"], "not_found")
        swept = len(net.connects)
        net.now += 30
        self.assertEqual(locator.locate()["source"], "rate_limited")
        self.assertEqual(len(net.connects), swept)
        net.now += 31
        self.assertEqual(locator.locate()["source"], "not_found")
        self.assertEqual(len(net.connects), swept * 2)

    def test_sweep_stays_in_own_24_and_known_ports(self):
        net = FakeNetwork("192.168.10.3", [], {})
        net.locator(self.cache).locate()
        hosts = {host for host, _port in net.connects}
        ports = {port for _host, port in net.connects}
        self.assertEqual(len(hosts), 253)
        self.assertTrue(all(host.startswith("192.168.10.") for host in hosts))
        self.assertNotIn("192.168.10.3", hosts)
        self.assertLessEqual(ports, set(range_discovery.PORTS))

    def test_public_or_missing_own_address_never_sweeps(self):
        self.assertEqual(subnet_candidates("8.8.8.8"), [])
        self.assertEqual(subnet_candidates(None), [])
        self.assertEqual(subnet_candidates("127.0.0.1"), [])

    def test_pinned_host_disables_sweep(self):
        net = FakeNetwork("192.168.10.3", ["192.168.10.11"], {"192.168.10.11": ("webgoat",)})
        locator = RangeLocator(self.cache, pinned_host="192.168.10.10", fingerprint=net.fingerprint,
                               own_address=lambda: net.own, port_open=net.port_open)
        self.assertEqual(locator.locate()["host"], "192.168.10.10")
        self.assertEqual(net.connects, [])

    def test_corrupt_cache_is_ignored(self):
        self.cache.write_text("{not json")
        net = FakeNetwork("192.168.10.3", ["192.168.10.11"], {"192.168.10.11": ("webgoat",)})
        self.assertEqual(net.locator(self.cache).locate()["host"], "192.168.10.11")


class LocalizeTest(unittest.TestCase):
    def test_texts_follow_found_host_but_target_identity_stays(self):
        lab = {"target": "192.168.10.10", "steps": [{"command": "nc -vz 192.168.10.10 8080",
                                                     "expect": [{"any_of": ["только 192.168.10.10"]}]}]}
        moved = localize(lab, "192.168.10.11")
        self.assertEqual(moved["target"], "192.168.10.11")
        self.assertEqual(moved["target_id"], "192.168.10.10")
        self.assertEqual(moved["steps"][0]["command"], "nc -vz 192.168.10.11 8080")
        self.assertEqual(moved["steps"][0]["expect"][0]["any_of"], ["только 192.168.10.11"])
        self.assertEqual(lab["steps"][0]["command"], "nc -vz 192.168.10.10 8080")
        self.assertEqual(localize({"target": "webgoat"}, "192.168.10.11")["target_id"], "webgoat")


class ServerLabTest(unittest.TestCase):
    def test_server_shows_found_host_and_keeps_mastery_identity(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            os.environ["CYBER_RANGE_COACH_DB"] = str(Path(directory) / "state.sqlite")
            os.environ["CYBER_RANGE_COACH_RANGE_HOST"] = "192.168.10.11"
            import server
            lab = server.load_content("labs", "lab-1-1-scope-reachability")
            self.assertEqual(lab["target"], "192.168.10.11")
            self.assertEqual(lab["target_id"], "192.168.10.10")
            shown = json.dumps(server.public_lab(lab), ensure_ascii=False)
            self.assertNotIn("192.168.10.10", shown)


class ServerRangeTest(unittest.TestCase):
    def setUp(self):
        import os
        self.directory = tempfile.TemporaryDirectory()
        os.environ["CYBER_RANGE_COACH_DB"] = str(Path(self.directory.name) / "state.sqlite")
        os.environ.pop("CYBER_RANGE_COACH_RANGE_HOST", None)
        import importlib

        import server
        self.server = importlib.reload(server)

    def tearDown(self):
        self.directory.cleanup()

    def test_not_found_never_probes_or_shows_an_unverified_address(self):
        empty = Path(self.directory.name) / "never-found.json"
        lost = RangeLocator(empty, fingerprint=lambda _host: set(), own_address=lambda: None,
                            port_open=lambda _host, _port: False)

        def forbidden(*_args):
            raise AssertionError("unverified address was probed")

        self.server.RANGE_LOCATOR = lost
        self.server.tcp_check = forbidden
        self.server.http_get = forbidden
        result = self.server.health()
        self.assertIsNone(result["host"])
        self.assertEqual(result["verdict"], "OFFLINE")
        self.assertNotIn("192.168.10.10", json.dumps(result, ensure_ascii=False))
        lab = self.server.load_content("labs", "lab-1-1-scope-reachability")
        shown = dict(lab)
        shown.pop("target_id")
        self.assertNotIn("192.168.10.10", json.dumps(shown, ensure_ascii=False))
        self.assertIn(range_discovery.UNKNOWN_HOST, lab["steps"][1]["command"])

    def test_moved_laptop_is_not_a_second_target_for_mastery(self):
        lab = {
            "id": "lab-moved", "target": "192.168.10.11", "target_id": "192.168.10.10", "skills": ["scope"],
            "steps": [{"id": "decide", "kind": "decide", "decision_options": ["right", "wrong"]}, {"id": "debrief"}],
        }
        with self.server.database() as connection:
            connection.execute("INSERT INTO skill_target(skill_id, target) VALUES ('scope', '192.168.10.10')")
            connection.execute("INSERT INTO skill_progress(skill_id, level, assistance_level) VALUES ('scope', 4, 0)")
            connection.execute("INSERT INTO attempt(lab_id, step_id, hypothesis, decision_choice) VALUES ('lab-moved', 'decide', 'h', 'right')")
            debrief = connection.execute("INSERT INTO attempt(lab_id, step_id, hypothesis) VALUES ('lab-moved', 'debrief', 'h')").lastrowid
            result = self.server.close_learning(connection, lab, debrief)
            targets = [row[0] for row in connection.execute("SELECT target FROM skill_target WHERE skill_id = 'scope'")]
        self.assertEqual(result[0]["level"], 4)
        self.assertEqual(targets, ["192.168.10.10"])


class LocalizeEdgeTest(unittest.TestCase):
    def test_longer_address_is_not_rewritten(self):
        self.assertEqual(localize("192.168.10.100 and 192.168.10.10", "192.168.10.11"),
                         "192.168.10.100 and 192.168.10.11")


if __name__ == "__main__":
    unittest.main(verbosity=1)
