from __future__ import annotations

import unittest
from unittest.mock import patch

from dp4_platform.structure_model import build_c_h_adjacency, infer_bonds
from dp4_platform.structure2d import (
    Chem,
    Structure2DView,
    Point3D,
    _terminal_group_label,
    compute_rdkit_2d_coordinates,
)


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
    def _methoxy_mol(self, attachment_x: float) -> tuple["Chem.RWMol", int, int, list[int]]:
        mol = Chem.RWMol()
        attachment_idx = mol.AddAtom(Chem.Atom("C"))
        oxygen_idx = mol.AddAtom(Chem.Atom("O"))
        methyl_idx = mol.AddAtom(Chem.Atom("C"))
        hydrogen_indices = [mol.AddAtom(Chem.Atom("H")) for _ in range(3)]
        mol.AddBond(attachment_idx, oxygen_idx, Chem.BondType.SINGLE)
        mol.AddBond(oxygen_idx, methyl_idx, Chem.BondType.SINGLE)
        for hydrogen_idx in hydrogen_indices:
            mol.AddBond(methyl_idx, hydrogen_idx, Chem.BondType.SINGLE)

        methyl_x = -1.0 if attachment_x > 0.0 else 1.0
        conf = Chem.Conformer(mol.GetNumAtoms())
        conf.SetAtomPosition(attachment_idx, Point3D(attachment_x, 0.0, 0.0))
        conf.SetAtomPosition(oxygen_idx, Point3D(0.0, 0.0, 0.0))
        conf.SetAtomPosition(methyl_idx, Point3D(methyl_x, 0.0, 0.0))
        for offset, hydrogen_idx in enumerate(hydrogen_indices, start=1):
            conf.SetAtomPosition(hydrogen_idx, Point3D(methyl_x, offset * 0.3, 0.0))
        mol.AddConformer(conf)
        return mol, oxygen_idx, methyl_idx, hydrogen_indices

    @unittest.skipIf(Chem is None or Point3D is None, "RDKit is not installed")
    def test_methoxy_group_uses_skeletal_methyl_endpoint(self) -> None:
        mol, oxygen_idx, methyl_idx, hydrogen_indices = self._methoxy_mol(-1.0)

        display_mol, orig_to_draw, labels, hidden = (
            Structure2DView._build_display_mol_and_maps(None, mol)
        )

        self.assertNotIn(oxygen_idx, labels)
        self.assertNotIn(methyl_idx, labels)
        self.assertEqual(display_mol.GetNumAtoms(), 3)
        self.assertIn(oxygen_idx, orig_to_draw)
        self.assertIn(methyl_idx, orig_to_draw)
        self.assertNotIn(methyl_idx, hidden)
        for hydrogen_idx in hydrogen_indices:
            self.assertEqual(hidden[hydrogen_idx], methyl_idx)

    @unittest.skipIf(Chem is None or Point3D is None, "RDKit is not installed")
    def test_terminal_methyl_group_uses_skeletal_endpoint(self) -> None:
        mol = Chem.RWMol()
        attachment_idx = mol.AddAtom(Chem.Atom("C"))
        methyl_idx = mol.AddAtom(Chem.Atom("C"))
        hydrogen_indices = [mol.AddAtom(Chem.Atom("H")) for _ in range(3)]
        mol.AddBond(attachment_idx, methyl_idx, Chem.BondType.SINGLE)
        for hydrogen_idx in hydrogen_indices:
            mol.AddBond(methyl_idx, hydrogen_idx, Chem.BondType.SINGLE)
        conf = Chem.Conformer(mol.GetNumAtoms())
        conf.SetAtomPosition(attachment_idx, Point3D(0.0, 0.0, 0.0))
        conf.SetAtomPosition(methyl_idx, Point3D(1.0, 0.0, 0.0))
        for offset, hydrogen_idx in enumerate(hydrogen_indices, start=1):
            conf.SetAtomPosition(hydrogen_idx, Point3D(1.0, offset * 0.3, 0.0))
        mol.AddConformer(conf)

        display_mol, orig_to_draw, labels, hidden = (
            Structure2DView._build_display_mol_and_maps(None, mol)
        )

        self.assertEqual(labels, {})
        self.assertEqual(display_mol.GetNumAtoms(), 2)
        self.assertIn(methyl_idx, orig_to_draw)
        for hydrogen_idx in hydrogen_indices:
            self.assertEqual(hidden[hydrogen_idx], methyl_idx)

    @unittest.skipIf(Chem is None or Point3D is None, "RDKit is not installed")
    def test_terminal_group_label_keeps_attachment_atom_near_bond(self) -> None:
        mol = Chem.RWMol()
        oxygen_idx = mol.AddAtom(Chem.Atom("O"))
        carbon_idx = mol.AddAtom(Chem.Atom("C"))
        mol.AddBond(oxygen_idx, carbon_idx, Chem.BondType.SINGLE)
        conf = Chem.Conformer(mol.GetNumAtoms())
        conf.SetAtomPosition(oxygen_idx, Point3D(0.0, 0.0, 0.0))
        conf.SetAtomPosition(carbon_idx, Point3D(1.0, 0.0, 0.0))
        mol.AddConformer(conf)

        label = _terminal_group_label(mol, mol.GetAtomWithIdx(oxygen_idx), "OH", "HO")

        self.assertEqual(label, "HO")

    @unittest.skipIf(Chem is None or Point3D is None, "RDKit is not installed")
    def test_terminal_group_label_uses_default_when_neighbor_is_left(self) -> None:
        mol = Chem.RWMol()
        carbon_idx = mol.AddAtom(Chem.Atom("C"))
        oxygen_idx = mol.AddAtom(Chem.Atom("O"))
        mol.AddBond(carbon_idx, oxygen_idx, Chem.BondType.SINGLE)
        conf = Chem.Conformer(mol.GetNumAtoms())
        conf.SetAtomPosition(carbon_idx, Point3D(0.0, 0.0, 0.0))
        conf.SetAtomPosition(oxygen_idx, Point3D(-1.0, 0.0, 0.0))
        mol.AddConformer(conf)

        label = _terminal_group_label(mol, mol.GetAtomWithIdx(carbon_idx), "OH", "HO")

        self.assertEqual(label, "OH")

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
