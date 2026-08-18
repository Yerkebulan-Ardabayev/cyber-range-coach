#!/usr/bin/env python3
"""Cyber Range Coach local server.

The server intentionally has no target-operation endpoints. Its only network
activity is the four range health checks defined below.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import socket
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse
from parsers import parse

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
CONTENT_ROOT = ROOT / "content"
DB_PATH = Path(os.environ.get("CYBER_RANGE_COACH_DB", str(ROOT / "state.sqlite")))
HOST = "127.0.0.1"
PORT = int(os.environ.get("CYBER_RANGE_COACH_PORT", "8899"))
RANGE_HOST = "192.168.10.10"
RANGE_PORTS = (8080, 3000)
TIMEOUT_SECONDS = 1.5


SCHEMA = """
CREATE TABLE IF NOT EXISTS attempt (
    id INTEGER PRIMARY KEY,
    lab_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    hypothesis TEXT NOT NULL,
    raw_output TEXT,
    user_conclusion TEXT,
    hints_used INTEGER NOT NULL DEFAULT 0,
    revealed_solution INTEGER NOT NULL DEFAULT 0,
    decision_choice TEXT,
    verdict TEXT
);
CREATE TABLE IF NOT EXISTS observation (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempt(id),
    kind TEXT NOT NULL CHECK(kind IN ('fact', 'hypothesis')),
    text TEXT NOT NULL,
    source_line INTEGER
);
CREATE TABLE IF NOT EXISTS note (
    id INTEGER PRIMARY KEY,
    lab_id TEXT NOT NULL,
    date TEXT NOT NULL,
    goal TEXT, hypothesis TEXT, commands TEXT, results TEXT,
    conclusion TEXT, mistakes TEXT, learned TEXT
);
CREATE TABLE IF NOT EXISTS skill_progress (
    skill_id TEXT PRIMARY KEY,
    level INTEGER NOT NULL DEFAULT 0 CHECK(level BETWEEN 0 AND 5),
    assistance_level INTEGER NOT NULL DEFAULT 4 CHECK(assistance_level BETWEEN 0 AND 4),
    last_seen TEXT,
    next_review TEXT
);
CREATE TABLE IF NOT EXISTS review_queue (
    skill_id TEXT NOT NULL,
    due_date TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY(skill_id, due_date)
);
CREATE TABLE IF NOT EXISTS skill_target (
    skill_id TEXT NOT NULL,
    target TEXT NOT NULL,
    first_passed_ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(skill_id, target)
);
CREATE TABLE IF NOT EXISTS range_check (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    ok INTEGER NOT NULL CHECK(ok IN (0, 1)),
    detail TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS attempt_closed_is_immutable
BEFORE UPDATE ON attempt
WHEN OLD.verdict IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'closed attempt is immutable');
END;
CREATE TRIGGER IF NOT EXISTS attempt_closed_cannot_delete
BEFORE DELETE ON attempt
WHEN OLD.verdict IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'closed attempt is immutable');
END;
"""


def database():
    """Create the state database lazily and return a short-lived connection."""
    connection = sqlite3.connect(DB_PATH)
    connection.executescript(SCHEMA)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(note)")}
    if "manual_paragraph" not in columns:
        connection.execute("ALTER TABLE note ADD COLUMN manual_paragraph TEXT NOT NULL DEFAULT ''")
    connection.commit()
    return connection


def load_content(category, item_id=None):
    directory = CONTENT_ROOT / category
    items = []
    for path in sorted(directory.glob("*.json")):
        with path.open(encoding="utf-8") as source:
            item = json.load(source)
        if item_id is None or item.get("id") == item_id:
            items.append(item)
    if item_id is not None:
        return items[0] if items else None
    return items


PRIVATE_STEP_FIELDS = {"command", "command_anatomy", "solution", "hints", "decision_options"}
REVIEW_INTERVALS = (1, 3, 7, 21)


def find_step(lab_id, step_id):
    lab = load_content("labs", lab_id)
    if not lab:
        return None, None
    for step in lab.get("steps", []):
        if step.get("id") == step_id:
            return lab, step
    return lab, None


def open_attempt_for_step(lab_id, step_id, attempt_id=None):
    """Return only the current open attempt for one exact step.

    A completed attempt is learning history, never permission to reveal a
    command or answer in a later repetition.
    """
    with database() as connection:
        if attempt_id is None:
            return None
        return connection.execute(
            "SELECT id, hypothesis FROM attempt WHERE id = ? AND lab_id = ? "
            "AND step_id = ? AND verdict IS NULL AND TRIM(hypothesis) != ''",
            (attempt_id, lab_id, step_id),
        ).fetchone()


def assistance_for_lab(lab):
    with database() as connection:
        skill_ids = lab.get("skills", [])
        if skill_ids:
            placeholders = ",".join("?" for _item in skill_ids)
            rows = connection.execute(
                "SELECT assistance_level FROM skill_progress WHERE skill_id IN (%s)" % placeholders, skill_ids).fetchall()
            levels = [row[0] for row in rows]
        else:
            levels = []
    return min(levels) if levels else 4


def public_step(lab_id, step, attempt_id=None, reveal=None):
    visible = dict(step)
    lab = load_content("labs", lab_id)
    open_attempt = open_attempt_for_step(lab_id, step.get("id"), attempt_id)
    if not open_attempt:
        for field in PRIVATE_STEP_FIELDS:
            visible.pop(field, None)
        return visible
    level = assistance_for_lab(lab)
    # These fields are removed before serialization, never merely hidden by CSS.
    if level == 3:
        visible.pop("why", None)
        visible.pop("expect", None)
        visible.pop("distractors", None)
    elif level == 2:
        visible.pop("command_anatomy", None)
        if reveal != "command":
            visible.pop("command", None)
    elif level == 1:
        for field in ("why", "command", "command_anatomy", "expect", "distractors", "hints", "solution"):
            visible.pop(field, None)
    elif level == 0:
        return {"id": step.get("id"), "kind": step.get("kind"), "mission_only": True}
    return visible


def public_lab(lab, attempt_id=None, reveal=None):
    visible = dict(lab)
    if assistance_for_lab(lab) == 0 and open_attempt_for_step(lab["id"], lab["steps"][0]["id"], attempt_id):
        return {"id": lab["id"], "mission": lab["mission"], "objective": lab["objective"], "steps": []}
    visible["steps"] = [public_step(lab["id"], step, attempt_id, reveal) for step in lab.get("steps", [])]
    return visible


def attempt_context(lab_id, attempt_id):
    """Return the learner's own artefacts needed to resume one open lab.

    This deliberately exposes neither content answers nor another attempt.  A
    browser refresh must not turn the learner's real terminal output and own
    conclusion into an empty, unexplained screen.
    """
    with database() as connection:
        current = connection.execute(
            "SELECT id, step_id FROM attempt WHERE id = ? AND lab_id = ? "
            "AND verdict IS NULL", (attempt_id, lab_id)
        ).fetchone()
        if not current:
            return None
        previous_closed = connection.execute(
            "SELECT MAX(id) FROM attempt WHERE lab_id = ? AND verdict IS NOT NULL "
            "AND id < ?", (lab_id, attempt_id)
        ).fetchone()[0] or 0
        rows = connection.execute(
            "SELECT id, step_id, hypothesis, raw_output, user_conclusion, "
            "decision_choice, hints_used, revealed_solution FROM attempt "
            "WHERE lab_id = ? AND id > ? AND id <= ? ORDER BY id",
            (lab_id, previous_closed, attempt_id),
        ).fetchall()
        facts = connection.execute(
            "SELECT attempt_id, text, source_line FROM observation "
            "WHERE kind = 'fact' AND attempt_id IN "
            "(SELECT id FROM attempt WHERE lab_id = ? AND id > ? AND id <= ?) "
            "ORDER BY id",
            (lab_id, previous_closed, attempt_id),
        ).fetchall()
    by_attempt = {}
    for fact_attempt, text, line in facts:
        by_attempt.setdefault(fact_attempt, []).append({"text": text, "line": line})
    attempts = []
    for row in rows:
        attempts.append({
            "id": row[0], "step_id": row[1], "hypothesis": row[2],
            "raw_output": row[3], "user_conclusion": row[4],
            "decision_choice": row[5], "hints_used": row[6],
            "revealed_solution": bool(row[7]), "facts": by_attempt.get(row[0], []),
        })
    lab = load_content("labs", lab_id)
    for item in attempts:
        if item["raw_output"]:
            step = next((entry for entry in lab.get("steps", []) if entry.get("id") == item["step_id"]), {})
            item["diagnosis"] = execution_diagnosis(step, item["raw_output"], item["facts"])
    analyse_step = next((step for step in lab.get("steps", []) if step.get("id") == "analyse"), None)
    mentor_feedback = None
    if analyse_step:
        analyse_attempt = next((item for item in attempts if item["step_id"] == "analyse" and item["user_conclusion"]), None)
        if analyse_attempt:
            mentor_feedback = score_conclusion(analyse_step, analyse_attempt["user_conclusion"], analyse_attempt["facts"])
    decide_step = next((step for step in lab.get("steps", []) if step.get("id") == "decide"), None)
    decision = next((item for item in attempts if item["step_id"] == "decide" and item["decision_choice"]), None)
    decision_result = decision_feedback(decide_step, decision["decision_choice"]) if decide_step and decision else None
    return {"attempt_id": current[0], "step_id": current[1], "attempts": attempts,
            "mentor_feedback": mentor_feedback, "decision_feedback": decision_result}


def queue_review(connection, skill_id, reason):
    existing = connection.execute("SELECT COUNT(*) FROM review_queue WHERE skill_id = ?", (skill_id,)).fetchone()[0]
    offset = REVIEW_INTERVALS[min(existing, len(REVIEW_INTERVALS) - 1)]
    connection.execute("INSERT OR REPLACE INTO review_queue(skill_id, due_date, reason) VALUES (?, date('now', ?), ?)", (skill_id, "+%d day" % offset, reason))


def close_learning(connection, lab, attempt_id):
    # Снижение помощи и рост навыка происходят один раз за ПРОХОЖДЕНИЕ ЛАБЫ,
    # а не на каждом шаге. Иначе за одну лабу из пяти шагов помощь улетает
    # с L4 до L0 и снижение перестаёт быть постепенным.
    closed_step_id = connection.execute("SELECT step_id FROM attempt WHERE id = ?", (attempt_id,)).fetchone()
    final_step = lab["steps"][-1]["id"] if lab.get("steps") else None
    if not closed_step_id or closed_step_id[0] != final_step:
        return []
    previous = connection.execute("SELECT MAX(id) FROM attempt WHERE lab_id = ? AND step_id = 'debrief' AND verdict IS NOT NULL AND id < ?", (lab["id"], attempt_id)).fetchone()[0] or 0
    rows = connection.execute("SELECT hints_used, revealed_solution, decision_choice, step_id FROM attempt WHERE lab_id = ? AND id > ? AND id <= ?", (lab["id"], previous, attempt_id)).fetchall()
    decisions = [row for row in rows if row[3] == "decide"]
    decide_step = next((step for step in lab["steps"] if step.get("kind") == "decide"), None)
    correct = bool(decisions and decide_step and decisions[-1][2] == decide_step.get("decision_options", [None])[0])
    clean = all(row[0] < 3 and not row[1] for row in rows) and correct
    result = []
    for skill_id in lab.get("skills", []):
        progress = connection.execute("SELECT level, assistance_level FROM skill_progress WHERE skill_id = ?", (skill_id,)).fetchone() or (0, 4)
        old_level, assistance = progress
        target_seen = connection.execute("SELECT 1 FROM skill_target WHERE skill_id = ? AND target = ?", (skill_id, lab["target"])).fetchone() is not None
        prior_target = connection.execute("SELECT 1 FROM skill_target WHERE skill_id = ?", (skill_id,)).fetchone() is not None
        achieved = (5 if prior_target and not target_seen else 4) if assistance == 0 else 5 - assistance
        # Уровень навыка растёт только за чистое прохождение: с подсмотренным
        # решением или подсказкой 3 это не доказательство умения.
        level = max(old_level, achieved) if clean else old_level
        if assistance == 0 and not target_seen:
            connection.execute("INSERT INTO skill_target(skill_id, target) VALUES (?, ?)", (skill_id, lab["target"]))
        if clean and assistance > 0:
            assistance -= 1
        elif not clean:
            queue_review(connection, skill_id, "solution, hint 3 or incorrect decision")
        connection.execute("INSERT INTO skill_progress(skill_id, level, assistance_level, last_seen, next_review) VALUES (?, ?, ?, CURRENT_TIMESTAMP, NULL) ON CONFLICT(skill_id) DO UPDATE SET level=excluded.level, assistance_level=excluded.assistance_level, last_seen=excluded.last_seen", (skill_id, level, assistance))
        failed = connection.execute("SELECT COUNT(*) FROM attempt WHERE lab_id = ? AND verdict = 'failed'", (lab["id"],)).fetchone()[0]
        result.append({"skill_id": skill_id, "level": level, "assistance_level": assistance, "offer_raise_assistance": failed >= 3})
    return result


def create_note(connection, lab, attempt_id):
    previous = connection.execute("SELECT MAX(id) FROM attempt WHERE lab_id = ? AND step_id = 'debrief' AND verdict IS NOT NULL AND id < ?", (lab["id"], attempt_id)).fetchone()[0] or 0
    attempts = connection.execute("SELECT id, hypothesis, raw_output, user_conclusion, revealed_solution, hints_used FROM attempt WHERE lab_id = ? AND id > ? AND id <= ? ORDER BY id", (lab["id"], previous, attempt_id)).fetchall()
    facts = connection.execute("SELECT text FROM observation WHERE attempt_id IN (SELECT id FROM attempt WHERE lab_id = ? AND id > ? AND id <= ?) AND kind = 'fact' ORDER BY id", (lab["id"], previous, attempt_id)).fetchall()
    hypotheses = [row[1] for row in attempts if row[1]]
    outputs = [row[2] for row in attempts if row[2]]
    conclusions = [row[3] for row in attempts if row[3]]
    mistakes = []
    if any(row[4] for row in attempts): mistakes.append("solution раскрыт")
    if any(row[5] >= 3 for row in attempts): mistakes.append("запрошена подсказка 3")
    connection.execute("INSERT INTO note(lab_id, date, goal, hypothesis, commands, results, conclusion, mistakes, learned) VALUES (?, date('now'), ?, ?, ?, ?, ?, ?, ?)", (lab["id"], lab.get("objective", ""), "\n".join(hypotheses), "\n".join(step.get("command", "") for step in lab["steps"] if step.get("command")), "\n".join(outputs + [row[0] for row in facts]), "\n".join(conclusions), "\n".join(mistakes), ""))


def normalize_text(value):
    value = value.casefold().replace("ё", "е")
    words = re.findall(r"[a-zа-я0-9.+/-]+", value)
    endings = ("иями", "ями", "ами", "ого", "ему", "ыми", "ими", "иях",
               "ах", "ях", "ов", "ев", "ом", "ем", "ой", "ей", "ия",
               "ие", "ию", "иям", "ам", "ям", "ы", "и", "а", "я", "е",
               "у", "ю", "о")
    normalized = []
    for word in words:
        if len(word) > 5:
            for ending in endings:
                if word.endswith(ending) and len(word) - len(ending) >= 4:
                    word = word[:-len(ending)]
                    break
        normalized.append(word)
    return " ".join(normalized)


def rubric_match(item, normalized):
    for phrase in item.get("any_of", []):
        phrase_normalized = normalize_text(phrase)
        if phrase_normalized and phrase_normalized in normalized:
            return True
    pattern = item.get("regex")
    return bool(pattern and re.search(pattern, normalized, re.IGNORECASE))


def distractor_as_fact(item, text, normalized, fact_text):
    markers = [normalize_text(marker) for marker in item.get("markers", [])]
    targets = [normalize_text(value) for value in item.get("any_of", [])]
    marker_found = any(marker and marker in normalized for marker in markers)
    target_found = any(target and target in normalized for target in targets)
    unsupported_product = False
    for product in item.get("unsupported_products", []):
        product_normalized = normalize_text(product)
        if product_normalized and product_normalized in normalized and product_normalized not in fact_text:
            unsupported_product = True
    if (marker_found and target_found) or unsupported_product:
        return True
    fact_words = set(fact_text.split())
    assertion_terms = ("веб", "морд", "прилож", "продукт", "дыряв", "слаб",
                       "взлом", "эксплойт", "уязв", "java", "tomcat", "express")
    for sentence in re.split(r"[.!?]+", text):
        sentence_normalized = normalize_text(sentence)
        if not sentence_normalized:
            continue
        sentence_words = set(sentence_normalized.split())
        has_marker = any(marker and marker in sentence_normalized for marker in markers)
        has_assertion = any(term in sentence_normalized for term in assertion_terms)
        has_unknown_claim = any(len(word) > 4 and word not in fact_words for word in sentence_words)
        if has_marker and has_assertion and has_unknown_claim:
            return True
    return False


def score_conclusion(step, text, facts=None):
    normalized = normalize_text(text)
    fact_text = normalize_text(" ".join(fact.get("text", "") for fact in (facts or [])))
    named = [item["label"] for item in step.get("expect", []) if rubric_match(item, normalized)]
    missed = [item["label"] for item in step.get("expect", []) if not rubric_match(item, normalized)]
    flagged = [item["label"] for item in step.get("distractors", []) if distractor_as_fact(item, text, normalized, fact_text)]
    question = step.get("guiding_question") or "Какой факт из твоего вывода подтверждает следующий шаг?"
    return {"named": named, "missed": missed, "flagged_as_fact": flagged, "question": question}


def execution_diagnosis(step, raw, facts):
    """Explain whether Terminal actually ran the requested check.

    The parser deliberately preserves unrecognised lines.  This second layer
    gives a learner an immediate, bounded explanation for common Netcat
    outcomes instead of treating an option error as an empty scan result.
    """
    normalized = raw.lower()
    command = step.get("command", "").splitlines()[-1] or "команду из карточки"
    if "illegal option" in normalized or "unknown option" in normalized or "invalid option" in normalized or "usage: nc" in normalized:
        return {
            "kind": "command_syntax", "level": "error",
            "title": "Команда не выполнила TCP-проверку",
            "message": "Terminal распознал неверный ключ и показал справку. Это ошибка синтаксиса, а не ответ учебного узла.",
            "next": "Сверь регистр каждого ключа и запусти точную строку: %s" % command,
        }
    if "connection refused" in normalized:
        return {
            "kind": "connection_refused", "level": "warning",
            "title": "Узел ответил, но подключение отклонено",
            "message": "Это не доказывает, что узел выключен. TCP-подключение к этому порту было отвергнуто.",
            "next": "Сохрани этот вывод как факт и не называй продукт. Дальше сверяют стенд, адрес и разрешённый порт.",
        }
    if "operation timed out" in normalized or "connection timed out" in normalized:
        return {
            "kind": "timeout", "level": "warning",
            "title": "TCP-подключение не завершилось вовремя",
            "message": "За время ожидания соединение не было установлено. Это не равно ни открытому порту, ни известному продукту.",
            "next": "Сохрани полный вывод и проверь, поднят ли именно учебный стенд, не меняя цель или порт.",
        }
    if "succeeded" in normalized or any(fact.get("kind") == "tcp_connect" for fact in facts):
        return {
            "kind": "tcp_connected", "level": "success",
            "title": "TCP-подключение подтверждено",
            "message": "Netcat смог установить TCP-соединение с указанным адресом и портом.",
            "next": "Это подтверждает достижимость TCP-порта, но ещё не доказывает название приложения, версию или уязвимость.",
        }
    return None


def decision_feedback(step, choice):
    """Explain a branch using this step's own rubric, never a fixed lab text."""
    options = step.get("decision_options", [])
    correct = bool(options) and choice == options[0]
    expected = step.get("expect", [])
    basis = expected[0].get("label") if expected else "наблюдаемые факты"
    if correct:
        why = "Этот вариант сохраняет цель шага: %s." % basis
    else:
        why = "Этот вариант не подтверждает цель шага «%s». Вернитесь к фактам и выберите действие, которое её сохраняет." % basis
    return {"correct": correct, "why": why, "next_step": "debrief" if correct else "analyse"}


