from __future__ import annotations

import os
import tempfile
import unittest

from dp4_platform.config import DP4Config
from dp4_platform.diastereotopic import reassign_diastereotopic_pairs
from dp4_platform.dp4 import (
    apply_tms_referencing,
    score_candidates_all_modes,
)
from dp4_platform.experimental import load_experimental_assignments
from dp4_platform.models import CandidateIsomer, ExperimentalAssignment


def _parameter_table_unscaled() -> dict:
    return {
        "nuclei": {
            "1H": {
                "scaling_input": "unscaled_shift",
                "intercept": 0.0,
                "slope": 1.0,
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


class ReassignDiastereotopicPairsTests(unittest.TestCase):
    def test_swap_when_inverted_in_shift_sense(self) -> None:
        assignments = [
            ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=4.0, exchange_group="a"),
            ExperimentalAssignment(candidate_atom_id=2, nucleus="1H", exp_shift_ppm=2.0, exchange_group="a"),
        ]
        # calc says atom 1 -> 2.5, atom 2 -> 4.5; in shift sense the larger
        # exp delta (atom 1, 4.0) should receive the larger calc delta (4.5).
        rewritten, swaps = reassign_diastereotopic_pairs(
            assignments, {1: 2.5, 2: 4.5}, sense="shift"
        )
        self.assertEqual(rewritten, {1: 4.5, 2: 2.5})
        self.assertEqual(swaps, [(1, 2)])

    def test_no_swap_when_aligned(self) -> None:
        assignments = [
            ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=4.0, exchange_group="a"),
            ExperimentalAssignment(candidate_atom_id=2, nucleus="1H", exp_shift_ppm=2.0, exchange_group="a"),
        ]
        rewritten, swaps = reassign_diastereotopic_pairs(
            assignments, {1: 4.5, 2: 2.5}, sense="shift"
        )
        self.assertEqual(rewritten, {1: 4.5, 2: 2.5})
        self.assertEqual(swaps, [])

    def test_shielding_sense_inverts_relationship(self) -> None:
        assignments = [
            ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=4.0, exchange_group="a"),
            ExperimentalAssignment(candidate_atom_id=2, nucleus="1H", exp_shift_ppm=2.0, exchange_group="a"),
        ]
        # In shielding sense the larger exp delta (atom 1) should receive the
        # smaller sigma. Calc says sigma_1 = 28, sigma_2 = 25; that's already
        # backwards (atom 1 has larger sigma), so we expect a swap.
        rewritten, swaps = reassign_diastereotopic_pairs(
            assignments, {1: 28.0, 2: 25.0}, sense="shielding"
        )
        self.assertEqual(rewritten, {1: 25.0, 2: 28.0})
        self.assertEqual(swaps, [(1, 2)])

    def test_atoms_without_exchange_group_untouched(self) -> None:
        assignments = [
            ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=4.0),
            ExperimentalAssignment(candidate_atom_id=2, nucleus="1H", exp_shift_ppm=2.0),
        ]
        rewritten, swaps = reassign_diastereotopic_pairs(
            assignments, {1: 2.5, 2: 4.5}, sense="shift"
        )
        self.assertEqual(rewritten, {1: 2.5, 2: 4.5})
        self.assertEqual(swaps, [])

    def test_invalid_sense_raises(self) -> None:
        with self.assertRaises(ValueError):
            reassign_diastereotopic_pairs([], {}, sense="bogus")


