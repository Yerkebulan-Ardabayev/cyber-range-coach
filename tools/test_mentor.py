#!/usr/bin/env python3
"""Acceptance tests for mentor feedback on realistic, incomplete learner text."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server import score_conclusion

CASES = [
    ("lab-1-1-scope-reachability", "Пинг проходит, а TCP подключение к 8080 succeeded. Это два способа, значит веб-приложение точно работает.", [{"text": "64 bytes from 192.168.10.10"}, {"text": "Connection to 192.168.10.10 port 8080 succeeded"}]),
    ("lab-1-2-service-enumeration", "Открыто два порта, 8080 и 3000, на обоих http. Раз это Tomcat, приложение точно на Java и его наверняка можно сломать.", [{"text": "8080/tcp"}, {"text": "open"}, {"text": "http"}, {"text": "Apache Tomcat 10.x"}, {"text": "3000/tcp"}]),
    ("lab-1-3-http-protocol", "Получен HTTP 302 и Location ведёт на страницу логина. Значит веб-приложение точно сломано.", [{"text": "HTTP/1.1 302 Found"}, {"text": "Location: /WebGoat/login"}]),
    ("lab-1-4-attack-surface", "В Network есть URL /api/Users, метод GET и код 200. Это очевидно уязвимый endpoint.", [{"text": "GET /api/Users HTTP/1.1"}, {"text": "HTTP/1.1 200 OK"}]),
    ("lab-1-5-authentication-boundary", "Вижу 302 и заголовок Set-Cookie, потом 401. 401 точно означает, что у моей роли нет прав.", [{"text": "HTTP/1.1 302 Found"}, {"text": "Set-Cookie: JSESSIONID=redacted"}, {"text": "HTTP/1.1 401 Unauthorized"}]),
    ("lab-1-6-access-control", "Вторая учётка запросила object id 7, сервер вернул данные в ответе. Значит веб-приложение точно дырявое.", [{"text": "GET /api/item/7 HTTP/1.1"}, {"text": "HTTP/1.1 200 OK"}, {"text": "object data"}]),
    ("lab-1-7-blue-auth-events", "Есть несколько 401 от одного IP, но время и учётка не записаны. Это точно взлом, надо сразу блокировать.", [{"text": "HTTP/1.1 401 Unauthorized"}, {"text": "source=192.168.10.20"}]),
]


def main():
    failed = False
    for lab_id, text, facts in CASES:
        with (ROOT / "content/labs" / (lab_id + ".json")).open(encoding="utf-8") as source:
            lab = json.load(source)
        step = next(item for item in lab["steps"] if item["id"] == "analyse")
        result = score_conclusion(step, text, facts)
        print(lab_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["named"] or not result["missed"] or not result["flagged_as_fact"]:
            print("FAILED: expected non-empty named, missed and flagged_as_fact", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