def record_check(port, ok, detail):
    with database() as connection:
        connection.execute(
            "INSERT INTO range_check(host, port, ok, detail) VALUES (?, ?, ?, ?)",
            (RANGE_HOST, port, int(ok), detail),
        )


def tcp_check(port):
    try:
        with socket.create_connection((RANGE_HOST, port), timeout=TIMEOUT_SECONDS):
            detail = "TCP connect succeeded"
            record_check(port, True, detail)
            return True, detail
    except OSError as error:
        detail = "TCP connect failed: " + str(error)
        record_check(port, False, detail)
        return False, detail


def http_get(port, path):
    """Perform the explicitly allowed HTTP GET using the already-permitted socket."""
    try:
        with socket.create_connection((RANGE_HOST, port), timeout=TIMEOUT_SECONDS) as connection:
            connection.settimeout(TIMEOUT_SECONDS)
            request = (
                "GET " + path + " HTTP/1.1\r\n"
                "Host: " + RANGE_HOST + ":" + str(port) + "\r\n"
                "Connection: close\r\n\r\n"
            )
            connection.sendall(request.encode("ascii"))
            chunks = []
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(len(part) for part in chunks) > 131072:
                    break
        raw = b"".join(chunks).decode("utf-8", "replace")
        first_line, _, body = raw.partition("\r\n")
        parts = first_line.split()
        status = int(parts[1]) if len(parts) >= 2 and parts[0].startswith("HTTP/") else None
        return status, body, "HTTP " + (str(status) if status is not None else "invalid response")
    except (OSError, ValueError) as error:
        return None, "", "HTTP GET failed: " + str(error)


