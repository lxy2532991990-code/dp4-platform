"""DP4-style scoring utilities."""

from __future__ import annotations

import json
import math
from importlib import resources

from .config import DP4Config, ScalingMode
from .models import CandidateIsomer, CandidateScore, ExperimentalAssignment, ShiftRow


def load_parameter_table(path: str | None) -> dict:
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    with resources.files("dp4_platform.data").joinpath("default_parameter_table.json").open(
        "r", encoding="utf-8"
    ) as fh:
        return json.load(fh)


def _nucleus_params(parameter_table: dict, nucleus: str) -> dict:
    nuclei = parameter_table.get("nuclei", {})
    if nucleus not in nuclei:
        raise ValueError(f"Parameter table is missing settings for nucleus {nucleus}")
    return nuclei[nucleus]


def predict_shift(shielding: float, nucleus: str, parameter_table: dict, scaling_mode: ScalingMode) -> float:
    if scaling_mode == ScalingMode.IDENTITY:
        return shielding
    params = _nucleus_params(parameter_table, nucleus)
    if scaling_mode in (ScalingMode.PARAMETER_TABLE, ScalingMode.LINEAR):
        intercept = float(params.get("intercept", 0.0))
        slope = float(params.get("slope", 1.0))
        return intercept + slope * shielding
    raise ValueError(f"Unsupported scaling mode: {scaling_mode.value}")


def _normal_log_pdf(value: float, mean: float, stddev: float) -> float:
    if stddev <= 0:
        raise ValueError("Parameter table stddev must be positive")
    variance = stddev * stddev
    return -0.5 * math.log(2.0 * math.pi * variance) - ((value - mean) ** 2) / (2.0 * variance)


def _compute_error_stats(errors: list[float]) -> tuple[float, float]:
    if not errors:
        return float("nan"), float("nan")
    mae = sum(abs(value) for value in errors) / len(errors)
    rmse = math.sqrt(sum(value * value for value in errors) / len(errors))
    return mae, rmse


def _score_candidate(
    candidate: CandidateIsomer,
    assignments: list[ExperimentalAssignment],
    nuclei: tuple[str, ...],
    parameter_table: dict,
    config: DP4Config,
) -> CandidateScore:
    score = CandidateScore(candidate_name=candidate.name)
    log_likelihood_by_nucleus: dict[str, float] = {}

    for nucleus in nuclei:
        nucleus_assignments = [item for item in assignments if item.nucleus == nucleus]
        if not nucleus_assignments:
            continue
        params = _nucleus_params(parameter_table, nucleus)
        error_model = params.get("error_model", {})
        mean = float(error_model.get("mean", 0.0))
        stddev = float(error_model.get("stddev", 1.0))

        errors: list[float] = []
        log_likelihood = 0.0
        for assignment in nucleus_assignments:
            shielding = candidate.averaged_shieldings.get(nucleus, {}).get(assignment.candidate_atom_id)
            if shielding is None:
                raise ValueError(
                    f"Candidate '{candidate.name}' is missing shielding for atom "
                    f"{assignment.candidate_atom_id} nucleus {nucleus}. "
                    "Atom ids are matched exactly as parsed from the calculation output and may be zero-based."
                )
            predicted = predict_shift(shielding, nucleus, parameter_table, config.scaling_mode)
            error = assignment.exp_shift_ppm - predicted
            log_likelihood += _normal_log_pdf(error, mean, stddev)
            errors.append(error)
            score.shift_rows.append(
                ShiftRow(
                    atom_id=assignment.candidate_atom_id,
                    nucleus=nucleus,
                    exp_shift_ppm=assignment.exp_shift_ppm,
                    predicted_shift_ppm=predicted,
                    error_ppm=error,
                    label=assignment.label,
                )
            )

        mae, rmse = _compute_error_stats(errors)
        score.mae_by_nucleus[nucleus] = mae
        score.rmse_by_nucleus[nucleus] = rmse
        score.n_assignments_by_nucleus[nucleus] = len(nucleus_assignments)
        log_likelihood_by_nucleus[nucleus] = log_likelihood

    score.joint_log_likelihood = sum(log_likelihood_by_nucleus.values())
    score.probabilities = {nucleus: 0.0 for nucleus in nuclei}
    score.probabilities["_log_likelihood_by_nucleus"] = log_likelihood_by_nucleus
    return score


def _normalize_probabilities(candidate_scores: list[CandidateScore], nuclei: tuple[str, ...]) -> None:
    for nucleus in nuclei:
        values = [
            score.probabilities["_log_likelihood_by_nucleus"].get(nucleus, float("-inf"))
            for score in candidate_scores
        ]
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        max_log = max(finite)
        weights = [math.exp(value - max_log) if math.isfinite(value) else 0.0 for value in values]
        total = sum(weights)
        if total <= 0:
            continue
        for score, weight in zip(candidate_scores, weights):
            score.probabilities[nucleus] = weight / total

    joint_values = [score.joint_log_likelihood for score in candidate_scores]
    finite_joint = [value for value in joint_values if math.isfinite(value)]
    if not finite_joint:
        return
    max_joint = max(finite_joint)
    weights = [math.exp(value - max_joint) if math.isfinite(value) else 0.0 for value in joint_values]
    total = sum(weights)
    if total <= 0:
        return
    for score, weight in zip(candidate_scores, weights):
        score.joint_probability = weight / total
    for score in candidate_scores:
        score.probabilities.pop("_log_likelihood_by_nucleus", None)


def score_candidates(
    candidates: list[CandidateIsomer],
    assignments: list[ExperimentalAssignment],
    config: DP4Config,
    parameter_table: dict,
) -> list[CandidateScore]:
    scores = [
        _score_candidate(
            candidate=candidate,
            assignments=assignments,
            nuclei=config.nuclei,
            parameter_table=parameter_table,
            config=config,
        )
        for candidate in candidates
    ]
    _normalize_probabilities(scores, config.nuclei)
    return sorted(scores, key=lambda item: item.joint_probability, reverse=True)
