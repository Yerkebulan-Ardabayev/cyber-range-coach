#!/usr/bin/env python3
"""Validate the versioned Cyber Range Coach content without dependencies."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
CATEGORIES = ("tracks", "skills", "labs", "playbooks", "commands", "glossary")
STEP_REQUIRED = {"id", "kind", "prompt", "why", "distractors", "parser", "solution"}
VALID_STEP_KINDS = {"think", "execute", "analyse", "decide", "debrief"}


def validate_rubric_items(items, field, path, errors):
    if not isinstance(items, list) or not items:
        errors.append("%s: %s must be a non-empty list" % (path, field))
        return
    for item in items:
        if not isinstance(item, dict):
            errors.append("%s: %s item must be an object" % (path, field))
            continue
        required = {"id", "label"}
        if field == "expect":
            required.add("any_of")
        else:
            required.update({"markers", "any_of"})
        for key in required:
            if key not in item or not item[key]:
                errors.append("%s: %s item needs non-empty %r" % (path, field, key))
        for list_key in ("any_of", "markers", "unsupported_products"):
            if list_key in item and (not isinstance(item[list_key], list) or not all(isinstance(value, str) and value.strip() for value in item[list_key])):
                errors.append("%s: %s item field %r must be a list of non-empty strings" % (path, field, list_key))
        if "regex" in item and not isinstance(item["regex"], str):
            errors.append("%s: %s item regex must be a string" % (path, field))


def load_category(name, errors):
    result = []
    paths = sorted((CONTENT / name).glob("*.json"))
    if not paths:
        errors.append("content/%s has no JSON files" % name)
    for path in paths:
        try:
            with path.open(encoding="utf-8") as file:
                value = json.load(file)
            if not isinstance(value, dict):
                errors.append("%s: root must be an object" % path.relative_to(ROOT))
            else:
                value["__path"] = path
                result.append(value)
        except (OSError, json.JSONDecodeError) as error:
            errors.append("%s: %s" % (path.relative_to(ROOT), error))
    return result


def need(item, fields, errors, allow_empty=False):
    path = item["__path"].relative_to(ROOT)
    for field in fields:
        if field not in item or item[field] is None or (not allow_empty and item[field] == ""):
            errors.append("%s: required field %r is missing" % (path, field))


def main():
    errors = []
    data = {category: load_category(category, errors) for category in CATEGORIES}
    ids = {category: {item.get("id") for item in items if item.get("id")} for category, items in data.items()}
    for category, items in data.items():
        seen = set()
        for item in items:
            identifier = item.get("term") if category == "glossary" else item.get("id")
            if not identifier:
                errors.append("%s: required identifier is missing" % item["__path"].relative_to(ROOT))
            if identifier in seen:
                errors.append("%s: duplicate identifier %r" % (item["__path"].relative_to(ROOT), identifier))
            seen.add(identifier)
    for track in data["tracks"]:
        need(track, {"id", "role", "title", "goal", "skill_ids", "lab_ids"}, errors)
        for skill_id in track.get("skill_ids", []):
            if skill_id not in ids["skills"]: errors.append("%s: unknown skill_id %r" % (track["__path"].relative_to(ROOT), skill_id))
        for lab_id in track.get("lab_ids", []):
            if lab_id not in ids["labs"]: errors.append("%s: unknown lab_id %r" % (track["__path"].relative_to(ROOT), lab_id))
    for skill in data["skills"]:
        need(skill, {"id", "title", "role", "prereq_ids", "mastery_criteria"}, errors)
        for prerequisite in skill.get("prereq_ids", []):
            if prerequisite not in ids["skills"]: errors.append("%s: unknown prereq_id %r" % (skill["__path"].relative_to(ROOT), prerequisite))
    for lab in data["labs"]:
        need(lab, {"id", "track_id", "role", "target", "mission", "objective", "known", "skills", "steps"}, errors)
        if lab.get("track_id") not in ids["tracks"]: errors.append("%s: unknown track_id %r" % (lab["__path"].relative_to(ROOT), lab.get("track_id")))
        for skill_id in lab.get("skills", []):
            if skill_id not in ids["skills"]: errors.append("%s: unknown skill_id %r" % (lab["__path"].relative_to(ROOT), skill_id))
        for step in lab.get("steps", []):
            if not isinstance(step, dict):
                errors.append("%s: step must be an object" % lab["__path"].relative_to(ROOT)); continue
            checked_step = {**step, "__path": lab["__path"]}
            need(checked_step, STEP_REQUIRED, errors, allow_empty=True)
            need(checked_step, {"guiding_question"}, errors)
            validate_rubric_items(step.get("expect"), "expect", lab["__path"].relative_to(ROOT), errors)
            validate_rubric_items(step.get("distractors"), "distractors", lab["__path"].relative_to(ROOT), errors)
            if step.get("kind") not in VALID_STEP_KINDS: errors.append("%s: invalid step kind %r" % (lab["__path"].relative_to(ROOT), step.get("kind")))
            kind = step.get("kind")
            if kind == "execute":
                need(checked_step, {"command", "command_anatomy"}, errors)
                if step.get("interaction") in {"browser-observation", "guided-observation"}:
                    need(checked_step, {"browser_steps"}, errors)
                    browser_steps = step.get("browser_steps")
                    if not isinstance(browser_steps, list) or len(browser_steps) < 3 or not all(isinstance(value, str) and value.strip() for value in browser_steps):
                        errors.append("%s: browser-observation step %r needs at least 3 clear browser_steps" % (lab["__path"].relative_to(ROOT), step.get("id")))
            if kind == "decide":
                need(checked_step, {"decision_options"}, errors)
                if not isinstance(step.get("decision_options"), list) or not step.get("decision_options"):
                    errors.append("%s: decide step %r needs non-empty decision_options" % (lab["__path"].relative_to(ROOT), step.get("id")))
            if kind != "execute":
                need(checked_step, {"expect"}, errors)
            if kind in {"think", "execute", "analyse", "decide"}:
                need(checked_step, {"hints"}, errors)
                if not isinstance(step.get("hints"), list) or len(step["hints"]) != 3:
                    errors.append("%s: step %r must have exactly 3 hints" % (lab["__path"].relative_to(ROOT), step.get("id")))
            elif "hints" in step:
                errors.append("%s: debrief step %r must not have hints" % (lab["__path"].relative_to(ROOT), step.get("id")))
    for playbook in data["playbooks"]:
        need(playbook, {"id", "role", "title", "phases"}, errors)
        phases = playbook.get("phases")
        if not isinstance(phases, list) or not phases:
            errors.append("%s: phases must be a non-empty list" % playbook["__path"].relative_to(ROOT))
            continue
        phase_ids = set()
        for phase in phases:
            if not isinstance(phase, dict):
                errors.append("%s: phase must be an object" % playbook["__path"].relative_to(ROOT)); continue
            checked_phase = dict(phase); checked_phase["__path"] = playbook["__path"]
            need(checked_phase, {"id", "title", "checks", "decision"}, errors)
            if phase.get("id") in phase_ids:
                errors.append("%s: duplicate phase id %r" % (playbook["__path"].relative_to(ROOT), phase.get("id")))
            phase_ids.add(phase.get("id"))
            checks = phase.get("checks")
            if not isinstance(checks, list) or not 2 <= len(checks) <= 4 or not all(isinstance(item, str) and item.strip() for item in checks):
                errors.append("%s: phase %r needs 2-4 non-empty checks" % (playbook["__path"].relative_to(ROOT), phase.get("id")))
            decision = phase.get("decision")
            if not isinstance(decision, dict) or not isinstance(decision.get("question"), str) or not decision["question"].strip() or not isinstance(decision.get("branches"), list) or not decision["branches"]:
                errors.append("%s: phase %r needs decision question and branches" % (playbook["__path"].relative_to(ROOT), phase.get("id")))
                continue
            for branch in decision["branches"]:
                if not isinstance(branch, dict) or not isinstance(branch.get("answer"), str) or not branch["answer"].strip() or not isinstance(branch.get("next"), str) or not branch["next"].strip():
                    errors.append("%s: phase %r has invalid branch" % (playbook["__path"].relative_to(ROOT), phase.get("id")))
        for phase in phases:
            for branch in phase.get("decision", {}).get("branches", []):
                if isinstance(branch, dict) and branch.get("next") not in phase_ids:
                    errors.append("%s: phase %r points to missing next %r" % (playbook["__path"].relative_to(ROOT), phase.get("id"), branch.get("next")))
    for command in data["commands"]:
        need(command, {"id", "name", "purpose", "syntax", "args", "when", "when_not", "look_for", "example_output", "mistakes", "next_steps"}, errors)
    for entry in data["glossary"]:
        need(entry, {"term", "plain_meaning", "where_you_meet_it", "related"}, errors)
    if errors:
        print("CONTENT VALIDATION FAILED")
        for error in errors: print("- " + error)
        return 1
    print("CONTENT VALIDATION PASSED")
    for category in CATEGORIES: print("content/%s: %d file(s)" % (category, len(data[category])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
