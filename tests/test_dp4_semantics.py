from __future__ import annotations

import unittest

from dp4_platform.config import DP4Config
from dp4_platform.dp4 import (
    apply_tms_referencing,
    build_scaled_input_maps,
    per_isomer_linear_fits,
    scaled_regression_modes,
    score_candidates_all_modes,
)
from dp4_platform.models import CandidateIsomer, ExperimentalAssignment
from dp4_platform.pipeline import select_reference_shielding


def _candidate(name: str, shielding: float) -> CandidateIsomer:
    candidate = CandidateIsomer(name=name, directory=name)
    candidate.averaged_shieldings = {"1H": {1: shielding}}
    candidate.atom_hybridizations = {1: "sp3"}
    return candidate


def _parameter_table(scaling_input: str) -> dict:
    return {
        "nuclei": {
            "1H": {
                "scaling_input": scaling_input,
                "intercept": 0.0 if scaling_input == "unscaled_shift" else 31.0,
                "slope": 1.0 if scaling_input == "unscaled_shift" else -1.0,
                "scaled_error": {
                    "distribution": "normal",
                    "mean": 0.0,
                    "stddev": 1.0,
                },
                "unscaled_error": {
                    "on_sp3_carbon": {
                        "distribution": "normal",
                        "mean": 0.0,
                        "stddev": 1.0,
                    },
                    "default": {
                        "distribution": "normal",
                        "mean": 0.0,
                        "stddev": 1.0,
                    },
                },
            }
        }
    }


