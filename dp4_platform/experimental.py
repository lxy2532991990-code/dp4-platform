"""Experimental assignment loading and validation."""

from __future__ import annotations

import csv

from .models import ExperimentalAssignment


def normalize_nucleus(raw: str) -> str:
    value = str(raw).strip().upper().replace(" ", "")
    if value in {"H", "1H"}:
        return "1H"
    if value in {"C", "13C"}:
        return "13C"
    return str(raw).strip()


def _validate_exchange_groups(assignments: list[ExperimentalAssignment]) -> None:
    by_group: dict[str, list[ExperimentalAssignment]] = {}
    for assignment in assignments:
        if not assignment.exchange_group:
            continue
        by_group.setdefault(assignment.exchange_group, []).append(assignment)
    for group, members in by_group.items():
        if len(members) != 2:
            raise ValueError(
                f"exchange_group '{group}' must pair exactly 2 rows; got {len(members)}"
            )
        nuclei = {member.nucleus for member in members}
        if len(nuclei) != 1:
            raise ValueError(
                f"exchange_group '{group}' rows must share the same nucleus; got {sorted(nuclei)}"
            )


def load_experimental_assignments(path: str, allowed_nuclei: tuple[str, ...]) -> list[ExperimentalAssignment]:
    required = {"candidate_atom_id", "nucleus", "exp_shift_ppm"}
    assignments: list[ExperimentalAssignment] = []
    seen_keys: set[tuple[int, str]] = set()

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("Experimental CSV is missing a header row")
        missing = required - set(reader.fieldnames)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"Experimental CSV missing required columns: {missing_text}")

        for row_index, row in enumerate(reader, start=2):
            try:
                atom_id = int(str(row["candidate_atom_id"]).strip())
            except ValueError as exc:
                raise ValueError(f"Invalid candidate_atom_id at row {row_index}") from exc
            nucleus = normalize_nucleus(row["nucleus"])
            if nucleus not in allowed_nuclei:
                allowed = ", ".join(allowed_nuclei)
                raise ValueError(f"Unsupported nucleus '{nucleus}' at row {row_index}; allowed: {allowed}")
            try:
                exp_shift = float(str(row["exp_shift_ppm"]).strip())
            except ValueError as exc:
                raise ValueError(f"Invalid exp_shift_ppm at row {row_index}") from exc

            key = (atom_id, nucleus)
            if key in seen_keys:
                raise ValueError(f"Duplicate experimental assignment for atom {atom_id} nucleus {nucleus}")
            seen_keys.add(key)

            assignments.append(
                ExperimentalAssignment(
                    candidate_atom_id=atom_id,
                    nucleus=nucleus,
                    exp_shift_ppm=exp_shift,
                    label=str(row.get("label", "")).strip(),
                    exchange_group=str(row.get("exchange_group", "")).strip(),
                )
            )

    if not assignments:
        raise ValueError("Experimental CSV contains no assignments")
    _validate_exchange_groups(assignments)
    return assignments
