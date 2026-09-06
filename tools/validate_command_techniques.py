#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from cyber_range_coach.services.command_practice import COMMAND_LEAD, CommandCatalog

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    errors: list[str] = []
    try:
        catalog = CommandCatalog(ROOT / "curriculum" / "commands")
    except (OSError, ValueError) as error:
        print("COMMAND CONTENT VALIDATION FAILED")
        print(f"- {error}")
        return 1
    coverage_refs = {
        (item.source, item.address): item
        for item in catalog.coverage
    }
    for technique in catalog.techniques.values():
        for ref in technique.source_refs:
            coverage = coverage_refs.get((ref.source, ref.address))
            if coverage is None:
                errors.append(f"{technique.id}: source reference is not covered")
            elif technique.id not in coverage.technique_ids:
                errors.append(f"{technique.id}: source coverage does not point back to technique")
        challenge = catalog.challenges[technique.id]
        visible_strings = [
            technique.purpose,
            technique.typical_error,
            technique.mnemonic_image,
            challenge.prompt,
            challenge.observation.prompt,
            challenge.observation.sample_answer,
            *(hint.text for hint in challenge.hints),
        ]
        if any("—" in value for value in visible_strings):
            errors.append(f"{technique.id}: user-facing text contains an em dash")
        if challenge.recall.accepted_answers[0] in challenge.prompt:
            errors.append(f"{challenge.id}: prompt reveals the full answer")
        if not challenge.context.named_inputs or not challenge.context.constraints:
            errors.append(f"{challenge.id}: public context is incomplete")
        if challenge.context.shell != challenge.recall.shell:
            errors.append(f"{challenge.id}: context shell does not match recall shell")
        if not challenge.answer_fields:
            errors.append(f"{challenge.id}: public answer contract is empty")
        if not challenge.observation.example_output or not challenge.observation.fields:
            errors.append(f"{challenge.id}: structured observation contract is incomplete")
        if technique.shell == "bash" and challenge.recall.comparison_mode not in {
            "exact",
            "exact_or_permuted",
        }:
            errors.append(f"{challenge.id}: bash comparison mode is not declared")
    if any(source.embedded_images for source in catalog.sources):
        errors.append("mnemonic source list unexpectedly contains embedded images")
    for technique in catalog.techniques.values():
        if technique.shell == "cmd" and any(
            flag.startswith("-") for flag in technique.significant_flags
        ):
            errors.append(f"{technique.id}: cmd.exe switches start with a slash")
        if technique.shell == "bash" and any(
            flag.startswith("/") for flag in technique.significant_flags
        ):
            errors.append(f"{technique.id}: bash flags do not start with a slash")
    if errors:
        print("COMMAND CONTENT VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    statuses: dict[str, int] = {}
    for item in catalog.coverage:
        statuses[item.status] = statuses.get(item.status, 0) + 1
    print("COMMAND CONTENT VALIDATION PASSED")
    print(f"techniques: {len(catalog.techniques)}")
    print(f"challenges: {len(catalog.challenges)}")
    print(f"source blocks covered: {len(catalog.coverage)}")
    print("coverage statuses: " + ", ".join(f"{key}={value}" for key, value in statuses.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
