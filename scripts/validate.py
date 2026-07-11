#!/usr/bin/env python3
"""Validate the compact AutoCAD lifecycle JSONL dataset without dependencies."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data" / "autocad_2004_2027.jsonl"
METADATA = BASE / "metadata.json"
SCHEMA = BASE / "schema.json"

REQUIRED = {
    "id", "type", "name", "availability", "new_in", "changed_in",
    "removed_in", "restored_in", "available_in_latest", "source",
}
OPTIONAL = {"express_tools", "occurrence"}
REMOVED_FIELDS = {
    "record_key", "source_pdf", "source_page", "source_row",
    "status_by_version", "marker_by_version", "cell_color_rgb_by_version",
    "available_versions", "introduced_versions", "modified_versions",
    "unavailable_versions", "unknown_versions", "availability_ranges",
    "first_available_version", "last_available_version", "is_available_in_2027",
    "events", "search_text",
}


def fail(message: str) -> int:
    print(f"FAIL {message}", file=sys.stderr)
    return 1


def version_axis(record_type: str, metadata: dict) -> list[str]:
    try:
        axis = metadata["version_axes"][record_type]
    except KeyError as exc:
        raise ValueError(f"missing version axis for {record_type}") from exc
    if not isinstance(axis, list) or not axis or not all(isinstance(v, str) for v in axis):
        raise ValueError(f"invalid version axis for {record_type}")
    if len(axis) != len(set(axis)):
        raise ValueError(f"duplicate versions in axis for {record_type}")
    return axis


def expand_availability(record: dict, versions: list[str]) -> list[bool]:
    index = {version: position for position, version in enumerate(versions)}
    states = [False] * len(versions)
    previous_end = -2
    for interval in record["availability"]:
        if not isinstance(interval, dict) or set(interval) != {"from", "to"}:
            raise ValueError("availability interval must contain only from/to")
        start = interval["from"]
        end = interval["to"]
        if start not in index or end not in index:
            raise ValueError(f"availability interval uses unknown version: {start}-{end}")
        left, right = index[start], index[end]
        if left > right:
            raise ValueError(f"availability interval is reversed: {start}-{end}")
        if left <= previous_end:
            raise ValueError("availability intervals overlap or are unsorted")
        if left == previous_end + 1:
            raise ValueError("adjacent availability intervals must be merged")
        for position in range(left, right + 1):
            states[position] = True
        previous_end = right
    return states


def derive_transitions(
    states: list[bool], versions: list[str], new_in: list[str]
) -> tuple[list[str], list[str]]:
    removed, restored = [], []
    new_versions = set(new_in)
    for position in range(1, len(states)):
        if states[position - 1] and not states[position]:
            removed.append(versions[position])
        elif (
            not states[position - 1]
            and states[position]
            and versions[position] not in new_versions
        ):
            restored.append(versions[position])
    return removed, restored


def validate_ordered_versions(values, field: str, versions: list[str]) -> list[str]:
    errors = []
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        return [f"{field} must be a string list"]
    if len(values) != len(set(values)):
        errors.append(f"{field} contains duplicates")
    unknown = [v for v in values if v not in versions]
    if unknown:
        errors.append(f"{field} contains unknown versions {unknown}")
    known = [v for v in values if v in versions]
    if known != sorted(known, key=versions.index):
        errors.append(f"{field} is not in version-axis order")
    return errors


def validate_record(record: dict, metadata: dict) -> list[str]:
    errors = []
    if not isinstance(record, dict):
        return ["record is not an object"]
    record_type = record.get("type")
    allowed = REQUIRED | OPTIONAL
    missing = REQUIRED - set(record)
    extra = set(record) - allowed
    if missing:
        errors.append(f"missing fields {sorted(missing)}")
    if extra:
        errors.append(f"unexpected fields {sorted(extra)}")
    legacy = set(record) & REMOVED_FIELDS
    if legacy:
        errors.append(f"legacy fields retained {sorted(legacy)}")
    if record_type not in {"command", "system_variable"}:
        return errors + [f"invalid type {record_type!r}"]
    try:
        versions = version_axis(record_type, metadata)
    except ValueError as exc:
        return errors + [str(exc)]
    if not isinstance(record.get("id"), str) or not record["id"]:
        errors.append("id must be a non-empty string")
    expected_prefix = "cmd-" if record_type == "command" else "sysvar-"
    if isinstance(record.get("id"), str) and not record["id"].startswith(expected_prefix):
        errors.append(f"id must start with {expected_prefix}")
    if not isinstance(record.get("name"), str) or not record["name"]:
        errors.append("name must be a non-empty string")
    if record_type == "command":
        if not isinstance(record.get("express_tools"), bool):
            errors.append("command must contain boolean express_tools")
    elif "express_tools" in record:
        errors.append("system_variable must not contain express_tools")
    if "occurrence" in record and (not isinstance(record["occurrence"], int) or record["occurrence"] < 2):
        errors.append("occurrence must be an integer >= 2")
    source = record.get("source")
    if not isinstance(source, dict) or set(source) != {"page", "row"}:
        errors.append("source must contain only page/row")
    elif any(not isinstance(source[k], int) or source[k] < 1 for k in ("page", "row")):
        errors.append("source page/row must be positive integers")
    if not isinstance(record.get("availability"), list):
        return errors + ["availability must be a list"]
    try:
        states = expand_availability(record, versions)
    except ValueError as exc:
        return errors + [str(exc)]
    for field in ("new_in", "changed_in", "removed_in", "restored_in"):
        errors.extend(validate_ordered_versions(record.get(field), field, versions))
    index = {v: i for i, v in enumerate(versions)}
    for field in ("new_in", "changed_in"):
        for version in record.get(field, []):
            if version in index and not states[index[version]]:
                errors.append(f"{field} version {version} is not available")
    removed, restored = derive_transitions(states, versions, record.get("new_in", []))
    if record.get("removed_in") != removed:
        errors.append(f"removed_in mismatch: expected {removed}")
    if record.get("restored_in") != restored:
        errors.append(f"restored_in mismatch: expected {restored}")
    if record.get("available_in_latest") is not states[-1]:
        errors.append(f"available_in_latest mismatch: expected {states[-1]}")
    return errors


def main() -> int:
    for path in (DATA, METADATA, SCHEMA):
        if not path.exists():
            return fail(f"missing required file: {path}")
    try:
        metadata = json.loads(METADATA.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"cannot parse metadata/schema: {exc}")
    schema_props = set(schema.get("properties", {}))
    if schema.get("additionalProperties") is not False:
        return fail("schema must set additionalProperties=false")
    leaked = schema_props & REMOVED_FIELDS
    if leaked:
        return fail(f"schema retains legacy fields: {sorted(leaked)}")
    records = []
    try:
        with DATA.open(encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    return fail(f"blank JSONL line at {line_no}")
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    return fail(f"invalid JSONL at line {line_no}: {exc}")
    except OSError as exc:
        return fail(f"cannot read data: {exc}")
    ids = [r.get("id") for r in records if isinstance(r, dict)]
    if len(ids) != len(set(ids)):
        return fail("record IDs are not globally unique")
    counts = Counter(r.get("type") for r in records if isinstance(r, dict))
    expected = metadata.get("counts", {})
    actual = {
        "commands": counts["command"],
        "system_variables": counts["system_variable"],
        "total": len(records),
    }
    if actual != expected:
        return fail(f"record counts mismatch: expected {expected}, got {actual}")
    if actual != {"commands": 1444, "system_variables": 1164, "total": 2608}:
        return fail(f"unexpected canonical counts: {actual}")
    all_errors = []
    for line_no, record in enumerate(records, 1):
        for error in validate_record(record, metadata):
            all_errors.append(f"line {line_no} id={record.get('id')}: {error}")
            if len(all_errors) >= 30:
                break
        if len(all_errors) >= 30:
            break
    if all_errors:
        return fail("validation errors:\n" + "\n".join(all_errors))
    command_axis = version_axis("command", metadata)
    variable_axis = version_axis("system_variable", metadata)
    version_cells = counts["command"] * len(command_axis) + counts["system_variable"] * len(variable_axis)
    if version_cells != metadata.get("version_cells") or version_cells != 66084:
        return fail(f"version cell count mismatch: {version_cells}")
    print(
        f"PASS records={len(records)} commands={counts['command']} "
        f"system_variables={counts['system_variable']} version_cells={version_cells}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

