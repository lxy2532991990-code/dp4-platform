"""Merge audited extended DP4+/MM-DP4+ parameter rows into a v2 table.

The input is a machine-readable CSV/TSV export with one row per error-model
entry.  Scaling-only rows are recorded in the audit and are not merged into the
strict DP4+ parameter table.
"""

from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Iterable


REQUIRED_ERROR_ROWS = {"Csp2", "Csp3", "Hsp2", "Hsp3", "Csca", "Hsca"}
SCALING_ONLY_HINTS = {"slope", "intercept", "mae", "rmse", "r2", "r^2"}


def _clean(value: object) -> str:
    return str(value or "").strip()


def _optional_float(row: dict[str, str], *names: str) -> float | None:
    for name in names:
        raw = _clean(row.get(name))
        if raw:
            return float(raw)
    return None


def _required_float(row: dict[str, str], name: str) -> float:
    raw = _clean(row.get(name))
    if not raw:
        raise ValueError(f"Missing required numeric column '{name}'")
    return float(raw)


def _normalize_family(value: str) -> str:
    cleaned = _clean(value)
    if cleaned in {"DP4+", "MM-DP4+"}:
        return cleaned
    raise ValueError(f"Unsupported family '{value}'; expected DP4+ or MM-DP4+")


def _normalize_solvent_model(value: str) -> str:
    cleaned = _clean(value)
    return cleaned.upper() if cleaned else "GAS"


def _split_level_name(original_name: str) -> tuple[str, str, str]:
    parts = original_name.split(".")
    method = parts[0]
    basis = parts[1] if len(parts) > 1 else ""
    solvent_model = parts[2].upper() if len(parts) > 2 else "GAS"
    return method, basis, solvent_model


def _slash_level(method: str, basis: str, solvent_model: str) -> str:
    base = f"{method}/{basis}" if basis else method
    return base if solvent_model == "GAS" else f"{solvent_model}/{base}"


def _basis_aliases(name: str) -> set[str]:
    aliases = {name}
    replacements = {
        "(d,p)": "**",
        "(d)": "*",
        "(p)": "*",
        "M062x": "M06-2X",
        "wB97XD": "wb97xd",
    }
    for source, target in replacements.items():
        aliases.add(name.replace(source, target))
    return {alias for alias in aliases if alias}


def _aliases(original_name: str, family: str, display_name: str) -> list[str]:
    method, basis, solvent_model = _split_level_name(original_name)
    slash = f"{method}/{basis}" if basis else method
    candidates = {display_name, original_name, slash}
    if solvent_model != "GAS":
        candidates.update({
            f"{solvent_model}/{slash}",
            f"{slash}.{solvent_model}",
            f"{slash}/{solvent_model}",
        })
    for value in list(candidates):
        candidates.update(_basis_aliases(value))
    candidates.update({f"{family} {value}" for value in list(candidates)})
    return sorted(candidates)


def _error_entry(row: dict[str, str]) -> dict[str, object]:
    return {
        "distribution": "student_t_tail",
        "mu": _required_float(row, "m"),
        "sigma": _required_float(row, "s"),
        "nu": _required_float(row, "n"),
    }


def _nucleus_params(
    nucleus: str,
    scaled_row: dict[str, str],
    rows: dict[str, dict[str, str]],
    reference: float | None,
) -> dict[str, object]:
    if nucleus == "13C":
        unscaled_error = {
            "sp2": _error_entry(rows["Csp2"]),
            "sp3": _error_entry(rows["Csp3"]),
            "default": _error_entry(rows["Csp3"]),
        }
    else:
        unscaled_error = {
            "on_sp2_carbon": _error_entry(rows["Hsp2"]),
            "on_sp3_carbon": _error_entry(rows["Hsp3"]),
            "default": _error_entry(rows["Hsp3"]),
        }
    params: dict[str, object] = {
        "scaling_input": "unscaled_shift",
        "formula": (
            "delta_scaled = per-isomer linear regression of delta_unscaled "
            "against experimental shifts (extended DP4+ semantics)"
        ),
        "requires_tms": True,
        "intercept": 0.0,
        "slope": 1.0,
        "scaled_error": _error_entry(scaled_row),
        "unscaled_error": unscaled_error,
    }
    if reference is not None:
        params["reference_shielding"] = reference
        params["reference_source"] = "Extended parameter table"
    return params


def _read_delimited(path: Path) -> list[dict[str, str]]:
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        return [{key: _clean(value) for key, value in row.items()} for row in reader]


def _group_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        _normalize_family(row.get("family", "")),
        _clean(row.get("method")),
        _clean(row.get("basis")),
        _normalize_solvent_model(row.get("solvent_model", "")),
    )


