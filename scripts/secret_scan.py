from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_SUFFIXES = {
    ".db",
    ".docx",
    ".exe",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".pyc",
    ".sqlite",
    ".tif",
    ".tiff",
    ".woff",
    ".woff2",
}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{30,}\b"),
    "openai_key": re.compile(r"\bs[kK]-[A-Za-z0-9_-]{32,}\b"),
    "jwt": re.compile(r"\b[eE][yY][jJ][A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
}


def candidate_files() -> list[Path]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable is required for the repository secret scan")
    result = subprocess.run(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    findings: list[str] = []
    for path in candidate_files():
        relative = path.relative_to(ROOT)
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        if relative.name == ".env" or relative.name.startswith(".env."):
            findings.append(f"tracked environment file: {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in PATTERNS.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{name}: {relative}:{line}")
    if findings:
        print("Проверка секретов не пройдена:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Проверка секретов пройдена: приватные ключи и известные форматы токенов не найдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
