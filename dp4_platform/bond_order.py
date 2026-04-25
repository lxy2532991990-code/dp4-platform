"""Distance-based bond-order classifier.

Used as a cross-check against the neighbor-count hybridization rule. Single,
double, and triple bonds are inferred from the interatomic distance with
canonical thresholds. Returns ``"single"``, ``"double"``, or ``"triple"`` for
each bond; element pairs without a tabulated rule fall back to ``"single"``.

Keys are normalized as ``(min(a, b), max(a, b))`` to make membership tests
order-independent.
"""

from __future__ import annotations

from math import dist


_THRESHOLDS: dict[frozenset[str], tuple[float, float]] = {
    frozenset({"C", "C"}): (1.27, 1.42),
    frozenset({"C", "N"}): (1.22, 1.40),
    frozenset({"C", "O"}): (0.0, 1.30),
    frozenset({"N", "N"}): (1.20, 1.35),
    frozenset({"N", "O"}): (0.0, 1.30),
}


def classify_bond(
    element_a: str,
    element_b: str,
    distance: float,
) -> str:
    """Return ``"single"``, ``"double"``, or ``"triple"`` for one bond.

    Pairs without a tabulated threshold default to ``"single"``.
    """
    key = frozenset({element_a, element_b})
    thresholds = _THRESHOLDS.get(key)
    if thresholds is None:
        return "single"
    triple_max, double_max = thresholds
    if triple_max > 0 and distance < triple_max:
        return "triple"
    if distance < double_max:
        return "double"
    return "single"


def infer_bond_orders(
    coordinates: dict[int, tuple[float, float, float]],
    elements: dict[int, str],
    bonds: list[tuple[int, int]],
) -> dict[tuple[int, int], str]:
    """Classify each bond as ``"single"``, ``"double"``, or ``"triple"``.

    ``bonds`` should come from :func:`dp4_platform.structure_model.infer_bonds`.
    Element pairs without a tabulated rule default to ``"single"``.
    """
    orders: dict[tuple[int, int], str] = {}
    for atom_a, atom_b in bonds:
        key = (atom_a, atom_b) if atom_a < atom_b else (atom_b, atom_a)
        element_a = elements.get(atom_a, "")
        element_b = elements.get(atom_b, "")
        coord_a = coordinates.get(atom_a)
        coord_b = coordinates.get(atom_b)
        if coord_a is None or coord_b is None:
            orders[key] = "single"
            continue
        orders[key] = classify_bond(element_a, element_b, dist(coord_a, coord_b))
    return orders


def carbon_bond_order_summary(
    atom_id: int,
    elements: dict[int, str],
    bonds: list[tuple[int, int]],
    bond_orders: dict[tuple[int, int], str],
) -> dict[str, int]:
    """Count single/double/triple bonds incident on a carbon."""
    counts = {"single": 0, "double": 0, "triple": 0}
    for atom_a, atom_b in bonds:
        if atom_id not in (atom_a, atom_b):
            continue
        key = (atom_a, atom_b) if atom_a < atom_b else (atom_b, atom_a)
        order = bond_orders.get(key, "single")
        counts[order] = counts.get(order, 0) + 1
    return counts
