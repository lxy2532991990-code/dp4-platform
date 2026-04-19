from __future__ import annotations

import unittest
from unittest.mock import patch

from dp4_platform.structure_model import build_c_h_adjacency, infer_bonds
from dp4_platform.structure2d import Chem, compute_rdkit_2d_coordinates


class StructureModelTests(unittest.TestCase):
    def test_infer_bonds_detects_short_c_h_and_c_c_distances(self) -> None:
        coordinates = {
            1: (0.0, 0.0, 0.0),
            2: (1.09, 0.0, 0.0),
            3: (0.0, 1.50, 0.0),
            4: (5.0, 5.0, 5.0),
        }
        elements = {1: "C", 2: "H", 3: "C", 4: "H"}

        bonds = set(infer_bonds(coordinates, elements))

        self.assertIn((1, 2), bonds)
        self.assertIn((1, 3), bonds)
        self.assertNotIn((1, 4), bonds)

    def test_infer_bonds_handles_empty_coordinates(self) -> None:
        self.assertEqual(infer_bonds({}, {}), [])

    def test_build_c_h_adjacency_detects_ch_group(self) -> None:
        coordinates = {
            1: (0.0, 0.0, 0.0),
            2: (1.09, 0.0, 0.0),
        }
        elements = {1: "C", 2: "H"}

        hydrogens_by_carbon, carbon_by_hydrogen = build_c_h_adjacency(coordinates, elements)

        self.assertEqual(hydrogens_by_carbon, {1: [2]})
        self.assertEqual(carbon_by_hydrogen, {2: 1})

    def test_build_c_h_adjacency_detects_ch2_and_ch3_groups(self) -> None:
        coordinates = {
            1: (0.0, 0.0, 0.0),
            2: (1.09, 0.0, 0.0),
            3: (-0.36, 1.03, 0.0),
            4: (3.0, 0.0, 0.0),
            5: (4.09, 0.0, 0.0),
            6: (2.64, 1.03, 0.0),
            7: (2.64, -1.03, 0.0),
        }
        elements = {1: "C", 2: "H", 3: "H", 4: "C", 5: "H", 6: "H", 7: "H"}

        hydrogens_by_carbon, carbon_by_hydrogen = build_c_h_adjacency(coordinates, elements)

        self.assertEqual(hydrogens_by_carbon[1], [2, 3])
        self.assertEqual(hydrogens_by_carbon[4], [5, 6, 7])
        self.assertEqual(carbon_by_hydrogen[2], 1)
        self.assertEqual(carbon_by_hydrogen[7], 4)

    def test_build_c_h_adjacency_ignores_non_carbon_hydrogen_bonds(self) -> None:
        coordinates = {
            1: (0.0, 0.0, 0.0),
            2: (0.96, 0.0, 0.0),
            3: (4.0, 0.0, 0.0),
            4: (5.2, 0.0, 0.0),
        }
        elements = {1: "O", 2: "H", 3: "C", 4: "C"}

        hydrogens_by_carbon, carbon_by_hydrogen = build_c_h_adjacency(coordinates, elements)

        self.assertEqual(hydrogens_by_carbon, {})
        self.assertEqual(carbon_by_hydrogen, {})


class Structure2DTests(unittest.TestCase):
    @unittest.skipIf(Chem is None, "RDKit is not installed")
    def test_rdkit_2d_coordinates_preserve_atom_ids(self) -> None:
        coordinates = {
            1: (0.0, 0.0, 0.0),
            2: (1.50, 0.0, 0.0),
            3: (-0.5, 0.9, 0.0),
            4: (-0.5, -0.9, 0.0),
        }
        elements = {1: "C", 2: "C", 3: "H", 4: "H"}

        coordinates_2d = compute_rdkit_2d_coordinates(coordinates, elements)

        self.assertEqual(set(coordinates_2d), set(coordinates))
        for point in coordinates_2d.values():
            self.assertEqual(len(point), 2)

    def test_rdkit_missing_failure_is_displayable(self) -> None:
        with patch("dp4_platform.structure2d.Chem", None), patch("dp4_platform.structure2d.AllChem", None):
            with self.assertRaisesRegex(RuntimeError, "RDKit"):
                compute_rdkit_2d_coordinates({1: (0.0, 0.0, 0.0)}, {1: "C"})


if __name__ == "__main__":
    unittest.main()