class ExchangeGroupCsvLoaderTests(unittest.TestCase):
    def _write_csv(self, content: str) -> str:
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        fh.write(content)
        fh.close()
        self.addCleanup(os.remove, fh.name)
        return fh.name

    def test_loader_accepts_paired_rows(self) -> None:
        path = self._write_csv(
            "candidate_atom_id,nucleus,exp_shift_ppm,exchange_group\n"
            "1,1H,4.0,a\n"
            "2,1H,2.0,a\n"
            "3,1H,1.5,\n"
        )
        loaded = load_experimental_assignments(path, ("1H", "13C"))
        self.assertEqual(loaded[0].exchange_group, "a")
        self.assertEqual(loaded[1].exchange_group, "a")
        self.assertEqual(loaded[2].exchange_group, "")

    def test_loader_rejects_unpaired_group(self) -> None:
        path = self._write_csv(
            "candidate_atom_id,nucleus,exp_shift_ppm,exchange_group\n"
            "1,1H,4.0,a\n"
            "2,1H,2.0,\n"
        )
        with self.assertRaisesRegex(ValueError, "exchange_group 'a'"):
            load_experimental_assignments(path, ("1H", "13C"))

    def test_loader_rejects_three_member_group(self) -> None:
        path = self._write_csv(
            "candidate_atom_id,nucleus,exp_shift_ppm,exchange_group\n"
            "1,1H,4.0,a\n"
            "2,1H,3.0,a\n"
            "3,1H,2.0,a\n"
        )
        with self.assertRaisesRegex(ValueError, "exchange_group 'a'"):
            load_experimental_assignments(path, ("1H", "13C"))

    def test_loader_rejects_mixed_nucleus_group(self) -> None:
        path = self._write_csv(
            "candidate_atom_id,nucleus,exp_shift_ppm,exchange_group\n"
            "1,1H,4.0,a\n"
            "2,13C,40.0,a\n"
        )
        with self.assertRaisesRegex(ValueError, "share the same nucleus"):
            load_experimental_assignments(path, ("1H", "13C"))


class DiastereotopicPipelineTests(unittest.TestCase):
    def test_swap_recorded_in_shift_rows(self) -> None:
        candidate = CandidateIsomer(name="A", directory="A")
        # atom 1 sigma=28 (sp2 environment-like) and atom 2 sigma=25 -- but
        # the experiment says atom 1 has the larger delta (4.0) and atom 2 the
        # smaller (2.0). In tms mode (shift sense) the calc deltas are
        # 31-28=3 and 31-25=6, so atom 1 has the smaller calc delta. The
        # swap should reassign so atom 1 gets the larger calc delta (6).
        candidate.averaged_shieldings = {"1H": {1: 28.0, 2: 25.0}}
        candidate.tms_referenced_shifts = apply_tms_referencing(candidate, tms_1h=31.0, tms_13c=None)
        candidate.atom_hybridizations = {1: "sp3", 2: "sp3"}

        assignments = [
            ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=4.0, exchange_group="a"),
            ExperimentalAssignment(candidate_atom_id=2, nucleus="1H", exp_shift_ppm=2.0, exchange_group="a"),
        ]

        sets = score_candidates_all_modes(
            [candidate],
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table_unscaled(),
        )
        tms = next(item for item in sets if item.mode == "tms")
        rows = {row.atom_id: row for row in tms.candidate_scores[0].shift_rows}
        self.assertAlmostEqual(rows[1].predicted_shift_ppm, 6.0)
        self.assertAlmostEqual(rows[2].predicted_shift_ppm, 3.0)
        self.assertEqual(rows[1].exchange_group, "a")
        self.assertEqual(rows[1].swapped_with, 2)
        self.assertEqual(rows[2].swapped_with, 1)

    def test_no_swap_when_already_aligned(self) -> None:
        candidate = CandidateIsomer(name="A", directory="A")
        candidate.averaged_shieldings = {"1H": {1: 25.0, 2: 28.0}}
        candidate.tms_referenced_shifts = apply_tms_referencing(candidate, tms_1h=31.0, tms_13c=None)
        candidate.atom_hybridizations = {1: "sp3", 2: "sp3"}

        assignments = [
            ExperimentalAssignment(candidate_atom_id=1, nucleus="1H", exp_shift_ppm=4.0, exchange_group="a"),
            ExperimentalAssignment(candidate_atom_id=2, nucleus="1H", exp_shift_ppm=2.0, exchange_group="a"),
        ]

        sets = score_candidates_all_modes(
            [candidate],
            assignments,
            DP4Config(nuclei=("1H",)),
            _parameter_table_unscaled(),
        )
        tms = next(item for item in sets if item.mode == "tms")
        rows = {row.atom_id: row for row in tms.candidate_scores[0].shift_rows}
        self.assertIsNone(rows[1].swapped_with)
        self.assertIsNone(rows[2].swapped_with)


if __name__ == "__main__":
    unittest.main()
