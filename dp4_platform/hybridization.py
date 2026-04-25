"""Carbon hybridization detection from 3D molecular geometry."""

from __future__ import annotations

from enum import Enum
from math import dist

from .bond_order import carbon_bond_order_summary, infer_bond_orders
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


def _classify_by_neighbors(neighbor_count: int) -> CarbonHyb:
    if neighbor_count == 2:
        return CarbonHyb.SP
    if neighbor_count == 3:
        return CarbonHyb.SP2
    if neighbor_count == 4:
        return CarbonHyb.SP3
    return CarbonHyb.UNKNOWN


def _classify_by_bond_orders(counts: dict[str, int]) -> CarbonHyb | None:
    if counts.get("triple", 0) >= 1:
        return CarbonHyb.SP
    if counts.get("double", 0) >= 1:
        return CarbonHyb.SP2
    if counts.get("single", 0) == 4:
        return CarbonHyb.SP3
    return None


def detect_carbon_hybridizations(
    elements: dict[int, str],
    coordinates: dict[int, tuple[float, float, float]],
) -> tuple[dict[int, CarbonHyb], list[str]]:
    """Assign hybridization to every carbon and return cross-check warnings.

    The neighbor-count rule remains the primary classifier (2 -> sp, 3 -> sp2,
    4 -> sp3, anything else -> unknown). After classifying, a distance-based
    bond-order pass is run as a sanity check; warnings are emitted when the
    two analyses disagree.
    """
    bonds = infer_bonds(coordinates, elements)
    bond_orders = infer_bond_orders(coordinates, elements, bonds)
    result: dict[int, CarbonHyb] = {}
    warnings: list[str] = []

    for atom_id, element in elements.items():
        if element.upper() != "C":
            continue
        neighbor_count = _count_neighbors(atom_id, elements, coordinates, bonds)
        primary = _classify_by_neighbors(neighbor_count)
        result[atom_id] = primary

        order_counts = carbon_bond_order_summary(atom_id, elements, bonds, bond_orders)
        secondary = _classify_by_bond_orders(order_counts)
        if secondary is not None and primary != CarbonHyb.UNKNOWN and secondary != primary:
            warnings.append(
                f"atom {atom_id} ({element}): neighbor count suggests {primary.value} "
                f"but bond-order analysis suggests {secondary.value} "
                f"(single={order_counts.get('single', 0)}, "
                f"double={order_counts.get('double', 0)}, "
                f"triple={order_counts.get('triple', 0)})"
            )
        elif primary == CarbonHyb.UNKNOWN:
            warnings.append(
                f"atom {atom_id} ({element}): neighbor count {neighbor_count} is outside the "
                "expected 2-4 range; hybridization left as unknown"
            )

    return result, warnings


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
            carbon_hyb, _ = detect_carbon_hybridizations(elements, coordinates)
            return carbon_hyb.get(other, CarbonHyb.UNKNOWN)
    return None


def build_atom_hybridization_map(
    elements: dict[int, str],
    coordinates: dict[int, tuple[float, float, float]],
) -> tuple[dict[int, CarbonHyb], list[str]]:
    """Build a hybridization map for ALL atoms and return cross-check warnings.

    - Carbons: directly from geometry (neighbor count, with bond-order warnings)
    - Hydrogens: inherited from attached carbon
    - Other elements: UNKNOWN
    """
    carbon_hyb, warnings = detect_carbon_hybridizations(elements, coordinates)
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
    return result, warnings
