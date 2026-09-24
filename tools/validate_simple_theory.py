#!/usr/bin/env python3
"""Check the child-level theory blocks of the base course (spec.md 11.3 Г)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from cyber_range_coach.services.simple_theory import SimpleTheory, simplicity_errors

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-all", action="store_true", help="every lesson must have theory")
    args = parser.parse_args()
    lessons = yaml.safe_load((ROOT / "curriculum" / "fundamentals.yaml").read_text(encoding="utf-8"))["lessons"]
    errors: list[str] = []
    covered = 0
    for lesson in lessons:
        raw = lesson.get("simple_theory")
        if raw is None:
            if args.require_all:
                errors.append(f"{lesson['id']}: simple_theory is missing")
            continue
        covered += 1
        errors += [f"{lesson['id']}: {error}" for error in simplicity_errors(SimpleTheory(**raw))]
    if errors:
        print("SIMPLE THEORY VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("SIMPLE THEORY VALIDATION PASSED")
    print(f"lessons with simple theory: {covered}/{len(lessons)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
