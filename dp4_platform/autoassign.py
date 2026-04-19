"""Auto-assignment of experimental NMR chemical shifts to calculated atoms."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass

from .config import DP4Config
from .dp4 import load_parameter_table, predict_shift
from .energy import boltzmann_average_shieldings, compute_boltzmann_weights
from .models import CandidateIsomer
from .parser import load_candidate_from_directory


_FLOAT_PATTERN = re.compile(r"[-+]?\d+\.\d+|[-+]?\d+")


def parse_nmr_text(text: str) -> list[float]:
    """Extract chemical shifts (ppm) from a free-form NMR text string.

    Skips common metadata tokens (frequency in MHz, solvent-related integers) by
    taking only values that look like ppm shifts: decimal numbers, or integers in
    the plausible chemical-shift range.
    """
    if not text:
        return []

    cleaned = text
    cleaned = re.sub(r"\(([^)]*)\)", " ", cleaned)
    cleaned = re.sub(r"\[[^]]*]", " ", cleaned)
    cleaned = re.sub(r"(?i)\d+\s*MHz", " ", cleaned)
    cleaned = re.sub(r"(?i)\d+\s*Hz", " ", cleaned)
    cleaned = re.sub(r"(?i)CD\s*3?\s*OD(?:-d\d?)?", " ", cleaned)
    cleaned = re.sub(r"(?i)CDCl\s*3", " ", cleaned)
    cleaned = re.sub(r"(?i)DMSO(?:-d\d?)?", " ", cleaned)
    cleaned = re.sub(r"(?i)[1-3]H\s*NMR", " ", cleaned)
    cleaned = re.sub(r"(?i)13C\s*NMR", " ", cleaned)
    cleaned = re.sub(r"(?i)δ", " ", cleaned)

    shifts: list[float] = []
    seen: set[float] = set()
    for match in _FLOAT_PATTERN.finditer(cleaned):
        token = match.group(0)
        try:
            value = float(token)
        except ValueError:
            continue
        if "." not in token and abs(value) > 250:
            continue
        key = round(value, 4)
        if key in seen:
            continue
        seen.add(key)
        shifts.append(value)
    return shifts


@dataclass
class AutoAssignRow:
    nucleus: str
    atom_id: int
    predicted_shift_ppm: float
    exp_shift_ppm: float | None
    confidence: float
    element: str = ""


def _assign_one_nucleus(
    atom_predictions: list[tuple[int, float]],
    exp_shifts: list[float],
) -> list[AutoAssignRow]:
    """Return one row per calculated atom, assigned to an experimental shift.

    - If len(atoms) == len(exp): rank-match (descending sort on both is optimal
      for absolute-difference cost).
    - Otherwise: greedy nearest-neighbor per atom (atoms may share an exp peak,
      which captures chemically equivalent carbons reported as a single signal).

    Confidence = |nearest - second_nearest|; smaller => more ambiguous.
    """
    if not atom_predictions:
        return []

    atoms_sorted = sorted(atom_predictions, key=lambda item: -item[1])

    if exp_shifts and len(exp_shifts) == len(atom_predictions):
        exp_sorted = sorted(exp_shifts, reverse=True)
        rows: list[AutoAssignRow] = []
        for (atom_id, predicted), exp in zip(atoms_sorted, exp_sorted):
            others = [abs(other - predicted) for other in exp_sorted if other != exp]
            confidence = min(others) if others else float("inf")
            rows.append(
                AutoAssignRow(
                    nucleus="",
                    atom_id=atom_id,
                    predicted_shift_ppm=predicted,
                    exp_shift_ppm=exp,
                    confidence=confidence,
                )
            )
        return rows

    rows = []
    for atom_id, predicted in atoms_sorted:
        if not exp_shifts:
            rows.append(
                AutoAssignRow(
                    nucleus="",
                    atom_id=atom_id,
                    predicted_shift_ppm=predicted,
                    exp_shift_ppm=None,
                    confidence=0.0,
                )
            )
            continue
        distances = sorted(((abs(peak - predicted), peak) for peak in exp_shifts))
        best = distances[0][1]
        confidence = distances[1][0] - distances[0][0] if len(distances) > 1 else float("inf")
        rows.append(
            AutoAssignRow(
                nucleus="",
                atom_id=atom_id,
                predicted_shift_ppm=predicted,
                exp_shift_ppm=best,
                confidence=confidence,
            )
        )
    return rows


def build_candidate_predictions(
    name: str,
    directory: str,
    config: DP4Config,
) -> tuple[
    CandidateIsomer,
    dict[str, dict[int, float]],
    dict[int, str],
    dict[int, tuple[float, float, float]],
]:
    """Parse a candidate and return predicted shifts per (nucleus, atom_id).

    Also returns element labels per atom_id and one representative XYZ coordinate
    set (taken from the usable conformer with the highest Boltzmann weight that
    actually has coordinates parsed).
    """
    candidate = load_candidate_from_directory(name=name, directory=directory, config=config)
    if not candidate.collection.usable_records:
        raise ValueError(f"Candidate '{name}' has no usable conformers.")
    compute_boltzmann_weights(candidate, config)
    boltzmann_average_shieldings(candidate, config.nuclei)

    parameter_table = load_parameter_table(config.parameter_table)
    predicted: dict[str, dict[int, float]] = {}
    for nucleus in config.nuclei:
        shieldings = candidate.averaged_shieldings.get(nucleus, {})
        predicted[nucleus] = {
            atom_id: predict_shift(value, nucleus, parameter_table, config.scaling_mode)
            for atom_id, value in shieldings.items()
        }

    elements: dict[int, str] = {}
    for record in candidate.collection.usable_records:
        for atom_id, element in record.atom_elements.items():
            elements.setdefault(atom_id, element)

    coordinates: dict[int, tuple[float, float, float]] = {}
    records_with_coords = [r for r in candidate.collection.usable_records if r.coordinates]
    if records_with_coords:
        best = max(records_with_coords, key=lambda r: r.effective_weight)
        coordinates = dict(best.coordinates)

    return candidate, predicted, elements, coordinates


def auto_assign(
    predicted_by_nucleus: dict[str, dict[int, float]],
    exp_shifts_by_nucleus: dict[str, list[float]],
    elements: dict[int, str] | None = None,
) -> list[AutoAssignRow]:
    rows: list[AutoAssignRow] = []
    elements = elements or {}
    for nucleus, predicted in predicted_by_nucleus.items():
        if not predicted:
            continue
        exp_shifts = list(exp_shifts_by_nucleus.get(nucleus, []))
        atom_predictions = [(atom_id, value) for atom_id, value in predicted.items()]
        for row in _assign_one_nucleus(atom_predictions, exp_shifts):
            row.nucleus = nucleus
            row.element = elements.get(row.atom_id, "")
            rows.append(row)
    rows.sort(key=lambda item: (item.nucleus, item.atom_id))
    return rows


def write_assignments_csv(path: str, rows: list[AutoAssignRow]) -> int:
    """Write rows to CSV in the format expected by `load_experimental_assignments`.

    Rows with missing exp_shift_ppm are skipped. Returns the number of written rows.
    """
    written = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["candidate_atom_id", "nucleus", "exp_shift_ppm"])
        for row in rows:
            if row.exp_shift_ppm is None:
                continue
            writer.writerow([row.atom_id, row.nucleus, f"{row.exp_shift_ppm:.4f}"])
            written += 1
    return written
