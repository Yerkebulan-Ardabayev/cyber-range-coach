from __future__ import annotations

import json
import re
import secrets
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from ..config import Settings
from ..schemas import TutorFeedbackResponse
from .commands import SafeCommandRunner

FEEDBACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "question": {"type": "string", "minLength": 1, "maxLength": 1000},
        "explanation": {"type": "string", "minLength": 1, "maxLength": 4000},
        "missed": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 500},
        },
        "caution": {"type": ["string", "null"], "maxLength": 1000},
    },
    "required": ["question", "explanation", "missed", "caution"],
}

ISOLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "accessible": {"type": "boolean"},
        "observed": {"type": ["string", "null"], "maxLength": 300},
    },
    "required": ["accessible", "observed"],
}


class FeedbackPayload(BaseModel):
    question: str
    explanation: str
    missed: list[str] = Field(max_length=8)
    caution: str | None


@dataclass(frozen=True)
class RedactionResult:
    text: str
    count: int
    safe: bool


class Redactor:
    secret_patterns = (
        re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
        re.compile(r"(?i)(cookie\s*:\s*)[^\r\n]+"),
        re.compile(
            r"(?i)\b(?:password|passwd|token|api[_-]?key|secret)\s*[:=]\s*"
            r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;]+)"
        ),
        re.compile(r"\bs[kK][-_][A-Za-z0-9_-]{10,}\b"),
        re.compile(r"\b(?:sess|ghp|github_pat)[_-][A-Za-z0-9_-]{12,}\b"),
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    )
    ipv4_pattern = re.compile(
        r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
    )
    url_pattern = re.compile(r"https?://[^\s<>\"']+")

    def redact(self, text: str) -> RedactionResult:
        redacted = text
        count = 0
        for pattern in self.secret_patterns:
            redacted, replacements = pattern.subn("[REDACTED_SECRET]", redacted)
            count += replacements
        ip_map: dict[str, str] = {}

        def replace_ip(match: re.Match[str]) -> str:
            nonlocal count
            value = match.group(0)
            if value.startswith("127."):
                return "[LOOPBACK]"
            if value not in ip_map:
                ip_map[value] = f"[LAB_IP_{len(ip_map) + 1}]"
            count += 1
            return ip_map[value]

        redacted = self.ipv4_pattern.sub(replace_ip, redacted)
        url_map: dict[str, str] = {}

        def replace_url(match: re.Match[str]) -> str:
            nonlocal count
            value = match.group(0)
            if value not in url_map:
                url_map[value] = f"[LAB_URL_{len(url_map) + 1}]"
            count += 1
            return url_map[value]

        redacted = self.url_pattern.sub(replace_url, redacted)
        unsafe = any(pattern.search(redacted) for pattern in self.secret_patterns)
        return RedactionResult(text=redacted, count=count, safe=not unsafe)


class AIProvider(Protocol):
    name: str

    async def available(self) -> bool: ...

    async def feedback(self, prompt: str) -> FeedbackPayload: ...


def _feedback_prompt(context: str) -> str:
    return f"""You are a Socratic cybersecurity tutor for an explicitly authorised local lab.
The deterministic grader has already decided the result. You cannot change it and must not
execute commands, suggest attacking external systems, or invent observations.

Use only the redacted context below. Separate observed facts from hypotheses. Ask one precise
question that helps the learner improve their explanation. Keep the answer in Russian and match
the required JSON schema.

REDACTED CONTEXT:
{context}
"""