class DP4SemanticTests(unittest.TestCase):
    def test_tms_referencing_returns_unscaled_shift_without_mutating_shieldings(self) -> None:
        candidate = _candidate("A", 25.0)

        referenced = apply_tms_referencing(candidate, tms_1h=31.0, tms_13c=None)

        self.assertEqual(referenced, {"1H": {1: 6.0}})
        self.assertEqual(candidate.averaged_shieldings, {"1H": {1: 25.0}})

    def test_unscaled_shift_modes_are_unavailable_without_tms(self) -> None:
        candidates = [_candidate("A", 25.0), _candidate("B", 24.0)]
        assignments = [ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=6.0)]

        sets = score_candidates_all_modes(
            candidates,
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table("unscaled_shift"),
        )

        raw = next(item for item in sets if item.mode == "raw")
        tms = next(item for item in sets if item.mode == "tms")
        scaled = next(item for item in sets if item.mode == "scaled")
        self.assertEqual(len(raw.candidate_scores), 2)
        self.assertEqual(tms.candidate_scores, [])
        self.assertEqual(scaled.candidate_scores, [])
        self.assertTrue(any("TMS-referenced" in warning for warning in scaled.warnings))

    def test_tms_and_standard_scaled_modes_use_unscaled_shift_when_tms_is_available(self) -> None:
        candidates = [_candidate("A", 25.0), _candidate("B", 24.0)]
        for candidate in candidates:
            candidate.tms_referenced_shifts = apply_tms_referencing(candidate, tms_1h=31.0, tms_13c=None)
        assignments = [ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=6.0)]

        sets = score_candidates_all_modes(
            candidates,
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table("unscaled_shift"),
        )

        tms = next(item for item in sets if item.mode == "tms")
        scaled = next(item for item in sets if item.mode == "scaled")
        self.assertEqual(tms.ranking[0].candidate_name, "A")
        self.assertEqual(scaled.ranking[0].candidate_name, "A")
        self.assertAlmostEqual(tms.ranking[0].shift_rows[0].predicted_shift_ppm, 6.0)
        self.assertAlmostEqual(scaled.ranking[0].shift_rows[0].predicted_shift_ppm, 6.0)

    def test_unscaled_error_uses_calc_minus_exp_sign(self) -> None:
        candidates = [_candidate("calc_plus_two", 0.0), _candidate("calc_minus_two", 0.0)]
        candidates[0].tms_referenced_shifts = {"1H": {1: 10.0}}
        candidates[1].tms_referenced_shifts = {"1H": {1: 6.0}}
        for candidate in candidates:
            candidate.atom_hybridizations = {1: "sp3"}
        table = _parameter_table("unscaled_shift")
        table["nuclei"]["1H"]["unscaled_error"]["on_sp3_carbon"] = {
            "distribution": "normal",
            "mean": 2.0,
            "stddev": 0.1,
        }
        table["nuclei"]["1H"]["unscaled_error"]["default"] = {
            "distribution": "normal",
            "mean": 2.0,
            "stddev": 0.1,
        }
        assignments = [ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=8.0)]

        sets = score_candidates_all_modes(
            candidates,
            assignments,
            DP4Config(nuclei=("1H",)),
            table,
        )

        tms = next(item for item in sets if item.mode == "tms")
        self.assertEqual(tms.ranking[0].candidate_name, "calc_plus_two")
        self.assertAlmostEqual(tms.ranking[0].shift_rows[0].error_ppm, 2.0)

    def test_dp4app_scaled_regression_fits_computed_against_experimental(self) -> None:
        candidate = _candidate("A", 0.0)
        candidate.averaged_shieldings = {"1H": {1: 0.0, 2: 0.0, 3: 0.0}}
        candidate.tms_referenced_shifts = {"1H": {1: 25.0, 2: 45.0, 3: 65.0}}
        candidate.atom_hybridizations = {1: "sp3", 2: "sp3", 3: "sp3"}
        assignments = [
            ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=10.0),
            ExperimentalAssignment(candidate_atom_id=2, nucleus="1H", exp_shift_ppm=20.0),
            ExperimentalAssignment(candidate_atom_id=3, nucleus="1H", exp_shift_ppm=30.0),
        ]
        config = DP4Config(nuclei=("1H",))
        table = _parameter_table("unscaled_shift")
        scaled_maps, scaled_nuclei, _warnings, _formula = build_scaled_input_maps(
            [candidate],
            config,
            table,
        )

        fits = per_isomer_linear_fits(
            [candidate],
            assignments,
            scaled_nuclei,
            value_maps_by_candidate=scaled_maps,
            regression_modes_by_nucleus=scaled_regression_modes(table, scaled_nuclei),
        )

        self.assertEqual(len(fits), 1)
        self.assertAlmostEqual(fits[0].intercept, 5.0)
        self.assertAlmostEqual(fits[0].slope, 2.0)

        sets = score_candidates_all_modes(
            [candidate],
            assignments,
            config,
            table,
            linear_fits=fits,
        )
        scaled = next(item for item in sets if item.mode == "scaled")
        predicted = {
            row.atom_id: row.predicted_shift_ppm
            for row in scaled.ranking[0].shift_rows
        }
        self.assertAlmostEqual(predicted[1], 10.0)
        self.assertAlmostEqual(predicted[2], 20.0)
        self.assertAlmostEqual(predicted[3], 30.0)

    def test_dp4app_inverse_regression_is_not_direct_ols_on_imperfect_data(self) -> None:
        candidate = _candidate("A", 0.0)
        candidate.averaged_shieldings = {"1H": {1: 0.0, 2: 0.0, 3: 0.0}}
        candidate.tms_referenced_shifts = {"1H": {1: 10.0, 2: 25.0, 3: 29.0}}
        candidate.atom_hybridizations = {1: "sp3", 2: "sp3", 3: "sp3"}
        assignments = [
            ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=8.0),
            ExperimentalAssignment(candidate_atom_id=2, nucleus="1H", exp_shift_ppm=18.0),
            ExperimentalAssignment(candidate_atom_id=3, nucleus="1H", exp_shift_ppm=31.0),
        ]
        config = DP4Config(nuclei=("1H",))
        table = _parameter_table("unscaled_shift")
        scaled_maps, scaled_nuclei, _warnings, _formula = build_scaled_input_maps(
            [candidate],
            config,
            table,
        )
        fits = per_isomer_linear_fits(
            [candidate],
            assignments,
            scaled_nuclei,
            value_maps_by_candidate=scaled_maps,
            regression_modes_by_nucleus=scaled_regression_modes(table, scaled_nuclei),
        )
        inverse_fit = fits[0]
        direct_fits = per_isomer_linear_fits(
            [candidate],
            assignments,
            scaled_nuclei,
            value_maps_by_candidate=scaled_maps,
            regression_modes_by_nucleus={"1H": "direct"},
        )
        direct_fit = direct_fits[0]
        atom_two_calc = candidate.tms_referenced_shifts["1H"][2]
        inverse_prediction = (atom_two_calc - inverse_fit.intercept) / inverse_fit.slope
        direct_prediction = direct_fit.intercept + direct_fit.slope * atom_two_calc

        sets = score_candidates_all_modes(
            [candidate],
            assignments,
            config,
            table,
            linear_fits=fits,
        )
        scaled = next(item for item in sets if item.mode == "scaled")
        actual_atom_two = {
            row.atom_id: row.predicted_shift_ppm
            for row in scaled.ranking[0].shift_rows
        }[2]

        self.assertNotAlmostEqual(inverse_prediction, direct_prediction)
        self.assertAlmostEqual(actual_atom_two, inverse_prediction)

    def test_shielding_domain_scaled_mode_runs_without_tms(self) -> None:
        candidates = [_candidate("A", 25.0), _candidate("B", 24.0)]
        assignments = [ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=6.0)]

        sets = score_candidates_all_modes(
            candidates,
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table("shielding"),
        )

        scaled = next(item for item in sets if item.mode == "scaled")
        self.assertEqual(scaled.ranking[0].candidate_name, "A")
        self.assertAlmostEqual(scaled.ranking[0].shift_rows[0].predicted_shift_ppm, 6.0)
        self.assertTrue(any("uDP4+" in warning for warning in scaled.warnings))

    def test_reference_shielding_selection_uses_requested_solvent(self) -> None:
        level_data = {
            "reference_shielding": {"13C": 183.888775, "1H": 31.901641666667},
            "reference_shielding_by_solvent": {
                "CHCl3": {"13C": 183.888775, "1H": 31.901641666667},
                "DMSO": {"13C": 184.852125, "1H": 32.015216666667},
            },
        }

        reference, solvent, warnings = select_reference_shielding(level_data, "dmso")

        self.assertEqual(solvent, "DMSO")
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(reference["13C"], 184.852125)
        self.assertAlmostEqual(reference["1H"], 32.015216666667)

    def test_reference_shielding_selection_warns_and_falls_back(self) -> None:
        level_data = {
            "reference_shielding": {"13C": 183.888775, "1H": 31.901641666667},
            "reference_shielding_by_solvent": {
                "CHCl3": {"13C": 183.888775, "1H": 31.901641666667},
            },
        }

        reference, solvent, warnings = select_reference_shielding(level_data, "DMSO")

        self.assertEqual(solvent, "CHCl3")
        self.assertTrue(warnings)
        self.assertAlmostEqual(reference["13C"], 183.888775)


if __name__ == "__main__":
    unittest.main()
