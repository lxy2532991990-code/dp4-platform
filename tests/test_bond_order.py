from __future__ import annotations

import unittest

from dp4_platform.bond_order import classify_bond, infer_bond_orders
from dp4_platform.hybridization import (
    CarbonHyb,
    build_atom_hybridization_map,
    detect_carbon_hybridizations,
)
from dp4_platform.structure_model import infer_bonds


def _ethylene_geometry() -> tuple[dict[int, str], dict[int, tuple[float, float, float]]]:
    elements = {1: "C", 2: "C", 3: "H", 4: "H", 5: "H", 6: "H"}
    coordinates = {
        1: (0.000, 0.000, 0.000),
        2: (1.339, 0.000, 0.000),
        3: (-0.560, 0.940, 0.000),
        4: (-0.560, -0.940, 0.000),
        5: (1.899, 0.940, 0.000),
        6: (1.899, -0.940, 0.000),
    }
    return elements, coordinates


def _acetylene_geometry() -> tuple[dict[int, str], dict[int, tuple[float, float, float]]]:
    elements = {1: "C", 2: "C", 3: "H", 4: "H"}
    coordinates = {
        1: (0.000, 0.000, 0.000),
        2: (1.203, 0.000, 0.000),
        3: (-1.060, 0.000, 0.000),
        4: (2.263, 0.000, 0.000),
    }
    return elements, coordinates


def _formaldehyde_geometry() -> tuple[dict[int, str], dict[int, tuple[float, float, float]]]:
    elements = {1: "C", 2: "O", 3: "H", 4: "H"}
    coordinates = {
        1: (0.000, 0.000, 0.000),
        2: (1.205, 0.000, 0.000),  # C=O ~1.21 Å
        3: (-0.555, 0.943, 0.000),
        4: (-0.555, -0.943, 0.000),
    }
    return elements, coordinates


def _methane_geometry() -> tuple[dict[int, str], dict[int, tuple[float, float, float]]]:
    elements = {1: "C", 2: "H", 3: "H", 4: "H", 5: "H"}
    coordinates = {
        1: (0.000, 0.000, 0.000),
        2: (0.629, 0.629, 0.629),
        3: (-0.629, -0.629, 0.629),
        4: (-0.629, 0.629, -0.629),
        5: (0.629, -0.629, -0.629),
    }
    return elements, coordinates


class ClassifyBondTests(unittest.TestCase):
    def test_double_bond_distance(self) -> None:
        self.assertEqual(classify_bond("C", "C", 1.339), "double")

    def test_single_bond_distance(self) -> None:
        self.assertEqual(classify_bond("C", "C", 1.540), "single")

    def test_triple_bond_distance(self) -> None:
        self.assertEqual(classify_bond("C", "C", 1.203), "triple")

    def test_unknown_pair_defaults_single(self) -> None:
        self.assertEqual(classify_bond("Si", "Si", 2.34), "single")

    def test_carbonyl_is_double(self) -> None:
        self.assertEqual(classify_bond("C", "O", 1.205), "double")

    def test_long_co_is_single(self) -> None:
        self.assertEqual(classify_bond("C", "O", 1.43), "single")


class InferBondOrdersTests(unittest.TestCase):
    def test_ethylene_double_bond(self) -> None:
        elements, coordinates = _ethylene_geometry()
        bonds = infer_bonds(coordinates, elements)
        orders = infer_bond_orders(coordinates, elements, bonds)
        self.assertEqual(orders[(1, 2)], "double")
        # All C-H bonds are single
        for key, order in orders.items():
            atoms = {elements[key[0]], elements[key[1]]}
            if "H" in atoms:
                self.assertEqual(order, "single")

    def test_acetylene_triple_bond(self) -> None:
        elements, coordinates = _acetylene_geometry()
        bonds = infer_bonds(coordinates, elements)
        orders = infer_bond_orders(coordinates, elements, bonds)
        self.assertEqual(orders[(1, 2)], "triple")


class HybridizationCrossCheckTests(unittest.TestCase):
    def test_ethylene_carbons_classified_sp2_no_warnings(self) -> None:
        elements, coordinates = _ethylene_geometry()
        hyb, warnings = detect_carbon_hybridizations(elements, coordinates)
        self.assertEqual(hyb[1], CarbonHyb.SP2)
        self.assertEqual(hyb[2], CarbonHyb.SP2)
        self.assertEqual(warnings, [])

    def test_acetylene_carbons_classified_sp_no_warnings(self) -> None:
        elements, coordinates = _acetylene_geometry()
        hyb, warnings = detect_carbon_hybridizations(elements, coordinates)
        self.assertEqual(hyb[1], CarbonHyb.SP)
        self.assertEqual(hyb[2], CarbonHyb.SP)
        self.assertEqual(warnings, [])

    def test_carbonyl_classified_sp2_no_warnings(self) -> None:
        elements, coordinates = _formaldehyde_geometry()
        hyb, warnings = detect_carbon_hybridizations(elements, coordinates)
        self.assertEqual(hyb[1], CarbonHyb.SP2)
        self.assertEqual(warnings, [])

    def test_methane_sp3_no_warnings(self) -> None:
        elements, coordinates = _methane_geometry()
        hyb, warnings = detect_carbon_hybridizations(elements, coordinates)
        self.assertEqual(hyb[1], CarbonHyb.SP3)
        self.assertEqual(warnings, [])

    def test_warns_when_neighbor_count_says_sp3_but_double_bond_present(self) -> None:
        # 4 covalent neighbors for atom 1 (so neighbor count -> sp3) but the
        # C-C bond to atom 2 is at olefinic distance so bond-order says sp2.
        elements = {1: "C", 2: "C", 3: "H", 4: "H", 5: "H"}
        coordinates = {
            1: (0.000, 0.000, 0.000),
            2: (1.339, 0.000, 0.000),  # double-bond distance
            3: (-0.629, 0.629, 0.629),
            4: (-0.629, -0.629, 0.629),
            5: (-0.629, 0.629, -0.629),
        }
        hyb, warnings = detect_carbon_hybridizations(elements, coordinates)
        self.assertEqual(hyb[1], CarbonHyb.SP3)  # neighbor count remains primary
        self.assertTrue(any("atom 1" in w for w in warnings))
        self.assertTrue(any("sp2" in w for w in warnings))

    def test_build_atom_hybridization_map_propagates_to_hydrogens(self) -> None:
        elements, coordinates = _ethylene_geometry()
        hyb_map, warnings = build_atom_hybridization_map(elements, coordinates)
        self.assertEqual(hyb_map[1], CarbonHyb.SP2)
        self.assertEqual(hyb_map[3], CarbonHyb.SP2)  # hydrogen on sp2 carbon
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
