from __future__ import annotations

import unittest
from unittest.mock import patch

from dp4_platform.structure_model import infer_bonds
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