def health():
    webgoat_tcp, webgoat_tcp_detail = tcp_check(8080)
    juice_tcp, juice_tcp_detail = tcp_check(3000)
    checks = [
        {"service": "WebGoat", "port": 8080, "stage": "tcp", "ok": webgoat_tcp, "detail": webgoat_tcp_detail},
        {"service": "Juice Shop", "port": 3000, "stage": "tcp", "ok": juice_tcp, "detail": juice_tcp_detail},
    ]
    webgoat_http_ok = False
    juice_http_ok = False
    if webgoat_tcp:
        status, _body, detail = http_get(8080, "/WebGoat/")
        webgoat_http_ok = status in (200, 302)
        record_check(8080, webgoat_http_ok, detail)
        checks.append({"service": "WebGoat", "port": 8080, "stage": "http", "path": "/WebGoat/", "status": status, "ok": webgoat_http_ok, "detail": detail})
    else:
        detail = "Skipped because TCP connect failed"
        record_check(8080, False, detail)
        checks.append({"service": "WebGoat", "port": 8080, "stage": "http", "path": "/WebGoat/", "ok": False, "detail": detail})
    if juice_tcp:
        status, body, detail = http_get(3000, "/")
        # Juice Shop's landing HTML should be a real document, not an empty response.
        content_present = "<html" in body.lower() or "juice" in body.lower()
        juice_http_ok = status == 200 and content_present
        suffix = "; content marker present" if content_present else "; expected HTML/Juice Shop content marker missing"
        record_check(3000, juice_http_ok, detail + suffix)
        checks.append({"service": "Juice Shop", "port": 3000, "stage": "http", "path": "/", "status": status, "content_present": content_present, "ok": juice_http_ok, "detail": detail + suffix})
    else:
        detail = "Skipped because TCP connect failed"
        record_check(3000, False, detail)
        checks.append({"service": "Juice Shop", "port": 3000, "stage": "http", "path": "/", "ok": False, "detail": detail})

    diagnosis = []
    if not webgoat_tcp and not juice_tcp:
        diagnosis.append({"level": "error", "message": "Оба порта 8080 и 3000 недоступны: хост выключен, сменил IP или трафик блокирует firewall."})
        diagnosis.append({"level": "action", "message": "Проверьте Windows, текущий IP через ipconfig, правила Windows Firewall и запуск обоих сервисов."})
    elif webgoat_tcp and not juice_tcp:
        diagnosis.append({"level": "error", "message": "Сеть и адрес доступны через WebGoat: конкретно Juice Shop на порту 3000 не отвечает."})
        diagnosis.append({"level": "action", "message": "Перезапустите Juice Shop на Windows и проверьте правило Firewall для TCP 3000."})
    elif not webgoat_tcp and juice_tcp:
        diagnosis.append({"level": "error", "message": "Сеть и адрес доступны через Juice Shop: конкретно WebGoat на порту 8080 не отвечает."})
        diagnosis.append({"level": "action", "message": "Перезапустите WebGoat на Windows и проверьте правило Firewall для TCP 8080."})
    if webgoat_tcp and not webgoat_http_ok:
        diagnosis.append({"level": "error", "message": "Порт 8080 открыт, но WebGoat ответил не ожидаемым HTTP 200 или 302: сервис поднялся не полностью."})
    if juice_tcp and not juice_http_ok:
        diagnosis.append({"level": "error", "message": "Порт 3000 открыт, но Juice Shop не отдал HTTP 200 с ожидаемым содержимым: сервис поднялся не полностью."})
    if webgoat_http_ok and juice_http_ok:
        diagnosis.append({"level": "ok", "message": "WebGoat и Juice Shop отвечают ожидаемым образом."})
    verdict = "ONLINE" if webgoat_http_ok and juice_http_ok else "OFFLINE"
    return {"host": RANGE_HOST, "checks": checks, "verdict": verdict, "diagnosis": diagnosis}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, format, *args):
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), format % args))

    def send_json(self, status, payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def end_headers(self):
        path = urlparse(self.path).path
        if path.endswith((".html", ".js", ".css")) or path == "/":
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON object required")
            return value, None
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return None, "Некорректный JSON: " + str(error)

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parsed_url.query
        params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
        try:
            request_attempt_id = int(params["attempt_id"]) if "attempt_id" in params else None
        except ValueError:
            self.send_json(400, {"error": "Некорректный идентификатор попытки."})
            return
        if path == "/api/range/health":
            self.send_json(200, health())
            return
        if path == "/api/today":
            with database() as connection:
                open_attempt = connection.execute(
                    "SELECT id, lab_id, step_id FROM attempt WHERE verdict IS NULL "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                review = connection.execute("SELECT skill_id, due_date, reason FROM review_queue WHERE due_date <= date('now') ORDER BY due_date LIMIT 1").fetchall()
            if open_attempt:
                lab = load_content("labs", open_attempt[1])
                step_id = open_attempt[2]
                resume = {"attempt_id": open_attempt[0], "step_id": step_id}
            else:
                # Continue in the declared track order.  A closed debrief is
                # the only completion signal, so a browser refresh or an old
                # partial attempt can never silently skip a lab.
                track = load_content("tracks", "track-1-first-contact")
                with database() as connection:
                    completed = {
                        row[0] for row in connection.execute(
                            "SELECT DISTINCT lab_id FROM attempt "
                            "WHERE step_id = 'debrief' AND verdict IS NOT NULL"
                        )
                    }
                next_lab_id = next(
                    (item for item in track.get("lab_ids", []) if item not in completed),
                    track["lab_ids"][-1],
                )
                lab = load_content("labs", next_lab_id)
                step_id = lab["steps"][0]["id"]
                resume = None
            with database() as connection:
                level = connection.execute("SELECT assistance_level FROM skill_progress WHERE skill_id = ?", (lab["skills"][0],)).fetchone()
            self.send_json(200, {"track": lab["track_id"], "lab": lab["id"], "step": step_id, "assistance_level": level[0] if level else 4, "resume": resume, "review_due": [{"skill_id": row[0], "due_date": row[1], "reason": row[2]} for row in review]})
            return
        if path == "/api/progress":
            skills = load_content("skills")
            with database() as connection:
                progress = {row[0]: row[1:] for row in connection.execute("SELECT skill_id, level, assistance_level, next_review FROM skill_progress")}
                total, clean = connection.execute("SELECT COUNT(*), SUM(CASE WHEN hints_used < 2 THEN 1 ELSE 0 END) FROM attempt WHERE verdict IS NOT NULL").fetchone()
            result = []
            for skill in skills:
                level, assistance, next_review = progress.get(skill["id"], (0, 4, None))
                missing = [item["title"] for item in skills if item["id"] in skill.get("prereq_ids", []) and progress.get(item["id"], (0,))[0] < 2]
                result.append({"id": skill["id"], "title": skill["title"], "level": level, "assistance_level": assistance, "next_review": next_review, "available": not missing, "unlock_first": missing})
            self.send_json(200, {"skills": result, "closed_without_hints_2_3": {"closed": total or 0, "without_hints": clean or 0}})
            return
        if path == "/api/notes":
            with database() as connection:
                rows = connection.execute("SELECT id, lab_id, date, goal, hypothesis, commands, results, conclusion, mistakes, learned, manual_paragraph FROM note ORDER BY id DESC").fetchall()
            keys = ("id", "lab_id", "date", "goal", "hypothesis", "commands", "results", "conclusion", "mistakes", "learned", "manual_paragraph")
            self.send_json(200, [dict(zip(keys, row)) for row in rows])
            return
        if path.startswith("/api/lab/"):
            parts = path.split("/")
            lab = load_content("labs", parts[3] if len(parts) > 3 else "")
            if not lab:
                self.send_json(404, {"error": "Лабораторная не найдена"})
            elif len(parts) == 4:
                self.send_json(200, public_lab(lab, request_attempt_id, params.get("reveal")))
            elif len(parts) == 5 and parts[4] == "attempt-context":
                context = attempt_context(lab["id"], request_attempt_id)
                if context is None:
                    self.send_json(404, {"error": "Открытая попытка этой лабораторной не найдена."})
                else:
                    self.send_json(200, context)
            elif len(parts) == 6 and parts[4] == "step":
                _lab, step = find_step(lab["id"], parts[5])
                if step:
                    self.send_json(200, public_step(lab["id"], step, request_attempt_id, params.get("reveal")))
                else:
                    self.send_json(404, {"error": "Шаг не найден"})
            else:
                self.send_json(404, {"error": "Неизвестный маршрут лабы"})
            return
        if path.startswith("/api/hint/"):
            parts = path.split("/")
            try:
                level = int(params.get("level", "0"))
            except ValueError:
                level = 0
            lab_id, step_id = (parts[3], parts[4]) if len(parts) == 5 else (None, None)
            _lab, step = find_step(lab_id, step_id)
            attempt = open_attempt_for_step(lab_id, step_id, request_attempt_id) if step else None
            if not step or not attempt or level not in (1, 2, 3):
                self.send_json(400, {"error": "Нужны существующие попытка, шаг и уровень 1, 2 или 3."})
            else:
                with database() as connection:
                    used = connection.execute("SELECT hints_used FROM attempt WHERE id = ?", (attempt[0],)).fetchone()[0]
                    if level > used + 1:
                        self.send_json(409, {"error": "Сначала запросите предыдущий уровень подсказки."})
                    else:
                        connection.execute("UPDATE attempt SET hints_used = CASE WHEN hints_used < ? THEN ? ELSE hints_used END WHERE id = ?", (level, level, attempt[0]))
                        self.send_json(200, {"level": level, "hint": step["hints"][level - 1]})
            return
        if path.startswith("/api/content/"):
            parts = path.split("/")
            if len(parts) not in (4, 5):
                self.send_json(404, {"error": "Unknown content route"})
                return
            item = load_content(parts[3], parts[4] if len(parts) == 5 else None)
            if item is None:
                self.send_json(404, {"error": "Content item not found"})
            else:
                if parts[3] == "labs":
                    if isinstance(item, list):
                        self.send_json(200, [public_lab(lab, request_attempt_id) for lab in item])
                    else:
                        self.send_json(200, public_lab(item, request_attempt_id))
                else:
                    self.send_json(200, item)
            return
        if path.startswith("/api/"):
            self.send_json(404, {"error": "Unknown API route"})
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        body, error = self.read_json()
        if error:
            self.send_json(400, {"error": error})
            return
        if path == "/api/attempt":
            lab_id, step_id = body.get("lab_id"), body.get("step_id")
            hypothesis = body.get("hypothesis", "")
            continue_attempt_id = body.get("continue_attempt_id")
            _lab, step = find_step(lab_id, step_id)
            if not step:
                self.send_json(404, {"error": "Лабораторная или шаг не найдены."})
            elif not isinstance(hypothesis, str) or not hypothesis.strip():
                self.send_json(400, {"error": "Гипотеза обязательна: напишите, что ожидаете узнать."})
            else:
                with database() as connection:
                    active = connection.execute(
                        "SELECT id, lab_id FROM attempt WHERE verdict IS NULL ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    if continue_attempt_id is None and active:
                        self.send_json(409, {"error": "Сначала продолжите или закройте незавершённую попытку. Новая лабораторная не будет скрывать её журнал."})
                        return
                    if continue_attempt_id is not None:
                        if not isinstance(continue_attempt_id, int) or not active or active[0] != continue_attempt_id or active[1] != lab_id:
                            self.send_json(409, {"error": "Следующий шаг можно создать только из текущей незавершённой попытки этой же лабораторной."})
                            return
                    cursor = connection.execute("INSERT INTO attempt(lab_id, step_id, hypothesis) VALUES (?, ?, ?)", (lab_id, step_id, hypothesis.strip()))
                    attempt_id = cursor.lastrowid
                    connection.execute("INSERT INTO observation(attempt_id, kind, text, source_line) VALUES (?, 'hypothesis', ?, NULL)", (attempt_id, hypothesis.strip()))
                self.send_json(201, {"attempt_id": attempt_id})
            return
        if path.startswith("/api/note/") and path.endswith("/paragraph"):
            try:
                note_id = int(path.split("/")[3])
            except ValueError:
                self.send_json(400, {"error": "Некорректный идентификатор заметки."})
                return
            paragraph = body.get("paragraph", "")
            if not isinstance(paragraph, str):
                self.send_json(400, {"error": "Абзац должен быть текстом."})
                return
            with database() as connection:
                cursor = connection.execute("UPDATE note SET manual_paragraph = ? WHERE id = ?", (paragraph.strip(), note_id))
                if not cursor.rowcount:
                    self.send_json(404, {"error": "Заметка не найдена."})
                else:
                    self.send_json(200, {"id": note_id, "manual_paragraph": paragraph.strip()})
            return
        if path.startswith("/api/skill/") and path.endswith("/raise-assistance"):
            skill_id = path.split("/")[3]
            with database() as connection:
                connection.execute("INSERT INTO skill_progress(skill_id, assistance_level) VALUES (?, 4) ON CONFLICT(skill_id) DO UPDATE SET assistance_level = MIN(4, assistance_level + 1)", (skill_id,))
            self.send_json(200, {"skill_id": skill_id, "raised": True})
            return
        if path.startswith("/api/lab/") and path.endswith("/abandon"):
            parts = path.split("/")
            lab_id = parts[3] if len(parts) == 5 else None
            requested_attempt = body.get("attempt_id")
            if not isinstance(requested_attempt, int) or not load_content("labs", lab_id):
                self.send_json(400, {"error": "Нужны существующие лабораторная и текущая попытка."})
                return
            with database() as connection:
                current = connection.execute(
                    "SELECT id FROM attempt WHERE lab_id = ? AND verdict IS NULL ORDER BY id DESC LIMIT 1", (lab_id,)
                ).fetchone()
                if not current or current[0] != requested_attempt:
                    self.send_json(409, {"error": "Начать заново можно только из текущего незавершённого шага."})
                    return
                previous_closed = connection.execute(
                    "SELECT MAX(id) FROM attempt WHERE lab_id = ? AND verdict IS NOT NULL AND id < ?", (lab_id, requested_attempt)
                ).fetchone()[0] or 0
                cursor = connection.execute(
                    "UPDATE attempt SET verdict = 'abandoned' WHERE lab_id = ? AND id > ? AND verdict IS NULL",
                    (lab_id, previous_closed),
                )
            self.send_json(200, {"abandoned": cursor.rowcount})
            return
        parts = path.split("/")
        if len(parts) < 5 or parts[1:3] != ["api", "attempt"]:
            self.send_json(404, {"error": "Неизвестный API маршрут"})
            return
        try:
            attempt_id = int(parts[3])
        except ValueError:
            self.send_json(400, {"error": "Некорректный идентификатор попытки."})
            return
        action = parts[4]
        with database() as connection:
            attempt = connection.execute("SELECT lab_id, step_id, verdict FROM attempt WHERE id = ?", (attempt_id,)).fetchone()
            if not attempt:
                self.send_json(404, {"error": "Попытка не найдена."})
                return
            _lab, step = find_step(attempt[0], attempt[1])
            if action == "output":
                raw = body.get("raw", "")
                if not isinstance(raw, str) or not raw.strip():
                    self.send_json(400, {"error": "Вставьте непустой вывод команды."})
                    return
                facts, unparsed, parser_name = parse(raw, step.get("parser", "log"))
                connection.execute("UPDATE attempt SET raw_output = ? WHERE id = ?", (raw, attempt_id))
                connection.execute("DELETE FROM observation WHERE attempt_id = ? AND kind = 'fact'", (attempt_id,))
                for fact in facts:
                    connection.execute("INSERT INTO observation(attempt_id, kind, text, source_line) VALUES (?, 'fact', ?, ?)", (attempt_id, fact["text"], fact["line"]))
                self.send_json(200, {
                    "facts": facts, "unparsed": unparsed, "parser": parser_name,
                    "diagnosis": execution_diagnosis(step, raw, facts),
                })
            elif action == "conclusion":
                text = body.get("text", "")
                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"error": "Напишите свой вывод до разбора наставника."})
                    return
                connection.execute("UPDATE attempt SET user_conclusion = ? WHERE id = ?", (text.strip(), attempt_id))
                fact_rows = connection.execute(
                    "SELECT text, source_line FROM observation WHERE attempt_id = ? AND kind = 'fact' ORDER BY id",
                    (attempt_id,),
                ).fetchall()
                facts = [{"text": row[0], "line": row[1]} for row in fact_rows]
                self.send_json(200, score_conclusion(step, text, facts))
            elif action == "solution":
                if body.get("confirm") is not True:
                    self.send_json(400, {"error": "Подтвердите раскрытие solution значением confirm: true."})
                    return
                connection.execute("UPDATE attempt SET revealed_solution = 1 WHERE id = ?", (attempt_id,))
                self.send_json(200, {"solution": step.get("solution", ""), "revealed_solution": 1})
            elif action == "decision":
                choice = body.get("choice")
                options = step.get("decision_options", [])
                if choice not in options:
                    self.send_json(400, {"error": "Выберите один из вариантов этого шага."})
                    return
                connection.execute("UPDATE attempt SET decision_choice = ? WHERE id = ?", (choice, attempt_id))
                self.send_json(200, decision_feedback(step, choice))
            elif action == "debrief":
                if attempt[2] is not None:
                    self.send_json(409, {"error": "Шаг уже закрыт и неизменяем."})
                    return
                verdict = body.get("verdict", "completed")
                lab = load_content("labs", attempt[0])
                previous_closed = connection.execute(
                    "SELECT MAX(id) FROM attempt WHERE lab_id = ? AND verdict IS NOT NULL AND id < ?",
                    (attempt[0], attempt_id),
                ).fetchone()[0] or 0
                connection.execute("UPDATE attempt SET verdict = ? WHERE id = ?", (verdict, attempt_id))
                create_note(connection, lab, attempt_id)
                learning = close_learning(connection, lab, attempt_id)
                # One learning run contains one attempt per phase.  Leaving
                # earlier phases open made Today hide them behind the last id
                # and blocked every later lab after a seemingly closed debrief.
                connection.execute(
                    "UPDATE attempt SET verdict = ? WHERE lab_id = ? AND id > ? "
                    "AND id < ? AND verdict IS NULL",
                    (verdict, attempt[0], previous_closed, attempt_id),
                )
                self.send_json(200, {"verdict": verdict, "closed": True, "learning": learning})
            else:
                self.send_json(404, {"error": "Неизвестное действие попытки."})


def main():
    database().close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Cyber Range Coach listening on http://%s:%d/" % (HOST, PORT), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