def _is_scaling_only(rows: Iterable[dict[str, str]]) -> bool:
    for row in rows:
        row_label = _clean(row.get("row_label")).lower()
        if row_label in SCALING_ONLY_HINTS:
            return True
        if any(_clean(row.get(name)) for name in SCALING_ONLY_HINTS):
            return True
    return False


def _source_metadata(source_id: str, source_label: str, source_doi: str) -> dict[str, object]:
    source: dict[str, object] = {"label": source_label}
    if source_doi:
        source["doi"] = source_doi
    return source


def merge_parameter_rows(
    table: dict[str, object],
    rows: list[dict[str, str]],
    source_id: str,
    source_label: str,
    source_doi: str = "",
) -> tuple[dict[str, object], dict[str, object]]:
    merged = deepcopy(table)
    levels = merged.setdefault("levels", {})
    sources = merged.setdefault("sources", {})
    sources[source_id] = _source_metadata(source_id, source_label, source_doi)

    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        if not any(_clean(value) for value in row.values()):
            continue
        groups.setdefault(_group_key(row), []).append(row)

    audit: dict[str, object] = {
        "source_id": source_id,
        "source_label": source_label,
        "source_doi": source_doi,
        "added_levels": [],
        "replaced_levels": [],
        "rejected_incomplete": [],
        "rejected_scaling_only": [],
    }

    for (family, method, basis, solvent_model), group_rows in sorted(groups.items()):
        display = _slash_level(method, basis, solvent_model)
        level_key = f"{family}/{display}"
        row_map = {_clean(row.get("row_label")): row for row in group_rows if _clean(row.get("row_label"))}
        missing = sorted(REQUIRED_ERROR_ROWS - set(row_map))
        if missing:
            rejected = {
                "level_key": level_key,
                "missing_rows": missing,
                "present_rows": sorted(row_map),
            }
            target = "rejected_scaling_only" if _is_scaling_only(group_rows) else "rejected_incomplete"
            audit[target].append(rejected)
            continue

        reference = {
            "13C": _optional_float(row_map["Csca"], "reference_13c", "reference_shielding_13c", "ref_13c"),
            "1H": _optional_float(row_map["Hsca"], "reference_1h", "reference_shielding_1h", "ref_1h"),
        }
        reference = {nucleus: value for nucleus, value in reference.items() if value is not None}
        original_name = f"{method}.{basis}" if solvent_model == "GAS" else f"{method}.{basis}.{solvent_model}"
        level = {
            "family": family,
            "original_name": original_name,
            "aliases": _aliases(original_name, family, display),
            "source_id": source_id,
            "doi": source_doi,
            "method_reference_ids": [source_id],
            "geometry_level": "Extended parameter source",
            "nmr_level": display,
            "solvent_model": solvent_model,
            "solvent": "GAS" if solvent_model == "GAS" else "as defined by extended parameter source",
            "notes": "Merged from audited extended parameter rows; n/m/s rows are Student-t error model parameters.",
            "reference_shielding": reference,
            "reference_shielding_by_solvent": {"GAS" if solvent_model == "GAS" else solvent_model: reference},
            "nuclei": {
                "13C": _nucleus_params("13C", row_map["Csca"], row_map, reference.get("13C")),
                "1H": _nucleus_params("1H", row_map["Hsca"], row_map, reference.get("1H")),
            },
        }
        replaced = level_key in levels
        levels[level_key] = level
        audit["replaced_levels" if replaced else "added_levels"].append({
            "level_key": level_key,
            "mapped_rows": sorted(REQUIRED_ERROR_ROWS),
            "reference_found": sorted(reference),
        })

    generated_from = merged.setdefault("generated_from", {})
    generated_from["extended_parameter_import"] = {
        "source_id": source_id,
        "source_label": source_label,
        "source_doi": source_doi,
        "merge_tool": "tools/merge_extended_dp4_parameters.py",
    }
    return merged, audit


def merge_parameter_file(
    base_table_path: Path,
    parameter_rows_path: Path,
    source_id: str,
    source_label: str,
    source_doi: str = "",
) -> tuple[dict[str, object], dict[str, object]]:
    table = json.loads(base_table_path.read_text(encoding="utf-8"))
    rows = _read_delimited(parameter_rows_path)
    return merge_parameter_rows(table, rows, source_id, source_label, source_doi)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="Existing v2 parameter table JSON")
    parser.add_argument("--rows", required=True, type=Path, help="CSV/TSV export with error-model rows")
    parser.add_argument("--output", required=True, type=Path, help="Merged parameter table JSON")
    parser.add_argument("--audit", required=True, type=Path, help="Merge audit JSON")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--source-doi", default="")
    args = parser.parse_args()

    table, audit = merge_parameter_file(
        args.base,
        args.rows,
        args.source_id,
        args.source_label,
        args.source_doi,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(table, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.audit.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(table.get('levels', {}))} levels)")
    print(f"Wrote {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
