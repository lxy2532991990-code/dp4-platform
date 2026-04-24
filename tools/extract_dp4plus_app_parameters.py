"""Extract DP4+App parameter workbooks into the platform v2 JSON schema.

The extractor intentionally uses only the Python standard library so the
generated parameter table can be audited without installing DP4+App's runtime
stack.  It reads the public PyPI sdist, verifies the expected SHA256 digest,
extracts the DP4+/MM-DP4+ Excel workbooks, and writes a normalized JSON table
plus an audit report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tarfile
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


PACKAGE_NAME = "dp4plus-app"
APP_VERSION = "2.1.3"
EXPECTED_SHA256 = "220a82c8cea61b64df4f4e4f0feeb8ac7e5f62398bafe24d67f3459d61ce6f3d"
APP_DOI = "10.1021/acs.jnatprod.3c00566"
DP4PLUS_DOI = "10.1021/acs.joc.5b02396"

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _clean_value(value):
    if isinstance(value, float) and math.isfinite(value):
        rounded = round(value, 12)
        return int(rounded) if float(rounded).is_integer() else rounded
    return value


class Workbook:
    def __init__(self, path: Path):
        self.path = path
        self._zip = zipfile.ZipFile(path)
        self._shared_strings = self._load_shared_strings()
        self._sheets = self._load_sheet_paths()

    @property
    def sheet_names(self) -> list[str]:
        return list(self._sheets)

    def close(self) -> None:
        self._zip.close()

    def _load_shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self._zip.namelist():
            return []
        root = ET.fromstring(self._zip.read("xl/sharedStrings.xml"))
        strings: list[str] = []
        for item in root.findall("a:si", NS):
            strings.append("".join(text.text or "" for text in item.findall(".//a:t", NS)))
        return strings

    def _load_sheet_paths(self) -> dict[str, str]:
        wb = ET.fromstring(self._zip.read("xl/workbook.xml"))
        rel_root = ET.fromstring(self._zip.read("xl/_rels/workbook.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rel_root}
        sheets: dict[str, str] = {}
        for sheet in wb.find("a:sheets", NS):
            rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = rels[rel_id]
            path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
            sheets[sheet.attrib["name"]] = path.replace("xl/../", "")
        return sheets

    def _cell_value(self, cell):
        cell_type = cell.attrib.get("t")
        if cell_type == "s":
            value = cell.find("a:v", NS)
            return self._shared_strings[int(value.text)] if value is not None and value.text else ""
        if cell_type == "inlineStr":
            return "".join(text.text or "" for text in cell.findall(".//a:t", NS))
        value = cell.find("a:v", NS)
        if value is None or value.text is None:
            return ""
        raw = value.text
        try:
            return _clean_value(float(raw))
        except ValueError:
            return raw

    def read_sheet(self, name: str) -> list[list[object]]:
        root = ET.fromstring(self._zip.read(self._sheets[name]))
        rows: list[list[object]] = []
        for row in root.findall(".//a:sheetData/a:row", NS):
            values: list[object] = []
            for cell in row.findall("a:c", NS):
                index = _column_index(cell.attrib.get("r", "A1"))
                while len(values) <= index:
                    values.append("")
                values[index] = self._cell_value(cell)
            rows.append(values)
        return rows


def _split_level_name(original_name: str) -> tuple[str, str, str]:
    parts = original_name.split(".")
    method = parts[0]
    basis = parts[1] if len(parts) > 1 else ""
    solvent_model = parts[2].upper() if len(parts) > 2 else "GAS"
    return method, basis, solvent_model


def _slash_level(original_name: str) -> str:
    method, basis, solvent_model = _split_level_name(original_name)
    base = f"{method}/{basis}" if basis else method
    return base if solvent_model == "GAS" else f"{solvent_model}/{base}"


def _basis_aliases(name: str) -> set[str]:
    aliases = {name}
    aliases.add(name.replace("(d,p)", "**"))
    aliases.add(name.replace("(d)", "*"))
    aliases.add(name.replace("(p)", "*"))
    aliases.add(name.replace("M062x", "M06-2X"))
    aliases.add(name.replace("wB97XD", "wb97xd"))
    return {alias for alias in aliases if alias}


def _aliases(original_name: str, family: str, display_name: str) -> list[str]:
    method, basis, solvent_model = _split_level_name(original_name)
    slash = f"{method}/{basis}" if basis else method
    dotted = original_name
    candidates = {display_name, original_name, dotted, slash}
    if solvent_model != "GAS":
        candidates.update({
            f"{solvent_model}/{slash}",
            f"{slash}.{solvent_model}",
            f"{slash}/{solvent_model}",
        })
    for value in list(candidates):
        candidates.update(_basis_aliases(value))
    prefix = "MM-DP4+" if family == "MM-DP4+" else "DP4+"
    candidates.update({f"{prefix} {value}" for value in list(candidates)})
    return sorted(candidates)


def _error_entry(row: dict[str, object]) -> dict[str, object]:
    return {
        "distribution": "student_t_tail",
        "mu": float(row["m"]),
        "sigma": float(row["s"]),
        "nu": float(row["n"]),
    }


def _reference_from_row(row: list[object]) -> dict[str, float]:
    out: dict[str, float] = {}
    if len(row) > 1 and row[1] != "":
        out["13C"] = float(row[1])
    if len(row) > 2 and row[2] != "":
        out["1H"] = float(row[2])
    return out


def _standard_maps(workbook: Workbook, standard_sheet: str, solvent_sheets: list[str]) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, dict[str, float]]]]:
    defaults: dict[str, dict[str, float]] = {}
    for row in workbook.read_sheet(standard_sheet)[1:]:
        if row and row[0]:
            defaults[str(row[0])] = _reference_from_row(row)

    by_solvent: dict[str, dict[str, dict[str, float]]] = {}
    for sheet in solvent_sheets:
        if sheet not in workbook.sheet_names:
            continue
        for row in workbook.read_sheet(sheet)[1:]:
            if row and row[0]:
                by_solvent.setdefault(str(row[0]), {})[sheet] = _reference_from_row(row)
    return defaults, by_solvent


def _parameter_rows(workbook: Workbook, sheet_name: str) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    data = workbook.read_sheet(sheet_name)
    headers = [str(item) for item in data[0]]
    for row in data[1:]:
        if not row or not row[0]:
            continue
        item = {"row_label": row[0]}
        for index, header in enumerate(headers[1:], start=1):
            item[header] = row[index] if index < len(row) else ""
        rows[str(row[0])] = item
    return rows


def _nucleus_params(nucleus: str, scaled: dict[str, object], unscaled: dict[str, dict[str, object]], reference: float | None) -> dict[str, object]:
    if nucleus == "13C":
        unscaled_error = {
            "sp2": _error_entry(unscaled["Csp2"]),
            "sp3": _error_entry(unscaled["Csp3"]),
            "default": _error_entry(unscaled["Csp3"]),
        }
    else:
        unscaled_error = {
            "on_sp2_carbon": _error_entry(unscaled["Hsp2"]),
            "on_sp3_carbon": _error_entry(unscaled["Hsp3"]),
            "default": _error_entry(unscaled["Hsp3"]),
        }
    params: dict[str, object] = {
        "scaling_input": "unscaled_shift",
        "formula": (
            "delta_scaled = per-isomer linear regression of delta_unscaled "
            "against experimental shifts (DP4+App semantics)"
        ),
        "requires_tms": True,
        "intercept": 0.0,
        "slope": 1.0,
        "scaled_error": _error_entry(scaled),
        "unscaled_error": unscaled_error,
    }
    if reference is not None:
        params["reference_shielding"] = reference
        params["reference_source"] = "DP4+App standard table"
    return params


def _build_levels(
    workbook: Workbook,
    family: str,
    source_file: str,
    standard_sheet: str,
    solvent_sheets: list[str],
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    levels: dict[str, dict[str, object]] = {}
    audit: list[dict[str, object]] = []
    defaults, by_solvent = _standard_maps(workbook, standard_sheet, solvent_sheets)
    parameter_sheet_names = [name for name in workbook.sheet_names if name not in {standard_sheet, *solvent_sheets}]

    for sheet_name in parameter_sheet_names:
        rows = _parameter_rows(workbook, sheet_name)
        required = {"Csp2", "Csp3", "Hsp2", "Hsp3", "Csca", "Hsca"}
        missing = sorted(required - set(rows))
        if missing:
            audit.append({
                "source_file": source_file,
                "sheet": sheet_name,
                "status": "needs_review",
                "missing_rows": missing,
            })
            continue

        display = _slash_level(sheet_name)
        level_key = f"{family}/{display}"
        method, basis, solvent_model = _split_level_name(sheet_name)
        reference = defaults.get(sheet_name, {})
        level = {
            "family": family,
            "original_name": sheet_name,
            "aliases": _aliases(sheet_name, family, display),
            "source_id": "dp4plus_app_2023",
            "doi": APP_DOI,
            "method_reference_ids": ["dp4plus_2015", "dp4plus_app_2023"],
            "app_version": APP_VERSION,
            "license": "MIT",
            "geometry_level": "DP4+App standard workflow",
            "nmr_level": display,
            "solvent_model": solvent_model,
            "solvent": "GAS" if solvent_model == "GAS" else "CHCl3 default in DP4+App standard table",
            "notes": "Extracted from DP4+App parameter workbook; n/m/s rows are Student-t error model parameters.",
            "reference_shielding": reference,
            "reference_shielding_by_solvent": by_solvent.get(sheet_name, {}),
            "nuclei": {
                "13C": _nucleus_params("13C", rows["Csca"], rows, reference.get("13C")),
                "1H": _nucleus_params("1H", rows["Hsca"], rows, reference.get("1H")),
            },
        }
        levels[level_key] = level
        audit.append({
            "source_file": source_file,
            "sheet": sheet_name,
            "status": "ok",
            "level_key": level_key,
            "mapped_rows": sorted(required),
            "reference_found": sorted(reference),
        })
    return levels, audit


def extract(sdist: Path) -> tuple[dict[str, object], dict[str, object]]:
    actual = _sha256(sdist)
    if actual.lower() != EXPECTED_SHA256:
        raise ValueError(
            f"Unexpected SHA256 for {sdist}: {actual}; expected {EXPECTED_SHA256}"
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        with tarfile.open(sdist, "r:gz") as tf:
            tf.extractall(temp)
        source_root = next(temp.glob("dp4plus_app-*"))
        data_dir = source_root / "src" / "dp4plus_app"

        qm = Workbook(data_dir / "data_base_QM.xlsx")
        mm = Workbook(data_dir / "data_base_MM.xlsx")
        try:
            solvent_sheets_qm = qm.sheet_names[1:13]
            solvent_sheets_mm = mm.sheet_names[1:13]
            qm_levels, qm_audit = _build_levels(
                qm, "DP4+", "data_base_QM.xlsx", "standard", solvent_sheets_qm
            )
            mm_levels, mm_audit = _build_levels(
                mm, "MM-DP4+", "data_base_MM.xlsx", "Standard", solvent_sheets_mm
            )
        finally:
            qm.close()
            mm.close()

    levels = {**qm_levels, **mm_levels}
    table = {
        "schema_version": 2,
        "description": (
            "DP4+/MM-DP4+ parameter table extracted from DP4+App 2.1.3. "
            "The scoring semantics are chemical-shift domain: unscaled shifts are "
            "computed as sigma_reference - sigma_sample, then scaled per DP4+App."
        ),
        "generated_from": {
            "package": PACKAGE_NAME,
            "version": APP_VERSION,
            "sdist_sha256": EXPECTED_SHA256,
            "pypi_url": "https://pypi.org/project/dp4plus-app/",
            "extraction_tool": "tools/extract_dp4plus_app_parameters.py",
        },
        "sources": {
            "dp4plus_2015": {
                "label": "Original DP4+ parameterization",
                "doi": DP4PLUS_DOI,
            },
            "dp4plus_app_2023": {
                "label": "DP4+App reference implementation",
                "doi": APP_DOI,
                "package": PACKAGE_NAME,
                "version": APP_VERSION,
                "license": "MIT",
            },
        },
        "fallback_level": "DP4+/mPW1PW91/6-31+G(d,p)",
        "default_level": "DP4+/mPW1PW91/6-31+G(d,p)",
        "levels": levels,
    }
    fallback = table["fallback_level"]
    if fallback in levels:
        table["nuclei"] = levels[fallback]["nuclei"]

    audit = {
        "package": PACKAGE_NAME,
        "version": APP_VERSION,
        "sdist_sha256": actual,
        "level_count": len(levels),
        "expected_counts": {"DP4+": 24, "MM-DP4+": 36},
        "actual_counts": {
            "DP4+": sum(1 for item in levels.values() if item["family"] == "DP4+"),
            "MM-DP4+": sum(1 for item in levels.values() if item["family"] == "MM-DP4+"),
        },
        "workbook_rows": qm_audit + mm_audit,
    }
    return table, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdist", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()

    table, audit = extract(args.sdist)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(table, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.audit.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(table['levels'])} levels)")
    print(f"Wrote {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
