from __future__ import annotations

import tempfile
import unittest
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from dp4_platform.autoassign import build_candidate_predictions
from dp4_platform.config import DP4Config
from dp4_platform.energy import boltzmann_average_shieldings, compute_boltzmann_weights
from dp4_platform.models import FileRole
from dp4_platform.parser import discover_candidate_files, load_candidate_from_directory, pair_discovered_files


ORCA_COMBINED_TEXT = """\
FINAL SINGLE POINT ENERGY      -100.123456
VIBRATIONAL FREQUENCIES
 1: 15.0 cm**-1
 2: 45.0 cm**-1

CARTESIAN COORDINATES (ANGSTROEM)
------------------------------
C    0.000000    0.000000    0.000000
H    0.000000    0.000000    1.089000

1 C isotropic shielding : 120.0000
2 H isotropic shielding : 30.0000
"""


ORCA_OPT_TEXT = """\
FINAL SINGLE POINT ENERGY      -100.223456
VIBRATIONAL FREQUENCIES
 1: 22.0 cm**-1
 2: 54.0 cm**-1

CARTESIAN COORDINATES (ANGSTROEM)
------------------------------
C    0.000000    0.000000    0.000000
H    0.000000    0.000000    1.089000
"""


ORCA_NMR_TEXT = """\
1 C isotropic shielding : 121.0000
2 H isotropic shielding : 31.0000
"""


GAUSSIAN_OPT_TEXT = """\
Entering Gaussian System, Link 0=g16
SCF Done:  E(RB3LYP) =  -233.699703238     A.U. after    1 cycles
                         Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          6           0        0.000000    0.000000    0.000000
      2          1           0        0.000000    0.000000    1.089000
 ---------------------------------------------------------------------
 Frequencies --    211.0197               272.2704               280.5689
 Sum of electronic and thermal Free Energies=         -233.592383
 Normal termination of Gaussian 16
"""


GAUSSIAN_NMR_TEXT = """\
Entering Gaussian System, Link 0=g16
SCF Done:  E(RB3LYP) =  -233.767757924     A.U. after    8 cycles
                         Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          6           0        0.000000    0.000000    0.000000
      2          1           0        0.000000    0.000000    1.089000
 ---------------------------------------------------------------------
      1  C    Isotropic =   149.3254   Anisotropy =    51.0548
      2  H    Isotropic =    30.9527   Anisotropy =     7.0146
 Normal termination of Gaussian 16
"""


class ParserSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.gaussian_fixture = self.repo_root / "tests" / "fixtures" / "gaussian_example.log"
        self.default_config = DP4Config()

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @contextmanager
    def _workspace_tempdir(self):
        base = self.repo_root / "tests_runtime"
        base.mkdir(exist_ok=True)
        tmpdir = base / f"case_{uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            yield tmpdir
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_orca_combined_classification_and_parse(self) -> None:
        with self._workspace_tempdir() as tmpdir:
            candidate_dir = tmpdir / "isomer_a"
            file_path = candidate_dir / "conf-1.out"
            self._write(file_path, ORCA_COMBINED_TEXT)

            discovered = discover_candidate_files(str(candidate_dir), self.default_config)
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0].program, "orca")
            self.assertEqual(discovered[0].role, FileRole.COMBINED)

            candidate = load_candidate_from_directory("isomer_a", str(candidate_dir), self.default_config)
            record = candidate.collection.all_records[0]
            self.assertAlmostEqual(record.scf_energy or 0.0, -100.123456, places=6)
            self.assertEqual(sorted(record.shieldings_by_nucleus), ["13C", "1H"])
            self.assertTrue(record.coordinates)

    def test_orca_split_opt_nmr_flow_still_loads(self) -> None:
        with self._workspace_tempdir() as tmpdir:
            candidate_dir = tmpdir / "isomer_b"
            self._write(candidate_dir / "conf-1_opt.out", ORCA_OPT_TEXT)
            self._write(candidate_dir / "conf-1_nmr.out", ORCA_NMR_TEXT)

            candidate = load_candidate_from_directory("isomer_b", str(candidate_dir), self.default_config)
            self.assertEqual(len(candidate.collection.all_records), 1)
            record = candidate.collection.all_records[0]
            self.assertTrue(record.is_paired())
            self.assertIn("13C", record.shieldings_by_nucleus)

    def test_gaussian_example_combined_is_detected_and_parsed(self) -> None:
        config = DP4Config(program_mode="auto")
        discovered = discover_candidate_files(str(self.gaussian_fixture.parent), config)
        target = next(info for info in discovered if info.path == str(self.gaussian_fixture.resolve()))
        self.assertEqual(target.program, "gaussian")
        self.assertEqual(target.role, FileRole.COMBINED)

        candidate = load_candidate_from_directory("gaussian_combined", str(self.gaussian_fixture.parent), config)
        target_record = next(record for record in candidate.collection.all_records if Path(record.source_file or "").name == self.gaussian_fixture.name)
        self.assertAlmostEqual(target_record.scf_energy or 0.0, -233.767757924, places=6)
        self.assertAlmostEqual(target_record.gibbs_energy or 0.0, -233.592383, places=6)
        self.assertTrue(target_record.frequencies)
        self.assertTrue(target_record.coordinates)
        self.assertIn("13C", target_record.shieldings_by_nucleus)
        self.assertIn("1H", target_record.shieldings_by_nucleus)

    def test_gaussian_split_supports_conf_id_and_filename_pairing(self) -> None:
        with self._workspace_tempdir() as tmpdir:
            by_conf_dir = tmpdir / "by_conf"
            self._write(by_conf_dir / "conf-1_opt.log", GAUSSIAN_OPT_TEXT)
            self._write(by_conf_dir / "conf-1_nmr.log", GAUSSIAN_NMR_TEXT)

            candidate = load_candidate_from_directory("gaussian_conf", str(by_conf_dir), DP4Config(program_mode="gaussian"))
            self.assertEqual(len(candidate.collection.all_records), 1)
            compute_boltzmann_weights(candidate, DP4Config(program_mode="gaussian"))
            averaged = boltzmann_average_shieldings(candidate, ("1H", "13C"))
            self.assertIn("13C", averaged)

            by_name_dir = tmpdir / "by_name"
            self._write(by_name_dir / "alpha-opt.log", GAUSSIAN_OPT_TEXT)
            self._write(by_name_dir / "alpha-nmr.log", GAUSSIAN_NMR_TEXT)
            discovered = discover_candidate_files(str(by_name_dir), DP4Config(program_mode="gaussian", auto_pair_strategy="filename"))
            paired, unpaired_opt, unpaired_nmr = pair_discovered_files(
                discovered,
                DP4Config(program_mode="gaussian", auto_pair_strategy="filename"),
            )
            self.assertEqual(len(paired), 1)
            self.assertFalse(unpaired_opt)
            self.assertFalse(unpaired_nmr)

    def test_program_mode_overrides_and_mixed_programs_error(self) -> None:
        gaussian_dir = str(self.gaussian_fixture.parent)
        auto_info = next(info for info in discover_candidate_files(gaussian_dir, DP4Config(program_mode="auto")) if Path(info.path).name == self.gaussian_fixture.name)
        gaussian_info = next(info for info in discover_candidate_files(gaussian_dir, DP4Config(program_mode="gaussian")) if Path(info.path).name == self.gaussian_fixture.name)
        orca_info = next(info for info in discover_candidate_files(gaussian_dir, DP4Config(program_mode="orca")) if Path(info.path).name == self.gaussian_fixture.name)
        self.assertEqual(auto_info.program, "gaussian")
        self.assertEqual(gaussian_info.role, FileRole.COMBINED)
        self.assertEqual(orca_info.role, FileRole.UNKNOWN)

        with self._workspace_tempdir() as tmpdir:
            candidate_dir = tmpdir / "mixed_candidate"
            self._write(candidate_dir / "conf-1.out", ORCA_COMBINED_TEXT)
            self._write(candidate_dir / "conf-2.log", GAUSSIAN_NMR_TEXT)
            with self.assertRaisesRegex(ValueError, "Mixed quantum chemistry programs"):
                discover_candidate_files(str(candidate_dir), DP4Config(program_mode="auto"))

    def test_gaussian_predictions_flow_runs_without_algorithm_changes(self) -> None:
        with self._workspace_tempdir() as tmpdir:
            candidate_dir = tmpdir / "gaussian_predict"
            target = candidate_dir / "000055.log"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.gaussian_fixture.read_bytes())

            candidate, predicted, elements, coordinates = build_candidate_predictions(
                "gaussian_predict",
                str(candidate_dir),
                DP4Config(program_mode="auto"),
            )
            self.assertTrue(candidate.collection.usable_records)
            self.assertIn("13C", predicted)
            self.assertTrue(elements)
            self.assertTrue(coordinates)


if __name__ == "__main__":
    unittest.main()
