#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from cyber_range_coach.services.command_practice import CommandCatalog
from cyber_range_coach.services.missions import MissionCatalog

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        commands = CommandCatalog(ROOT / "curriculum" / "commands")
        catalog = MissionCatalog(ROOT / "curriculum" / "missions", commands)
    except (OSError, ValueError) as error:
        print("MISSION CONTENT VALIDATION FAILED")
        print(f"- {error}")
        return 1
    errors: list[str] = []
    for mission in catalog.missions.values():
        visible_strings = [
            mission.title,
            mission.story,
            mission.allowed_environment,
            mission.prepared_data_description,
            mission.final_artifact_prompt,
            mission.explanation_prompt,
            mission.variant_rule,
            *mission.required_actions,
        ]
        if any("—" in value for value in visible_strings):
            errors.append(f"{mission.id}: user-facing text contains an em dash")
        if not mission.requires_free_text:
            errors.append(f"{mission.id}: mission must require a free-text response")
        for variant in mission.variants:
            if not variant.grading.artifact.accepted_values:
                errors.append(f"{mission.id}/{variant.id}: artifact contract is empty")
            if not variant.grading.facts:
                errors.append(f"{mission.id}/{variant.id}: structured fact contract is empty")
            field_ids = [field.id for field in variant.grading.facts]
            if len(field_ids) != len(set(field_ids)):
                errors.append(f"{mission.id}/{variant.id}: structured fact ids are not unique")
            if any("—" in entry.content for entry in variant.prepared_data):
                errors.append(f"{mission.id}/{variant.id}: prepared data contains an em dash")
    if errors:
        print("MISSION CONTENT VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("MISSION CONTENT VALIDATION PASSED")
    print(f"missions: {len(catalog.missions)}")
    print("variants: " + str(sum(len(mission.variants) for mission in catalog.missions.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
