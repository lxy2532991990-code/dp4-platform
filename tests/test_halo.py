from __future__ import annotations

import unittest
from pathlib import Path

from dp4_platform.config import DP4Config
from dp4_platform.dp4 import (
    apply_tms_referencing,
    load_parameter_table,
    score_candidates_all_modes,
    validate_parameter_table,
)
from dp4_platform.halo import (
    HALOGENS,
    apply_mstd_unscaled,
    detect_halogen_neighbors,
    mstd_key,
)
from dp4_platform.models import CandidateIsomer, ExperimentalAssignment, ShiftRow
from dp4_platform.report import _shift_csv_fieldnames, _shift_csv_row
from dp4_platform.structure_model import infer_bonds
from tools.extract_dp4plus_app_parameters import _extract_mstd_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MSTD_QM_WORKBOOK = (
    PROJECT_ROOT
    / "DP4plus-App"
    / "pypi_pkg"
    / "extracted"
    / "dp4plus_app"
    / "MSTD-QM-Stand.xlsx"
)


def _chloromethane_geometry() -> tuple[dict[int, str], dict[int, tuple[float, float, float]]]:
    elements = {1: "C", 2: "Cl", 3: "H", 4: "H", 5: "H"}
    coordinates = {
        1: (0.000, 0.000, 0.000),
        2: (1.776, 0.000, 0.000),  # C-Cl ~1.78 Å
        3: (-0.380, 1.027, 0.000),
        4: (-0.380, -0.514, 0.890),
        5: (-0.380, -0.514, -0.890),
    }
    return elements, coordinates


def _bromomethane_geometry() -> tuple[dict[int, str], dict[int, tuple[float, float, float]]]:
    elements = {1: "C", 2: "Br", 3: "H", 4: "H", 5: "H"}
    coordinates = {
        1: (0.000, 0.000, 0.000),
        2: (1.939, 0.000, 0.000),  # C-Br ~1.94 Å
        3: (-0.380, 1.027, 0.000),
        4: (-0.380, -0.514, 0.890),
        5: (-0.380, -0.514, -0.890),
    }
    return elements, coordinates


def _chlorobromomethane_geometry() -> tuple[dict[int, str], dict[int, tuple[float, float, float]]]:
    # Carbon bonded to both Cl and Br (CHClBr-style geminal); Br should win.
    elements = {1: "C", 2: "Cl", 3: "Br", 4: "H", 5: "H"}
    coordinates = {
        1: (0.000, 0.000, 0.000),
        2: (1.776, 0.000, 0.000),
        3: (-0.900, 1.700, 0.000),
        4: (-0.500, -0.800, 0.900),
        5: (-0.500, -0.800, -0.900),
    }
    return elements, coordinates


class DetectHalogenNeighborsTests(unittest.TestCase):
    def test_detect_c_cl_and_adjacent_h(self) -> None:
        elements, coordinates = _chloromethane_geometry()
        bonds = infer_bonds(coordinates, elements)
        result = detect_halogen_neighbors(elements, bonds)
        self.assertEqual(result[1], "Cl")
        for h_id in (3, 4, 5):
            self.assertEqual(result[h_id], "Cl")

    def test_detect_c_br(self) -> None:
        elements, coordinates = _bromomethane_geometry()
        bonds = infer_bonds(coordinates, elements)
        result = detect_halogen_neighbors(elements, bonds)
        self.assertEqual(result[1], "Br")

    def test_geminal_picks_heaviest(self) -> None:
        elements, coordinates = _chlorobromomethane_geometry()
        bonds = infer_bonds(coordinates, elements)
        result = detect_halogen_neighbors(elements, bonds)
        self.assertEqual(result[1], "Br")
        # adjacent hydrogens inherit Br as well
        self.assertEqual(result[4], "Br")

    def test_no_halogen_returns_empty(self) -> None:
        # Methane: no halogens.
        elements = {1: "C", 2: "H", 3: "H", 4: "H", 5: "H"}
        coordinates = {
            1: (0.000, 0.000, 0.000),
            2: (0.629, 0.629, 0.629),
            3: (-0.629, -0.629, 0.629),
            4: (-0.629, 0.629, -0.629),
            5: (0.629, -0.629, -0.629),
        }
        bonds = infer_bonds(coordinates, elements)
        self.assertEqual(detect_halogen_neighbors(elements, bonds), {})


