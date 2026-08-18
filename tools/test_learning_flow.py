#!/usr/bin/env python3
"""API acceptance test for one complete, evidence-led learning attempt.

It uses an isolated temporary SQLite file.  The user's state.sqlite is never
opened or changed by this test.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def request(base, path, payload=None, expected=200):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if data is None else {"Content-Type": "application/json"}
    response = urlopen(Request(base + path, data=data, headers=headers), timeout=5)
    if response.status != expected:
        raise AssertionError("%s returned %s, expected %s" % (path, response.status, expected))
    return json.loads(response.read().decode("utf-8"))


def wait_ready(base):
    last_error = None
    for _ in range(40):
        try:
            request(base, "/api/today")
            return
        except (URLError, ConnectionError, OSError) as error:
            last_error = error
            time.sleep(0.05)
    raise RuntimeError("Test server did not start: %s" % last_error)


def main():
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    with tempfile.TemporaryDirectory(prefix="cyber-range-coach-test-") as temporary:
        environment = os.environ.copy()
        environment["CYBER_RANGE_COACH_PORT"] = str(port)
        environment["CYBER_RANGE_COACH_DB"] = str(Path(temporary) / "state.sqlite")
        server = subprocess.Popen(
            [sys.executable, "server.py"], cwd=str(ROOT), env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            wait_ready(base)
            today = request(base, "/api/today")
            assert today["lab"] == "lab-1-1-scope-reachability", today
            assert today["resume"] is None, today

            command_attempt = request(base, "/api/attempt", {
                "lab_id": "lab-1-2-service-enumeration", "step_id": "execute",
                "hypothesis": "Хочу перечислить сервисы и их версии на одном своём узле.",
            }, expected=201)["attempt_id"]
            protected = request(base, "/api/lab/lab-1-2-service-enumeration")
            assert "command" not in protected["steps"][1], "command leaked before hypothesis gate"
            opened = request(base, "/api/lab/lab-1-2-service-enumeration?attempt_id=%d" % command_attempt)
            assert opened["steps"][1]["command"] == "nmap -sV 192.168.10.10"
            try:
                request(base, "/api/attempt", {
                    "lab_id": "lab-1-1-scope-reachability", "step_id": "execute",
                    "hypothesis": "Эта вторая попытка не должна быть создана.",
                }, expected=201)
                raise AssertionError("a second learning run was allowed over an open attempt")
            except HTTPError as error:
                assert error.code == 409, error.code

            raw = """Nmap scan report for 192.168.10.10
PORT     STATE SERVICE VERSION
3000/tcp open  http    Node.js Express framework
8080/tcp open  http    Apache Tomcat 10.1
"""
            parsed = request(base, "/api/attempt/%d/output" % command_attempt, {"raw": raw})
            assert len(parsed["facts"]) >= 6, parsed
            analyse_attempt = request(base, "/api/attempt", {
                "lab_id": "lab-1-2-service-enumeration", "step_id": "analyse",
                "hypothesis": "Отделить факты вывода от предположений.",
                "continue_attempt_id": command_attempt,
            }, expected=201)["attempt_id"]
            feedback = request(base, "/api/attempt/%d/conclusion" % analyse_attempt, {
                "text": "Открыто два порта, 3000 и 8080, оба HTTP. В выводе есть Express и Tomcat 10.1. Это ещё не доказывает уязвимость."
            })
            assert feedback["named"], feedback
            assert feedback["missed"], feedback

            decide_attempt = request(base, "/api/attempt", {
                "lab_id": "lab-1-2-service-enumeration", "step_id": "decide",
                "hypothesis": "Выбрать следующий шаг по подтверждённым сервисам.",
                "continue_attempt_id": analyse_attempt,
            }, expected=201)["attempt_id"]
            context = request(base, "/api/lab/lab-1-2-service-enumeration/attempt-context?attempt_id=%d" % decide_attempt)
            assert context["step_id"] == "decide", context
            assert context["mentor_feedback"]["named"], context
            decision = request(base, "/api/attempt/%d/decision" % decide_attempt, {
                "choice": "Продолжить по подтверждённому веб-сервису."
            })
            assert decision["correct"] is True, decision
            debrief_attempt = request(base, "/api/attempt", {
                "lab_id": "lab-1-2-service-enumeration", "step_id": "debrief",
                "hypothesis": "Сначала перечисление, потом оценка риска.",
                "continue_attempt_id": decide_attempt,
            }, expected=201)["attempt_id"]
            closed = request(base, "/api/attempt/%d/debrief" % debrief_attempt, {"verdict": "completed"})
            assert closed["closed"] is True, closed
            notes = request(base, "/api/notes")
            assert notes and "Nmap scan report" in notes[0]["results"], notes
            restart_attempt = request(base, "/api/attempt", {
                "lab_id": "lab-1-1-scope-reachability", "step_id": "execute",
                "hypothesis": "Повторить проверку достижимости с новым выводом.",
            }, expected=201)["attempt_id"]
            abandoned = request(base, "/api/lab/lab-1-1-scope-reachability/abandon", {
                "attempt_id": restart_attempt,
            })
            assert abandoned["abandoned"] == 1, abandoned
            assert request(base, "/api/today")["resume"] is None
            syntax_attempt = request(base, "/api/attempt", {
                "lab_id": "lab-1-1-scope-reachability", "step_id": "execute",
                "hypothesis": "Проверить достижимость только учебного адреса.",
            }, expected=201)["attempt_id"]
            syntax_result = request(base, "/api/attempt/%d/output" % syntax_attempt, {
                "raw": "nc: invalid option -- V\nusage: nc [-46AacCDdEFhklMnOortUuvz] [hostname] [port[s]]",
            })
            assert syntax_result["diagnosis"]["kind"] == "command_syntax", syntax_result
            assert "-vz" in syntax_result["diagnosis"]["next"], syntax_result
            abandoned_syntax = request(base, "/api/lab/lab-1-1-scope-reachability/abandon", {
                "attempt_id": syntax_attempt,
            })
            assert abandoned_syntax["abandoned"] == 1, abandoned_syntax
            assert request(base, "/api/today")["resume"] is None
            print("LEARNING FLOW ACCEPTANCE PASSED")
            return 0
        finally:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=3)


if __name__ == "__main__":
    sys.exit(main())
