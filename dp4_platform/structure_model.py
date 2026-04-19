"""Shared molecular structure helpers for 2D and 3D viewers."""

from __future__ import annotations

from math import dist


ELEMENT_COLORS: dict[str, tuple[float, float, float]] = {
    "H": (0.90, 0.90, 0.90),
    "C": (0.25, 0.25, 0.25),
    "N": (0.19, 0.31, 0.97),
    "O": (0.94, 0.16, 0.16),
    "F": (0.56, 0.88, 0.31),
    "P": (1.00, 0.50, 0.00),
    "S": (1.00, 1.00, 0.19),
    "Cl": (0.12, 0.94, 0.12),
    "Br": (0.65, 0.16, 0.16),
    "I": (0.58, 0.00, 0.58),
}
DEFAULT_COLOR = (0.55, 0.55, 0.55)
HIGHLIGHT_COLOR = (1.00, 0.85, 0.10)
RELATED_HIGHLIGHT_COLOR = (1.00, 0.93, 0.45)
ASSIGNED_COLOR = (0.25, 0.75, 0.35)

COVALENT_RADIUS: dict[str, float] = {
    "H": 0.31,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Br": 1.20,
    "I": 1.39,
}
DEFAULT_COVALENT = 0.80
BOND_TOLERANCE = 0.40


def infer_bonds(
    coordinates: dict[int, tuple[float, float, float]],
    elements: dict[int, str],
) -> list[tuple[int, int]]:
    """Infer single bonds from interatomic distances and covalent radii."""
    atom_ids = list(coordinates.keys())
    bonds: list[tuple[int, int]] = []
    for i, atom_a in enumerate(atom_ids):
        for atom_b in atom_ids[i + 1 :]:
            element_a = elements.get(atom_a, "C")
            element_b = elements.get(atom_b, "C")
            radius_a = COVALENT_RADIUS.get(element_a, DEFAULT_COVALENT)
            radius_b = COVALENT_RADIUS.get(element_b, DEFAULT_COVALENT)
            max_bond = radius_a + radius_b + BOND_TOLERANCE
            distance = dist(coordinates[atom_a], coordinates[atom_b])
            if 0.4 < distance < max_bond:
                bonds.append((atom_a, atom_b))
    return bonds


def build_c_h_adjacency(
    coordinates: dict[int, tuple[float, float, float]],
    elements: dict[int, str],
) -> tuple[dict[int, list[int]], dict[int, int]]:
    """Return direct C-H relationships inferred from the structure geometry."""
    hydrogens_by_carbon: dict[int, list[int]] = {}
    carbon_by_hydrogen: dict[int, int] = {}
    for atom_a, atom_b in infer_bonds(coordinates, elements):
        element_a = elements.get(atom_a, "")
        element_b = elements.get(atom_b, "")
        if element_a == "C" and element_b == "H":
            carbon_id, hydrogen_id = atom_a, atom_b
        elif element_a == "H" and element_b == "C":
            carbon_id, hydrogen_id = atom_b, atom_a
        else:
            continue
        hydrogens_by_carbon.setdefault(carbon_id, []).append(hydrogen_id)
        carbon_by_hydrogen[hydrogen_id] = carbon_id

    for hydrogen_ids in hydrogens_by_carbon.values():
        hydrogen_ids.sort()
    return hydrogens_by_carbon, carbon_by_hydrogen
