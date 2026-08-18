"""Literal-only parsers for output pasted by the learner.

They do not execute commands, contact targets, or infer facts absent from text.
"""
import re


NMAP_SERVICE = re.compile(r"^(\d+)/(tcp|udp)\s+(\S+)\s+(\S+)(?:\s+(.*\S))?$")
HTTP_STATUS = re.compile(r"^HTTP/\d(?:\.\d)?\s+(\d{3})(?:\s+(.*))?$")
HTTP_HEADER = re.compile(r"^([!#$%&'*+\-.^_`|~0-9A-Za-z]+):\s*(.*)$")


def parse_nmap(raw):
    facts, unparsed = [], []
    for number, line in enumerate(raw.splitlines(), 1):
        match = NMAP_SERVICE.match(line)
        if match:
            port, protocol, state, service, version = match.groups()
            facts.append({"line": number, "kind": "port", "text": port + "/" + protocol})
            facts.append({"line": number, "kind": "state", "text": state})
            facts.append({"line": number, "kind": "service", "text": service})
            if version:
                facts.append({"line": number, "kind": "version", "text": version})
        else:
            unparsed.append({"line": number, "text": line})
    return facts, unparsed, "nmap-sV"


def parse_http(raw):
    facts, unparsed = [], []
    for number, line in enumerate(raw.splitlines(), 1):
        status = HTTP_STATUS.match(line)
        header = HTTP_HEADER.match(line)
        if status:
            code, reason = status.groups()
            facts.append({"line": number, "kind": "http_status", "text": code + (" " + reason if reason else "")})
        elif header:
            name, value = header.groups()
            facts.append({"line": number, "kind": "header", "text": name + ": " + value})
        else:
            unparsed.append({"line": number, "text": line})
    return facts, unparsed, "http"


def parse_log(raw):
    facts, unparsed = [], []
    for number, line in enumerate(raw.splitlines(), 1):
        if line.strip():
            facts.append({"line": number, "kind": "log", "text": line})
        else:
            unparsed.append({"line": number, "text": line})
    return facts, unparsed, "log"


def parse(raw, parser_name):
    if parser_name == "nmap":
        return parse_nmap(raw)
    if parser_name in ("curl", "http"):
        return parse_http(raw)
    return parse_log(raw)