class MstdKeyTests(unittest.TestCase):
    def test_known_combinations(self) -> None:
        self.assertEqual(mstd_key("13C", "Cl", "sp2"), "C_Cl_sp2")
        self.assertEqual(mstd_key("1H", "Br", "sp3"), "H_Br_sp3")

    def test_unknown_hyb_returns_none(self) -> None:
        self.assertIsNone(mstd_key("13C", "Cl", "sp"))
        self.assertIsNone(mstd_key("13C", "Cl", "unknown"))

    def test_iodine_returns_none(self) -> None:
        self.assertNotIn("I", HALOGENS)
        self.assertIsNone(mstd_key("13C", "I", "sp3"))


class ApplyMstdUnscaledTests(unittest.TestCase):
    def test_formula(self) -> None:
        # std_tens=190, sigma=120, std_exp=70 -> 140
        entry = {"shielding_standard": 190.0, "reference_value": 70.0}
        self.assertAlmostEqual(apply_mstd_unscaled(120.0, entry), 140.0)


class MstdExtractorTests(unittest.TestCase):
    def test_extractor_reads_qm_mstd_workbook(self) -> None:
        if not MSTD_QM_WORKBOOK.exists():
            self.skipTest(f"{MSTD_QM_WORKBOOK} is not available")
        extracted = _extract_mstd_workbook(MSTD_QM_WORKBOOK)
        entry = extracted["B3LYP.6-31G(d,p)"]["C_Cl_sp2"]
        self.assertAlmostEqual(entry["shielding_standard"], 70.0715)
        self.assertAlmostEqual(entry["reference_value"], 117.42)


class BundledParameterTableMstdTests(unittest.TestCase):
    def test_bundled_table_contains_mstd_references(self) -> None:
        table = load_parameter_table(None)
        levels = table.get("levels", {})
        self.assertTrue(
            any(
                "mstd_reference" in params
                for level in levels.values()
                for params in level.get("nuclei", {}).values()
            )
        )
        fallback = levels[table["fallback_level"]]["nuclei"]
        self.assertEqual(
            sorted(fallback["13C"]["mstd_reference"]),
            ["C_Br_sp2", "C_Br_sp3", "C_Cl_sp2", "C_Cl_sp3"],
        )
        self.assertEqual(
            sorted(fallback["1H"]["mstd_reference"]),
            ["H_Br_sp2", "H_Br_sp3", "H_Cl_sp2", "H_Cl_sp3"],
        )


class ShiftReportCsvTests(unittest.TestCase):
    def test_shift_csv_includes_halo_and_pairing_fields(self) -> None:
        row = ShiftRow(
            atom_id=7,
            nucleus="1H",
            label="H-7a",
            exp_shift_ppm=3.0,
            predicted_shift_ppm=3.25,
            error_ppm=0.25,
            unscaled_shift_ppm=3.4,
            exchange_group="a",
            swapped_with=8,
            halogen_neighbor="Cl",
        )
        self.assertEqual(
            _shift_csv_fieldnames()[-4:],
            ["unscaled_shift_ppm", "exchange_group", "swapped_with", "halogen_neighbor"],
        )
        self.assertEqual(_shift_csv_row(row)[-4:], ["3.400000", "a", "8", "Cl"])


class ValidateParameterTableTests(unittest.TestCase):
    def _base_table(self, mstd_block: dict | None) -> dict:
        nucleus = {
            "scaling_input": "unscaled_shift",
            "intercept": 0.0,
            "slope": 1.0,
            "scaled_error": {"distribution": "normal", "mean": 0.0, "stddev": 1.0},
        }
        if mstd_block is not None:
            nucleus["mstd_reference"] = mstd_block
        return {
            "schema_version": 2,
            "sources": {"x": {"label": "test"}},
            "fallback_level": "L",
            "levels": {
                "L": {
                    "family": "DP4+",
                    "nuclei": {"1H": nucleus},
                }
            },
        }

    def test_table_without_mstd_validates(self) -> None:
        # Backwards-compatible: pre-existing tables keep validating.
        validate_parameter_table(self._base_table(None))

    def test_well_formed_mstd_validates(self) -> None:
        block = {"H_Cl_sp3": {"shielding_standard": 25.0, "reference_value": 3.5}}
        validate_parameter_table(self._base_table(block))

    def test_non_dict_mstd_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mstd_reference"):
            validate_parameter_table(self._base_table("oops"))  # type: ignore[arg-type]

    def test_missing_field_rejected(self) -> None:
        block = {"H_Cl_sp3": {"shielding_standard": 25.0}}
        with self.assertRaisesRegex(ValueError, "reference_value"):
            validate_parameter_table(self._base_table(block))


