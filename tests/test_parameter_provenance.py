import csv
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dp4_platform.dp4 import load_parameter_table, resolve_level_match, validate_parameter_table
from tools.merge_extended_dp4_parameters import merge_parameter_file


class ParameterProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = load_parameter_table(None)

    def test_bundled_v2_table_has_expected_sources_and_counts(self) -> None:
        self.assertEqual(self.table.get("schema_version"), 2)
        self.assertEqual(len(self.table.get("levels", {})), 60)
        sources = self.table.get("sources", {})
        self.assertEqual(sources["dp4plus_2015"]["doi"], "10.1021/acs.joc.5b02396")
        self.assertEqual(sources["dp4plus_app_2023"]["doi"], "10.1021/acs.jnatprod.3c00566")

        families = {}
        for level in self.table["levels"].values():
            families[level["family"]] = families.get(level["family"], 0) + 1
            self.assertTrue({"1H", "13C"} & set(level.get("nuclei", {})))
            for params in level.get("nuclei", {}).values():
                self.assertIn("scaled_error", params)
                self.assertEqual(params["scaled_error"]["distribution"], "student_t_tail")
                self.assertIn(params.get("scaling_input"), {"unscaled_shift", "shielding"})
        self.assertEqual(families["DP4+"], 24)
        self.assertEqual(families["MM-DP4+"], 36)

    def test_level_alias_matching_covers_common_notations(self) -> None:
        cases = {
            "mPW1PW91/6-31+G**": "DP4+/mPW1PW91/6-31+G(d,p)",
            "B3LYP/6-31G(d)": "DP4+/B3LYP/6-31G(d)",
            "PCM/mPW1PW91/6-31+G(d,p)": "DP4+/PCM/mPW1PW91/6-31+G(d,p)",
            "SMD/wB97XD/6-311+G**": "MM-DP4+/SMD/wB97XD/6-311+G(d,p)",
        }
        for requested, expected in cases.items():
            with self.subTest(requested=requested):
                match = resolve_level_match(self.table, requested)
                self.assertTrue(match["matched"])
                self.assertFalse(match["fallback"])
                self.assertEqual(match["level_name"], expected)

    def test_unmatched_level_returns_fallback_with_warning_and_candidates(self) -> None:
        match = resolve_level_match(self.table, "totally/missing/level")
        self.assertFalse(match["matched"])
        self.assertTrue(match["fallback"])
        self.assertEqual(match["level_name"], self.table["fallback_level"])
        self.assertTrue(match["warnings"])

    def test_extended_parameter_csv_import_adds_strict_levels_and_aliases(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base_path = temp / "base.json"
            rows_path = temp / "extended.csv"
            base_path.write_text(
                json.dumps(self.table, ensure_ascii=False),
                encoding="utf-8",
            )
            rows_path.write_text(_extended_rows_csv(), encoding="utf-8")

            merged, audit = merge_parameter_file(
                base_path,
                rows_path,
                source_id="ijms_2023_lobatolide_supplement",
                source_label="IJMS 2023 Lobatolide H supplementary parameters",
                source_doi="10.3390/ijms24065841",
            )

        validate_parameter_table(merged)
        self.assertIn("ijms_2023_lobatolide_supplement", merged["sources"])
        self.assertIn("DP4+/mPW1PW91/6-311+G(2d,p)", merged["levels"])
        self.assertIn("DP4+/SMD/mPW1PW91/6-311+G(2d,p)", merged["levels"])
        self.assertEqual(
            {item["level_key"] for item in audit["added_levels"]},
            {
                "DP4+/SMD/mPW1PW91/6-311+G(2d,p)",
                "DP4+/mPW1PW91/6-311+G(2d,p)",
            },
        )

        gas_match = resolve_level_match(merged, "mPW1PW91/6-311+G(2d,p)")
        self.assertTrue(gas_match["matched"])
        self.assertEqual(gas_match["level_name"], "DP4+/mPW1PW91/6-311+G(2d,p)")
        smd_match = resolve_level_match(merged, "SMD/mPW1PW91/6-311+G(2d,p)")
        self.assertTrue(smd_match["matched"])
        self.assertEqual(smd_match["level_name"], "DP4+/SMD/mPW1PW91/6-311+G(2d,p)")

        existing_dp_match = resolve_level_match(merged, "mPW1PW91/6-311+G(d,p)")
        self.assertEqual(existing_dp_match["level_name"], "DP4+/mPW1PW91/6-311+G(d,p)")

    def test_extended_parameter_csv_rejects_incomplete_and_scaling_only_levels(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base_path = temp / "base.json"
            rows_path = temp / "extended.csv"
            base_path.write_text(
                json.dumps(self.table, ensure_ascii=False),
                encoding="utf-8",
            )
            rows_path.write_text(_rejected_rows_csv(), encoding="utf-8")

            merged, audit = merge_parameter_file(
                base_path,
                rows_path,
                source_id="ijms_2023_lobatolide_supplement",
                source_label="IJMS 2023 Lobatolide H supplementary parameters",
                source_doi="10.3390/ijms24065841",
            )

        self.assertNotIn("DP4+/B3LYP/6-311+G(2d,p)", merged["levels"])
        self.assertNotIn("DP4+/M062x/6-311+G(2d,p)", merged["levels"])
        self.assertEqual(
            audit["rejected_incomplete"][0]["level_key"],
            "DP4+/B3LYP/6-311+G(2d,p)",
        )
        self.assertEqual(
            audit["rejected_scaling_only"][0]["level_key"],
            "DP4+/M062x/6-311+G(2d,p)",
        )


def _csv_lines(rows: list[list[object]]) -> str:
    header = [
        "family",
        "method",
        "basis",
        "solvent_model",
        "row_label",
        "m",
        "s",
        "n",
        "reference_13c",
        "reference_1h",
        "slope",
        "intercept",
        "mae",
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        padded = list(row) + [""] * (len(header) - len(row))
        writer.writerow(padded)
    return buffer.getvalue()


def _complete_level_rows(method: str, solvent_model: str) -> list[list[object]]:
    basis = "6-311+G(2d,p)"
    return [
        ["DP4+", method, basis, solvent_model, "Csp2", -1.1, 2.1, 5.1, "", ""],
        ["DP4+", method, basis, solvent_model, "Csp3", -1.2, 2.2, 5.2, "", ""],
        ["DP4+", method, basis, solvent_model, "Hsp2", -0.1, 0.21, 6.1, "", ""],
        ["DP4+", method, basis, solvent_model, "Hsp3", -0.2, 0.22, 6.2, "", ""],
        ["DP4+", method, basis, solvent_model, "Csca", 0.0, 1.5, 7.1, 196.0, ""],
        ["DP4+", method, basis, solvent_model, "Hsca", 0.0, 0.15, 7.2, "", 31.5],
    ]


def _extended_rows_csv() -> str:
    return _csv_lines(
        _complete_level_rows("mPW1PW91", "GAS")
        + _complete_level_rows("mPW1PW91", "SMD")
    )


def _rejected_rows_csv() -> str:
    return _csv_lines(
        [
            ["DP4+", "B3LYP", "6-311+G(2d,p)", "GAS", "Csp2", -1.1, 2.1, 5.1],
            ["DP4+", "B3LYP", "6-311+G(2d,p)", "GAS", "Csp3", -1.2, 2.2, 5.2],
            ["DP4+", "M062x", "6-311+G(2d,p)", "GAS", "slope", "", "", "", "", "", 0.98, 1.2, 1.9],
            ["DP4+", "M062x", "6-311+G(2d,p)", "GAS", "intercept", "", "", "", "", "", 0.98, 1.2, 1.9],
        ]
    )


if __name__ == "__main__":
    unittest.main()