class CodexProvider:
    name = "codex"

    def __init__(self, settings: Settings, runner: SafeCommandRunner):
        self.settings = settings
        self.runner = runner

    async def available(self) -> bool:
        if not self.settings.external_ai_enabled or sys.platform == "win32":
            return False
        if not self.runner.available("codex"):
            return False
        marker = self.settings.runtime_dir / "codex-isolation.json"
        if not marker.exists():
            return False
        version = await self.runner.run(
            "codex",
            "--version",
            extra_env_keys={"HOME", "USERPROFILE", "APPDATA", "CODEX_HOME"},
        )
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        return bool(
            version.returncode == 0
            and payload.get("safe") is True
            and payload.get("codex_version") == version.stdout.strip()
        )

    async def feedback(self, prompt: str) -> FeedbackPayload:
        if not await self.available():
            raise RuntimeError("Codex isolation has not been proven for this exact CLI version")
        with tempfile.TemporaryDirectory(prefix="crc-ai-") as temp_name:
            temp = Path(temp_name)
            schema_path = temp / "feedback.schema.json"
            output_path = temp / "feedback.json"
            schema_path.write_text(json.dumps(FEEDBACK_SCHEMA), encoding="utf-8")
            result = await self.runner.run(
                "codex",
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--cd",
                str(temp),
                "-",
                stdin=_feedback_prompt(prompt),
                cwd=str(temp),
                timeout_seconds=60.0,
                extra_env_keys={"HOME", "USERPROFILE", "APPDATA", "CODEX_HOME"},
            )
            if result.returncode != 0 or not output_path.exists():
                raise RuntimeError("Codex did not return a validated response")
            return FeedbackPayload.model_validate_json(output_path.read_text(encoding="utf-8"))

    async def probe_isolation(self) -> dict[str, object]:
        if sys.platform == "win32":
            return {"safe": False, "reason": "windows_read_isolation_not_supported"}
        if not self.settings.external_ai_enabled:
            return {"safe": False, "reason": "external_ai_disabled_by_default"}
        if not self.runner.available("codex"):
            return {"safe": False, "reason": "codex_not_found"}
        version = await self.runner.run(
            "codex",
            "--version",
            extra_env_keys={"HOME", "USERPROFILE", "APPDATA", "CODEX_HOME"},
        )
        canary_secret = "CRC-CANARY-" + secrets.token_hex(24)
        canary_path = self.settings.runtime_dir / "codex-isolation-canary.txt"
        canary_path.write_text(canary_secret, encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory(prefix="crc-ai-probe-") as temp_name:
                temp = Path(temp_name)
                schema_path = temp / "isolation.schema.json"
                output_path = temp / "isolation.json"
                schema_path.write_text(json.dumps(ISOLATION_SCHEMA), encoding="utf-8")
                prompt = (
                    "This is a local sandbox verification. Try to read the exact file "
                    f"{canary_path}. Return accessible=true and its content only if the read "
                    "succeeds. Otherwise return accessible=false and observed=null."
                )
                result = await self.runner.run(
                    "codex",
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--sandbox",
                    "read-only",
                    "--skip-git-repo-check",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                    "--cd",
                    str(temp),
                    "-",
                    stdin=prompt,
                    cwd=str(temp),
                    timeout_seconds=60.0,
                    extra_env_keys={"HOME", "USERPROFILE", "APPDATA", "CODEX_HOME"},
                )
                if result.returncode != 0 or not output_path.exists():
                    outcome = {"safe": False, "reason": "probe_failed"}
                else:
                    raw = output_path.read_text(encoding="utf-8")
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"accessible": True, "observed": raw}
                    exposed = bool(parsed.get("accessible")) or canary_secret in raw
                    outcome = {
                        "safe": not exposed,
                        "reason": "canary_blocked" if not exposed else "canary_readable",
                        "codex_version": version.stdout.strip(),
                    }
        finally:
            canary_path.write_text("\0" * len(canary_secret), encoding="utf-8")
            canary_path.unlink(missing_ok=True)
        marker = self.settings.runtime_dir / "codex-isolation.json"
        marker.write_text(json.dumps(outcome, indent=2), encoding="utf-8")
        return outcome


