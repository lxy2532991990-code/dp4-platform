"""Carbon hybridization detection from 3D molecular geometry."""

from __future__ import annotations

from enum import Enum
from math import dist

from .structure_model import COVALENT_RADIUS, DEFAULT_COVALENT, BOND_TOLERANCE, infer_bonds


class CarbonHyb(Enum):
    SP = "sp"
    SP2 = "sp2"
    SP3 = "sp3"
    UNKNOWN = "unknown"


def _count_neighbors(
    atom_id: int,
    elements: dict[int, str],
    coordinates: dict[int, tuple[float, float, float]],
    bonds: list[tuple[int, int]],
) -> int:
    count = 0
    for a, b in bonds:
        if a == atom_id or b == atom_id:
            count += 1
    return count


def detect_carbon_hybridizations(
    elements: dict[int, str],
    coordinates: dict[int, tuple[float, float, float]],
) -> dict[int, CarbonHyb]:
    """Assign hybridization to every carbon atom based on neighbour count.

    Heuristic: 2 neighbours -> sp, 3 neighbours -> sp2, 4 neighbours -> sp3.
    For carbons with ambiguous neighbour counts (<2 or >4), returns UNKNOWN.
    """
    bonds = infer_bonds(coordinates, elements)
    result: dict[int, CarbonHyb] = {}

    for atom_id, element in elements.items():
        if element.upper() != "C":
            continue
        n = _count_neighbors(atom_id, elements, coordinates, bonds)
        if n == 2:
            result[atom_id] = CarbonHyb.SP
        elif n == 3:
            result[atom_id] = CarbonHyb.SP2
        elif n == 4:
            result[atom_id] = CarbonHyb.SP3
        else:
            result[atom_id] = CarbonHyb.UNKNOWN
    return result


def get_proton_hybridization(
    hydrogen_id: int,
    elements: dict[int, str],
    coordinates: dict[int, tuple[float, float, float]],
) -> CarbonHyb | None:
    """Return the hybridization of the carbon a proton is attached to.

    Returns None if the hydrogen is not bonded to a carbon.
    """
    bonds = infer_bonds(coordinates, elements)
    for a, b in bonds:
        other = None
        if a == hydrogen_id:
            other = b
        elif b == hydrogen_id:
            other = a
        else:
            continue
        if elements.get(other, "").upper() == "C":
            carbon_hyb = detect_carbon_hybridizations(elements, coordinates)
            return carbon_hyb.get(other, CarbonHyb.UNKNOWN)
    return None


def build_atom_hybridization_map(
    elements: dict[int, str],
    coordinates: dict[int, tuple[float, float, float]],
) -> dict[int, CarbonHyb]:
    """Build a hybridization map for ALL atoms.

    - Carbons: directly from geometry
    - Hydrogens: inherited from attached carbon
    - Other elements: UNKNOWN
    """
    carbon_hyb = detect_carbon_hybridizations(elements, coordinates)
    bonds = infer_bonds(coordinates, elements)

    # build a quick lookup: atom -> its carbon neighbour (if any)
    carbon_of: dict[int, int] = {}
    for a, b in bonds:
        el_a = elements.get(a, "")
        el_b = elements.get(b, "")
        if el_a.upper() == "C" and el_b.upper() == "H":
            carbon_of[b] = a
        elif el_b.upper() == "C" and el_a.upper() == "H":
            carbon_of[a] = b

    result: dict[int, CarbonHyb] = {}
    for atom_id, element in elements.items():
        el = element.upper()
        if el == "C":
            result[atom_id] = carbon_hyb.get(atom_id, CarbonHyb.UNKNOWN)
        elif el == "H":
            parent_c = carbon_of.get(atom_id)
            if parent_c is not None:
                result[atom_id] = carbon_hyb.get(parent_c, CarbonHyb.UNKNOWN)
            else:
                result[atom_id] = CarbonHyb.UNKNOWN
        else:
            result[atom_id] = CarbonHyb.UNKNOWN
    return result
