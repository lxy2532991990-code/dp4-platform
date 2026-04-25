"""Diastereotopic proton pairing — re-pair calculated values to experimental shifts.

For chemically equivalent (diastereotopic) nuclei such as the two protons of a
CH2 or the two methyls of an isopropyl group, the experimentalist cannot tell
which atom produced which signal. The arbitrary computed labelling is therefore
re-paired against the experimental shift order before scoring, so that the
larger experimental shift is matched with the calculated value that produces a
larger predicted shift (or, equivalently, a smaller shielding).

Mirrors upstream DP4+App ``correlation_module.py:246-275 diasterotopic()``.
"""

from __future__ import annotations

from .models import ExperimentalAssignment


def reassign_diastereotopic_pairs(
    nucleus_assignments: list[ExperimentalAssignment],
    calc_values: dict[int, float],
    *,
    sense: str,
) -> tuple[dict[int, float], list[tuple[int, int]]]:
    """Re-pair calc values within each non-empty ``exchange_group``.

    ``sense`` controls the relationship between the calculated value and the
    chemical shift:

    * ``"shielding"`` — calc value is a shielding ``sigma``; the larger
      experimental ``delta`` is matched with the smaller ``sigma``.
    * ``"shift"`` — calc value is a chemical shift ``delta``; the larger
      experimental ``delta`` is matched with the larger calculated ``delta``.

    Returns a tuple of ``(rewritten_map, swaps)`` where ``swaps`` is a list of
    ``(atom_a, atom_b)`` pairs whose calculated values were swapped. The input
    ``calc_values`` dict is not mutated.
    """
    if sense not in {"shielding", "shift"}:
        raise ValueError(f"sense must be 'shielding' or 'shift'; got {sense!r}")

    rewritten = dict(calc_values)
    swaps: list[tuple[int, int]] = []

    by_group: dict[str, list[ExperimentalAssignment]] = {}
    for assignment in nucleus_assignments:
        if not assignment.exchange_group:
            continue
        by_group.setdefault(assignment.exchange_group, []).append(assignment)

    for group, members in by_group.items():
        if len(members) != 2:
            # Validation should have rejected this earlier; skip defensively.
            continue
        first, second = members
        calc_a = rewritten.get(first.candidate_atom_id)
        calc_b = rewritten.get(second.candidate_atom_id)
        if calc_a is None or calc_b is None:
            continue

        # decide which atom should receive the larger experimental shift
        if first.exp_shift_ppm >= second.exp_shift_ppm:
            larger_exp_atom, smaller_exp_atom = first, second
        else:
            larger_exp_atom, smaller_exp_atom = second, first

        # decide which calc value belongs with the larger experimental shift
        if sense == "shielding":
            # smaller sigma -> larger delta
            calc_for_larger_exp = min(calc_a, calc_b)
            calc_for_smaller_exp = max(calc_a, calc_b)
        else:
            calc_for_larger_exp = max(calc_a, calc_b)
            calc_for_smaller_exp = min(calc_a, calc_b)

        existing_for_larger = rewritten[larger_exp_atom.candidate_atom_id]
        if existing_for_larger != calc_for_larger_exp:
            rewritten[larger_exp_atom.candidate_atom_id] = calc_for_larger_exp
            rewritten[smaller_exp_atom.candidate_atom_id] = calc_for_smaller_exp
            swaps.append(
                (
                    larger_exp_atom.candidate_atom_id,
                    smaller_exp_atom.candidate_atom_id,
                )
            )

    return rewritten, swaps