def _parameter_table_with_mstd(mstd_for_h: dict | None = None) -> dict:
    nucleus = {
        "scaling_input": "unscaled_shift",
        "intercept": 0.0,
        "slope": 1.0,
        "scaled_error": {
            "distribution": "normal",
            "mean": 0.0,
            "stddev": 1.0,
        },
        "unscaled_error": {
            "on_sp3_carbon": {"distribution": "normal", "mean": 0.0, "stddev": 1.0},
            "default": {"distribution": "normal", "mean": 0.0, "stddev": 1.0},
        },
    }
    if mstd_for_h is not None:
        nucleus["mstd_reference"] = mstd_for_h
    return {"nuclei": {"1H": nucleus}}


class HaloPipelineTests(unittest.TestCase):
    def _candidate(self, sigma: float) -> CandidateIsomer:
        candidate = CandidateIsomer(name="A", directory="A")
        candidate.averaged_shieldings = {"1H": {1: sigma}}
        candidate.atom_hybridizations = {1: "sp3"}
        candidate.halogen_neighbor = {1: "Cl"}
        candidate.tms_referenced_shifts = apply_tms_referencing(candidate, tms_1h=31.0, tms_13c=None)
        return candidate

    def test_tms_mode_uses_mstd_value(self) -> None:
        # MSTD: delta = std - sigma + ref. For sigma=25, std=28, ref=3.0 -> 6.0.
        # Without MSTD: delta = 31 - 25 = 6.0 also (coincidence chosen so ranking comparison stays clean).
        # Use std/ref that diverge to make MSTD distinct.
        mstd = {"H_Cl_sp3": {"shielding_standard": 30.0, "reference_value": 4.0}}
        # MSTD: 30 - 25 + 4 = 9.0 (whereas TMS path = 6.0).
        candidate = self._candidate(sigma=25.0)
        assignments = [ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=8.0)]
        sets = score_candidates_all_modes(
            [candidate],
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table_with_mstd(mstd),
        )
        tms = next(item for item in sets if item.mode == "tms")
        rows = {row.atom_id: row for row in tms.candidate_scores[0].shift_rows}
        self.assertAlmostEqual(rows[1].predicted_shift_ppm, 9.0)
        self.assertEqual(rows[1].halogen_neighbor, "Cl")
        self.assertAlmostEqual(rows[1].error_ppm, 1.0)

    def test_scaled_mode_uses_mstd_for_unscaled_term(self) -> None:
        mstd = {"H_Cl_sp3": {"shielding_standard": 30.0, "reference_value": 4.0}}
        candidate = self._candidate(sigma=25.0)
        assignments = [ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=8.0)]
        sets = score_candidates_all_modes(
            [candidate],
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table_with_mstd(mstd),
        )
        scaled = next(item for item in sets if item.mode == "scaled")
        rows = {row.atom_id: row for row in scaled.candidate_scores[0].shift_rows}
        self.assertAlmostEqual(rows[1].unscaled_shift_ppm, 9.0)
        self.assertEqual(rows[1].halogen_neighbor, "Cl")

    def test_missing_mstd_falls_back_with_warning(self) -> None:
        # Halogen present but parameter table has no mstd_reference block.
        candidate = self._candidate(sigma=25.0)
        assignments = [ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=8.0)]
        sets = score_candidates_all_modes(
            [candidate],
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table_with_mstd(None),
        )
        tms = next(item for item in sets if item.mode == "tms")
        rows = {row.atom_id: row for row in tms.candidate_scores[0].shift_rows}
        # No override applied -> tms predicted equals tms-referenced shift = 6.0
        self.assertAlmostEqual(rows[1].predicted_shift_ppm, 6.0)
        self.assertEqual(rows[1].halogen_neighbor, "")
        self.assertTrue(any("HALO override skipped" in w for w in tms.warnings))

    def test_non_halogen_atom_not_overridden(self) -> None:
        mstd = {"H_Cl_sp3": {"shielding_standard": 30.0, "reference_value": 4.0}}
        candidate = CandidateIsomer(name="A", directory="A")
        candidate.averaged_shieldings = {"1H": {1: 25.0}}
        candidate.atom_hybridizations = {1: "sp3"}
        # No halogen neighbor.
        candidate.halogen_neighbor = {}
        candidate.tms_referenced_shifts = apply_tms_referencing(candidate, tms_1h=31.0, tms_13c=None)
        assignments = [ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=8.0)]
        sets = score_candidates_all_modes(
            [candidate],
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table_with_mstd(mstd),
        )
        tms = next(item for item in sets if item.mode == "tms")
        rows = {row.atom_id: row for row in tms.candidate_scores[0].shift_rows}
        self.assertAlmostEqual(rows[1].predicted_shift_ppm, 6.0)
        self.assertEqual(rows[1].halogen_neighbor, "")
        self.assertFalse(any("HALO override" in w for w in tms.warnings))


if __name__ == "__main__":
    unittest.main()
