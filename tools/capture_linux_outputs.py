"""Capture or verify real Bash outputs for the command catalog.

Each technique in curriculum/output-fixtures/linux.yaml describes how to
prepare synthetic training data in a disposable reference Linux container.
The tool runs the accepted answer as the normal user ``student`` and renders a
terminal transcript (prompt, command, output). Nothing runs on the host.

    capture_linux_outputs.py --capture linux-pwd-current-directory
    capture_linux_outputs.py --check
"""

from __future__ import annotations

import argparse
import base64
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "curriculum" / "commands" / "linux-techniques.yaml"
FIXTURES = ROOT / "curriculum" / "output-fixtures" / "linux.yaml"
DEFAULT_IMAGE = "cyber-range-coach-reference:24.04"
PLACEHOLDER_MARKERS = ("SYNTHETIC RESULT", "observed_")
# Working files live only inside the disposable container.
WORK = "/opt/crc-capture"

BOOTSTRAP = """set -eu
if id ubuntu >/dev/null 2>&1; then userdel -r ubuntu >/dev/null 2>&1 || true; fi
id student >/dev/null 2>&1 || useradd -m -u 1000 -s /bin/bash student
install -d -o student -g student /home/student/training
install -d -m 755 /opt/crc-capture
cd /home/student/training
"""

PROMPT = r"""__crc_prompt() {
  local d="${PWD/#$HOME/\~}"
  printf '%s@%s:%s$ %s\n' "$(id -un)" "$(hostname)" "$d" "$1"
}
"""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _write(path: str, text: str) -> str:
    return f"printf %s {_b64(text)} | base64 -d > {path}\n"


def build_script(challenge: dict, fixture: dict) -> str:
    context = challenge["context"]
    workdir = context.get("working_directory") or "/home/student/training"
    shown = challenge["recall"]["accepted_answers"][0]
    steps = [(shown, fixture.get("run") or shown)]
    for follow in fixture.get("followups") or []:
        steps.append((follow, follow))
    student = ["export TZ=Asia/Almaty LANG=C.UTF-8", f"cd {shlex.quote(workdir)}"]
    student += ["{", fixture.get("prelude") or ":", "} >/dev/null 2>&1"]
    student.append(PROMPT)
    stdin = fixture.get("stdin")
    for index, (display, _command) in enumerate(steps):
        student.append(f"__crc_prompt {shlex.quote(display)}")
        redirect = f" < {WORK}/stdin" if stdin is not None and index == 0 else ""
        student.append(f". {WORK}/step-{index}.sh 2>&1{redirect}")
    script = BOOTSTRAP + (fixture.get("setup") or "") + "\n"
    script += "chmod 755 /home/student\n"
    for index, (_display, command) in enumerate(steps):
        script += _write(f"{WORK}/step-{index}.sh", command + "\n")
    if stdin is not None:
        script += _write(f"{WORK}/stdin", stdin)
    script += _write(f"{WORK}/student.sh", "\n".join(student) + "\n")
    script += f"chmod 644 {WORK}/*\n"
    script += f"su - student -c 'bash {WORK}/student.sh'\n"
    return script


def run_fixture(challenge: dict, fixture: dict, image: str) -> str:
    command = ["docker", "run", "--rm", "-i", "--hostname", "training-vm", "-e", "TZ=Asia/Almaty"]
    if fixture.get("privileged"):
        command.append("--privileged")
    command += ["--entrypoint", "bash", image, "-s"]
    completed = subprocess.run(
        command,
        input=build_script(challenge, fixture),
        capture_output=True,
        text=True,
        timeout=int(fixture.get("timeout", 60)),
        check=False,
    )
    output = completed.stdout.replace("\r", "")
    if completed.returncode != 0 and not output.strip():
        raise RuntimeError(completed.stderr.strip() or f"exit {completed.returncode}")
    return "\n".join(line.rstrip() for line in output.rstrip("\n").split("\n"))


def load() -> tuple[dict, dict]:
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    fixtures = yaml.safe_load(FIXTURES.read_text(encoding="utf-8")) if FIXTURES.exists() else {}
    challenges = {item["technique_id"]: item for item in catalog["challenges"]}
    return challenges, (fixtures or {}).get("fixtures", {})


def check(image: str, only: list[str]) -> int:
    challenges, fixtures = load()
    errors: list[str] = []
    for technique_id, challenge in challenges.items():
        if only and technique_id not in only:
            continue
        observation = challenge["observation"]
        stored = observation["example_output"]
        if any(marker in stored for marker in PLACEHOLDER_MARKERS):
            errors.append(f"{technique_id}: placeholder example output")
            continue
        fixture = fixtures.get(technique_id)
        if fixture is None:
            errors.append(f"{technique_id}: no fixture")
            continue
        for field in observation["fields"]:
            if not any(value.casefold() in stored.casefold() for value in field["accepted_values"]):
                errors.append(f"{technique_id}: field {field['id']} value is absent from example output")
        try:
            fresh = run_fixture(challenge, fixture, image)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{technique_id}: run failed: {exc}")
            continue
        if fixture.get("volatile"):
            # Values listed in volatile_fields change between runs (memory,
            # disk, PID); the learner reads them from the stored example.
            changing = set(fixture.get("volatile_fields") or [])
            for field in observation["fields"]:
                if field["id"] in changing:
                    continue
                if not any(value.casefold() in fresh.casefold() for value in field["accepted_values"]):
                    errors.append(f"{technique_id}: volatile field {field['id']} absent from fresh output")
        elif fresh != stored.rstrip("\n"):
            errors.append(f"{technique_id}: fresh output differs from stored example")
    for message in errors:
        print(message)
    print("LINUX OUTPUTS " + ("FAILED" if errors else "PASSED"))
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--capture", nargs="*", help="print transcripts for these techniques")
    parser.add_argument("--fixtures", type=Path, help="alternative fixtures file for authoring")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    if args.fixtures:
        global FIXTURES
        FIXTURES = args.fixtures
    if args.check:
        return check(args.image, args.only)
    challenges, fixtures = load()
    for technique_id in args.capture or []:
        fixture = fixtures.get(technique_id, {})
        print(f"===== {technique_id}")
        print(run_fixture(challenges[technique_id], fixture, args.image))
    return 0


if __name__ == "__main__":
    sys.exit(main())