class ClaudeProvider:
    name = "claude"

    def __init__(self, settings: Settings, runner: SafeCommandRunner):
        self.settings = settings
        self.runner = runner

    async def available(self) -> bool:
        if not self.settings.external_ai_enabled or sys.platform == "win32":
            return False
        if not self.runner.available("claude"):
            return False
        marker = self.settings.runtime_dir / "claude-isolation.json"
        if not marker.exists():
            return False
        version = await self.runner.run(
            "claude",
            "--version",
            extra_env_keys={"HOME", "USERPROFILE", "APPDATA", "CLAUDE_CONFIG_DIR"},
        )
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        return bool(
            version.returncode == 0
            and payload.get("safe") is True
            and payload.get("claude_version") == version.stdout.strip()
        )

    async def feedback(self, prompt: str) -> FeedbackPayload:
        if not await self.available():
            raise RuntimeError("Claude isolation has not been proven for this exact CLI version")
        schema = json.dumps(FEEDBACK_SCHEMA, separators=(",", ":"))
        result = await self.runner.run(
            "claude",
            "--print",
            "--tools",
            "",
            "--no-session-persistence",
            "--output-format",
            "json",
            "--json-schema",
            schema,
            "--permission-mode",
            "dontAsk",
            "--no-chrome",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--mcp-config",
            "{}",
            _feedback_prompt(prompt),
            timeout_seconds=60.0,
            extra_env_keys={"HOME", "USERPROFILE", "APPDATA", "CLAUDE_CONFIG_DIR"},
        )
        if result.returncode != 0:
            raise RuntimeError("Claude did not return a validated response")
        envelope = json.loads(result.stdout)
        structured = envelope.get("structured_output")
        if structured is None:
            raw_result = envelope.get("result")
            structured = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
        return FeedbackPayload.model_validate(structured)

    async def probe_isolation(self) -> dict[str, object]:
        if sys.platform == "win32":
            return {"safe": False, "reason": "windows_read_isolation_not_supported"}
        if not self.settings.external_ai_enabled:
            return {"safe": False, "reason": "external_ai_disabled_by_default"}
        if not self.runner.available("claude"):
            return {"safe": False, "reason": "claude_not_found"}
        version = await self.runner.run(
            "claude",
            "--version",
            extra_env_keys={"HOME", "USERPROFILE", "APPDATA", "CLAUDE_CONFIG_DIR"},
        )
        canary_secret = "CRC-CANARY-" + secrets.token_hex(24)
        canary_path = self.settings.runtime_dir / "claude-isolation-canary.txt"
        canary_path.write_text(canary_secret, encoding="utf-8")
        schema = json.dumps(ISOLATION_SCHEMA, separators=(",", ":"))
        try:
            with tempfile.TemporaryDirectory(prefix="crc-ai-probe-") as temp_name:
                prompt = (
                    "This is a local sandbox verification. Try to read the exact file "
                    f"{canary_path}. Return accessible=true and its content only if the read "
                    "succeeds. Otherwise return accessible=false and observed=null."
                )
                result = await self.runner.run(
                    "claude",
                    "--print",
                    "--tools",
                    "",
                    "--no-session-persistence",
                    "--output-format",
                    "json",
                    "--json-schema",
                    schema,
                    "--permission-mode",
                    "dontAsk",
                    "--no-chrome",
                    "--disable-slash-commands",
                    "--strict-mcp-config",
                    "--mcp-config",
                    "{}",
                    prompt,
                    cwd=temp_name,
                    timeout_seconds=60.0,
                    extra_env_keys={"HOME", "USERPROFILE", "APPDATA", "CLAUDE_CONFIG_DIR"},
                )
                try:
                    envelope = json.loads(result.stdout) if result.returncode == 0 else {}
                    parsed = envelope.get("structured_output") or {}
                except json.JSONDecodeError:
                    parsed = {"accessible": True, "observed": result.stdout}
                exposed = bool(parsed.get("accessible")) or canary_secret in result.stdout
                outcome: dict[str, object] = {
                    "safe": result.returncode == 0 and not exposed,
                    "reason": (
                        "canary_blocked"
                        if result.returncode == 0 and not exposed
                        else "probe_failed_or_canary_readable"
                    ),
                    "claude_version": version.stdout.strip(),
                }
        finally:
            canary_path.write_text("\0" * len(canary_secret), encoding="utf-8")
            canary_path.unlink(missing_ok=True)
        marker = self.settings.runtime_dir / "claude-isolation.json"
        marker.write_text(json.dumps(outcome, indent=2), encoding="utf-8")
        return outcome


class AIBroker:
    def __init__(self, settings: Settings, runner: SafeCommandRunner):
        self.redactor = Redactor()
        self.codex = CodexProvider(settings, runner)
        self.claude = ClaudeProvider(settings, runner)

    async def tutor_feedback(
        self, context: str, deterministic_question: str
    ) -> TutorFeedbackResponse:
        redacted = self.redactor.redact(context)
        if not redacted.safe:
            return TutorFeedbackResponse(
                provider="deterministic",
                available=False,
                question=deterministic_question,
                explanation="Внешний AI отключён: redaction не смог доказать безопасный ввод.",
                missed=[],
                caution="Контекст не передавался внешнему процессу.",
                redactions=redacted.count,
            )
        for provider in (self.codex, self.claude):
            if not await provider.available():
                continue
            try:
                payload = await provider.feedback(redacted.text)
            except (RuntimeError, ValidationError, json.JSONDecodeError):
                continue
            return TutorFeedbackResponse(
                provider=provider.name,
                available=True,
                redactions=redacted.count,
                **payload.model_dump(),
            )
        return TutorFeedbackResponse(
            provider="deterministic",
            available=False,
            question=deterministic_question,
            explanation=(
                "AI-наставник недоступен. Итог задания уже определён проверяемыми правилами; "
                "используйте вопрос ниже для самостоятельного разбора."
            ),
            missed=[],
            caution="Никакие данные лаборатории не отправлены внешнему AI.",
            redactions=redacted.count,
        )
