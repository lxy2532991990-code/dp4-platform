"""HALO (HALOgen-adjacent) module — MSTD override of unscaled chemical shifts.

For carbons bonded directly to a halogen and the hydrogens attached to those
carbons, DP4+App applies a Multi-STandarD (MSTD) correction:

    delta_unscaled = sigma_standard - sigma_sample + delta_reference

instead of the usual ``sigma_TMS - sigma_sample`` reference. This pulls the
unscaled shift toward the experimental reference of a similar halogen-bearing
system (per nucleus, per halogen, per sp2/sp3 environment).

The error distribution is unchanged — DP4+App uses the same ``sp2``/``sp3``
Student-t parameters for halogen-adjacent atoms. Only the value fed into the
unscaled error term is overridden.

Mirrors upstream ``HALO_module.py`` and ``MSTD-{QM,MM,Custom}-Stand.xlsx``.
"""

from __future__ import annotations


HALOGENS: tuple[str, ...] = ("Cl", "Br")  # MSTD coverage upstream — no iodine
_HALOGEN_PRIORITY: dict[str, int] = {"Cl": 1, "Br": 2}


def detect_halogen_neighbors(
    elements: dict[int, str],
    bonds: list[tuple[int, int]],
) -> dict[int, str]:
    """Map each halogen-adjacent atom to its halogen symbol.

    Carbons bonded directly to Cl/Br are flagged with that halogen. Hydrogens
    attached to such carbons inherit the same halogen tag (so the H_Cl/H_Br
    MSTD entries can fire).

    For carbons bearing more than one halogen (e.g. geminal CHClBr), the
    heavier halogen wins (Br > Cl) — this matches the dominance pattern used
    by the upstream MSTD reference set.
    """
    carbon_halogen: dict[int, str] = {}

    # First pass: C-X bonds.
    for atom_a, atom_b in bonds:
        el_a = elements.get(atom_a, "")
        el_b = elements.get(atom_b, "")
        if el_a == "C" and el_b in HALOGENS:
            carbon_id, halogen = atom_a, el_b
        elif el_b == "C" and el_a in HALOGENS:
            carbon_id, halogen = atom_b, el_a
        else:
            continue
        existing = carbon_halogen.get(carbon_id)
        if existing is None or _HALOGEN_PRIORITY[halogen] > _HALOGEN_PRIORITY[existing]:
            carbon_halogen[carbon_id] = halogen

    # Second pass: hydrogens attached to those carbons.
    result: dict[int, str] = dict(carbon_halogen)
    for atom_a, atom_b in bonds:
        el_a = elements.get(atom_a, "")
        el_b = elements.get(atom_b, "")
        if el_a == "C" and el_b == "H" and atom_a in carbon_halogen:
            result[atom_b] = carbon_halogen[atom_a]
        elif el_b == "C" and el_a == "H" and atom_b in carbon_halogen:
            result[atom_a] = carbon_halogen[atom_b]
    return result


def mstd_key(nucleus: str, halogen: str, hyb: str) -> str | None:
    """Return e.g. ``'C_Cl_sp2'`` or ``'H_Br_sp3'``; ``None`` if hybridization
    is not one of ``sp2``/``sp3`` (DP4+App's MSTD tables only cover those)."""
    if hyb not in {"sp2", "sp3"}:
        return None
    if halogen not in HALOGENS:
        return None
    if nucleus == "13C":
        nuc = "C"
    elif nucleus == "1H":
        nuc = "H"
    else:
        return None
    return f"{nuc}_{halogen}_{hyb}"


def apply_mstd_unscaled(calc_shielding: float, mstd_entry: dict) -> float:
    """``delta_unscaled = sigma_standard - sigma_sample + delta_reference``.

    Mirrors ``HALO_module.py:113-117``.
    """
    return (
        float(mstd_entry["shielding_standard"])
        - calc_shielding
        + float(mstd_entry["reference_value"])
    )
