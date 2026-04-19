"""Energy handling and Boltzmann weighting."""

from __future__ import annotations

import math

from .config import DP4Config, WeightingStrategy
from .models import CandidateIsomer, ConformerRecord

HARTREE_TO_KCAL = 627.5095
R_GAS = 1.987204e-3


def _get_energy(record: ConformerRecord, strategy: WeightingStrategy) -> float | None:
    if strategy == WeightingStrategy.ELECTRONIC:
        return record.scf_energy
    if strategy == WeightingStrategy.GIBBS:
        if record.gibbs_energy is not None:
            return record.gibbs_energy
        if record.scf_energy is not None and record.gibbs_correction is not None:
            return record.scf_energy + record.gibbs_correction
        return record.scf_energy
    if strategy == WeightingStrategy.SINGLE_POINT:
        return record.sp_energy or _get_energy(record, WeightingStrategy.GIBBS)
    if strategy == WeightingStrategy.MANUAL:
        return record.scf_energy
    return None


def compute_boltzmann_weights(candidate: CandidateIsomer, config: DP4Config) -> None:
    usable = candidate.collection.usable_records
    if not usable:
        return

    energies: dict[int, float] = {}
    for record in usable:
        energy = _get_energy(record, config.weighting)
        if energy is None:
            record.boltzmann_weight = 0.0
            record.add_warning(f"No energy available for {config.weighting.value}; excluded from weighting")
            continue
        energies[record.conf_id] = energy

    if not energies:
        raise ValueError(f"Candidate '{candidate.name}' has no usable conformers with energies")

    e_min = min(energies.values())
    raw_weights: dict[int, float] = {}
    for record in usable:
        if record.conf_id not in energies:
            continue
        relative_energy = (energies[record.conf_id] - e_min) * HARTREE_TO_KCAL
        record.relative_energy_kcal = relative_energy
        raw_weights[record.conf_id] = math.exp(-relative_energy / (R_GAS * config.temperature))

    total = sum(raw_weights.values())
    if total <= 0:
        raise ValueError(f"Candidate '{candidate.name}' produced invalid Boltzmann weights")

    for record in usable:
        weight = raw_weights.get(record.conf_id, 0.0) / total
        record.boltzmann_weight = weight

    candidate.collection.normalize_weights()


def boltzmann_average_shieldings(candidate: CandidateIsomer, nuclei: tuple[str, ...]) -> dict[str, dict[int, float]]:
    averaged: dict[str, dict[int, float]] = {nucleus: {} for nucleus in nuclei}
    usable = candidate.collection.usable_records
    if not usable:
        raise ValueError(f"Candidate '{candidate.name}' has no usable conformers")

    for nucleus in nuclei:
        atom_ids = sorted(
            {
                atom_id
                for record in usable
                for atom_id in record.shieldings_by_nucleus.get(nucleus, {})
            }
        )
        for atom_id in atom_ids:
            numerator = 0.0
            denominator = 0.0
            for record in usable:
                value = record.shieldings_by_nucleus.get(nucleus, {}).get(atom_id)
                if value is None:
                    continue
                numerator += record.effective_weight * value
                denominator += record.effective_weight
            if denominator > 0:
                averaged[nucleus][atom_id] = numerator / denominator
    candidate.averaged_shieldings = averaged
    return averaged
