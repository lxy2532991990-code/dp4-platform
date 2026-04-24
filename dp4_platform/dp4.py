"""DP4+ scoring: sDP4+ (scaled) + uDP4+ (unscaled) with t-distribution error models.

Supports raw shielding, TMS-referenced, and chemical shift input data.
Auto-detects theory level and provides three parallel scoring modes:
  1. raw  — unscaled error model on raw computed shieldings
  2. tms  — unscaled error model on TMS-referenced shifts
  3. scaled — combined sDP4+ + uDP4+ on linearly scaled shifts
"""

from __future__ import annotations

import json
import math
from importlib import resources

from .config import DP4Config, ScalingMode, DataKind
from .models import (
    CandidateIsomer,
    CandidateScore,
    ExperimentalAssignment,
    LinearFit,
    ScoringSet,
    ShiftRow,
)


# ---------------------------------------------------------------------------
# parameter table helpers
# ---------------------------------------------------------------------------

def load_parameter_table(path: str | None) -> dict:
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    with resources.files("dp4_platform.data").joinpath("default_parameter_table.json").open(
        "r", encoding="utf-8"
    ) as fh:
        return json.load(fh)


def _normalize_basis(name: str) -> str:
    n = name.lower().replace(" ", "")
    n = n.replace("(d,p)", "**")
    n = n.replace("(d)", "*")
    n = n.replace("(p)", "*")
    n = n.replace("(f)", "*")
    return n


def _normalize_level_name(name: str) -> str:
    return _normalize_basis(name)


def resolve_level_params(parameter_table: dict, theory_level: str | None) -> dict | None:
    levels = parameter_table.get("levels")
    if not levels:
        return None
    if not theory_level:
        return None
    target = _normalize_level_name(theory_level)
    for level_name, level_data in levels.items():
        if _normalize_level_name(level_name) == target:
            return level_data["nuclei"]
    return None


def _get_effective_nuclei(parameter_table: dict, theory_level: str | None) -> dict:
    if theory_level:
        matched = resolve_level_params(parameter_table, theory_level)
        if matched:
            return matched
    return parameter_table.get("nuclei", {})


def _nucleus_params(parameter_table: dict, nucleus: str, theory_level: str | None) -> dict:
    nuclei = _get_effective_nuclei(parameter_table, theory_level)
    if nucleus not in nuclei:
        raise ValueError(f"Parameter table is missing settings for nucleus {nucleus}")
    return nuclei[nucleus]


# ---------------------------------------------------------------------------
# data kind detection
# ---------------------------------------------------------------------------

def detect_data_kind(candidates: list[CandidateIsomer], nuclei: tuple[str, ...]) -> DataKind:
    all_values: dict[str, list[float]] = {}
    for nucleus in nuclei:
        all_values[nucleus] = []
        for cand in candidates:
            sh = cand.averaged_shieldings.get(nucleus, {})
            all_values[nucleus].extend(sh.values())

    if "1H" in all_values and all_values["1H"]:
        h_vals = all_values["1H"]
        h_min = min(h_vals)
        h_max = max(h_vals)
        h_mean = sum(h_vals) / len(h_vals)
        if h_min > 18 and h_mean > 22:
            return DataKind.RAW_SHIELDING
        if h_max < 15 and h_mean < 8:
            return DataKind.CHEMICAL_SHIFT
        if h_mean > 15:
            return DataKind.RAW_SHIELDING

    if "13C" in all_values and all_values["13C"]:
        c_vals = all_values["13C"]
        c_min = min(c_vals)
        if c_min < 0:
            return DataKind.RAW_SHIELDING

    return DataKind.RAW_SHIELDING


# ---------------------------------------------------------------------------
# TMS referencing
# ---------------------------------------------------------------------------

def apply_tms_referencing(
    candidate: CandidateIsomer,
    tms_1h: float | None,
    tms_13c: float | None,
) -> dict[str, dict[int, float]]:
    """Convert raw shieldings to TMS-referenced shifts: δ = σ_TMS - σ_sample."""
    referenced: dict[str, dict[int, float]] = {}
    for nucleus, tms in [("1H", tms_1h), ("13C", tms_13c)]:
        if tms is None:
            referenced[nucleus] = dict(candidate.averaged_shieldings.get(nucleus, {}))
            continue
        referenced[nucleus] = {
            atom_id: tms - shielding
            for atom_id, shielding in candidate.averaged_shieldings.get(nucleus, {}).items()
        }
    candidate.averaged_shieldings = referenced
    return referenced


# ---------------------------------------------------------------------------
# t-distribution
# ---------------------------------------------------------------------------

def _t_log_pdf(x: float, mu: float, sigma: float, nu: float) -> float:
    if sigma <= 0 or nu <= 0:
        raise ValueError("t-distribution requires sigma > 0 and nu > 0")
    z = (x - mu) / sigma
    return (
        math.lgamma((nu + 1.0) / 2.0)
        - math.lgamma(nu / 2.0)
        - 0.5 * math.log(nu * math.pi)
        - math.log(sigma)
        - ((nu + 1.0) / 2.0) * math.log1p(z * z / nu)
    )


# ---------------------------------------------------------------------------
# error-model dispatch
# ---------------------------------------------------------------------------

def _get_scaled_error_params(params: dict) -> dict:
    if "scaled_error" in params:
        se = params["scaled_error"]
        return {
            "distribution": se.get("distribution", "t"),
            "mu": float(se.get("mu", 0.0)),
            "sigma": float(se.get("sigma", 1.0)),
            "nu": float(se.get("nu", 5.0)),
        }
    if "error_model" in params:
        em = params["error_model"]
        return {
            "distribution": em.get("distribution", "normal"),
            "mu": float(em.get("mean", 0.0)),
            "sigma": float(em.get("stddev", 1.0)),
            "nu": float(em.get("nu", 5.0)),
        }
    return {"distribution": "normal", "mu": 0.0, "sigma": 1.0, "nu": 5.0}


def _get_unscaled_error_params(params: dict, hyb: str) -> dict | None:
    ue = params.get("unscaled_error")
    if not ue:
        return None
    entry = ue.get(hyb) or ue.get("default")
    if not entry:
        return None
    return {
        "distribution": entry.get("distribution", "t"),
        "mu": float(entry.get("mu", 0.0)),
        "sigma": float(entry.get("sigma", 1.0)),
        "nu": float(entry.get("nu", 5.0)),
    }


def _compute_log_likelihood(errors: list[float], em: dict) -> float:
    total = 0.0
    for error in errors:
        if em["distribution"] == "t":
            total += _t_log_pdf(error, em["mu"], em["sigma"], em["nu"])
        else:
            total += _normal_log_pdf(error, em["mu"], em["sigma"])
    return total


def _normal_log_pdf(value: float, mean: float, stddev: float) -> float:
    if stddev <= 0:
        raise ValueError("Parameter table stddev must be positive")
    variance = stddev * stddev
    return -0.5 * math.log(2.0 * math.pi * variance) - ((value - mean) ** 2) / (2.0 * variance)


# ---------------------------------------------------------------------------
# shift prediction
# ---------------------------------------------------------------------------

def predict_shift(
    shielding: float,
    nucleus: str,
    parameter_table: dict,
    scaling_mode: ScalingMode,
    theory_level: str | None = None,
) -> float:
    if scaling_mode == ScalingMode.IDENTITY:
        return shielding
    params = _nucleus_params(parameter_table, nucleus, theory_level)
    if scaling_mode in (ScalingMode.PARAMETER_TABLE, ScalingMode.LINEAR):
        intercept = float(params.get("intercept", 0.0))
        slope = float(params.get("slope", 1.0))
        return intercept + slope * shielding
    raise ValueError(f"Unsupported scaling mode: {scaling_mode.value}")


# ---------------------------------------------------------------------------
# per-isomer linear regression
# ---------------------------------------------------------------------------

def fit_linear(
    x_values: list[float],
    y_values: list[float],
) -> tuple[float, float, float]:
    """Least-squares fit y = a + b * x.  Returns (intercept, slope, r_squared)."""
    n = len(x_values)
    if n < 2:
        return 0.0, 1.0, 0.0

    sx = sum(x_values)
    sy = sum(y_values)
    sxy = sum(x * y for x, y in zip(x_values, y_values))
    sxx = sum(x * x for x in x_values)
    syy = sum(y * y for y in y_values)

    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, 1.0, 0.0

    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n

    # R²
    y_mean = sy / n
    ss_tot = syy - n * y_mean * y_mean
    if ss_tot == 0:
        return a, b, 1.0

    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(x_values, y_values))
    r2 = 1.0 - ss_res / ss_tot
    return a, b, r2


def per_isomer_linear_fits(
    candidates: list[CandidateIsomer],
    assignments: list[ExperimentalAssignment],
    nuclei: tuple[str, ...],
    use_tms_referenced: bool = False,
) -> list[LinearFit]:
    """Compute per-isomer linear regression parameters.

    For each isomer and nucleus, fits ``exp = intercept + slope * computed``
    using the matched assignment pairs.
    """
    fits: list[LinearFit] = []

    for candidate in candidates:
        for nucleus in nuclei:
            nucleus_assignments = [a for a in assignments if a.nucleus == nucleus]
            if not nucleus_assignments:
                continue

            x_vals: list[float] = []
            y_vals: list[float] = []
            for a in nucleus_assignments:
                shielding = candidate.averaged_shieldings.get(nucleus, {}).get(a.candidate_atom_id)
                if shielding is None:
                    continue
                x_vals.append(shielding)
                y_vals.append(a.exp_shift_ppm)

            if len(x_vals) < 2:
                continue

            intercept, slope, r2 = fit_linear(x_vals, y_vals)
            fits.append(LinearFit(
                candidate_name=candidate.name,
                nucleus=nucleus,
                intercept=intercept,
                slope=slope,
                r_squared=r2,
            ))

    return fits


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _compute_error_stats(errors: list[float]) -> tuple[float, float]:
    if not errors:
        return float("nan"), float("nan")
    mae = sum(abs(value) for value in errors) / len(errors)
    rmse = math.sqrt(sum(value * value for value in errors) / len(errors))
    return mae, rmse


def _hyb_key_for_nucleus(atom_id: int, nucleus: str, candidate: CandidateIsomer) -> str:
    raw = candidate.atom_hybridizations.get(atom_id, "unknown")
    hyb = str(raw).lower()
    if nucleus == "1H":
        return f"on_{hyb}_carbon"
    return hyb


# ---------------------------------------------------------------------------
# single-mode scoring
# ---------------------------------------------------------------------------

def _score_candidate_single_mode(
    candidate: CandidateIsomer,
    assignments: list[ExperimentalAssignment],
    nuclei: tuple[str, ...],
    parameter_table: dict,
    theory_level: str | None,
    mode: str,
    linear_fit_map: dict[str, dict[str, tuple[float, float]]] | None = None,
) -> CandidateScore:
    """Score one candidate in one mode.

    Parameters
    ----------
    mode: "raw" | "tms" | "scaled"
        - raw:    unscaled error model on raw shieldings
        - tms:    unscaled error model on TMS-referenced shifts
        - scaled: scaled error model + unscaled (combined), with per-isomer or table scaling
    linear_fit_map: {candidate_name: {nucleus: (intercept, slope)}} for per-isomer scaled mode
    """
    score = CandidateScore(candidate_name=candidate.name)

    for nucleus in nuclei:
        nucleus_assignments = [a for a in assignments if a.nucleus == nucleus]
        if not nucleus_assignments:
            continue
        params = _nucleus_params(parameter_table, nucleus, theory_level)

        scaled_em = _get_scaled_error_params(params)
        scaled_errors: list[float] = []

        # determine scaling for this isomer + nucleus
        if mode == "scaled" and linear_fit_map and candidate.name in linear_fit_map:
            fit = linear_fit_map[candidate.name].get(nucleus)
            if fit is not None:
                sc_intercept, sc_slope = fit
            else:
                sc_intercept = float(params.get("intercept", 0.0))
                sc_slope = float(params.get("slope", 1.0))
        else:
            sc_intercept = float(params.get("intercept", 0.0))
            sc_slope = float(params.get("slope", 1.0))

        for assignment in nucleus_assignments:
            atom_id = assignment.candidate_atom_id
            shielding = candidate.averaged_shieldings.get(nucleus, {}).get(atom_id)
            if shielding is None:
                raise ValueError(
                    f"Candidate '{candidate.name}' is missing shielding for atom "
                    f"{atom_id} nucleus {nucleus}."
                )

            if mode == "scaled":
                predicted = sc_intercept + sc_slope * shielding
            else:
                predicted = shielding  # raw or tms: no linear scaling

            scaled_error = assignment.exp_shift_ppm - predicted
            scaled_errors.append(scaled_error)

            score.shift_rows.append(
                ShiftRow(
                    atom_id=atom_id,
                    nucleus=nucleus,
                    exp_shift_ppm=assignment.exp_shift_ppm,
                    predicted_shift_ppm=predicted,
                    error_ppm=scaled_error,
                    label=assignment.label,
                )
            )

        # scaled log-likelihood (only used in "scaled" mode)
        if mode == "scaled":
            scaled_log_lik = _compute_log_likelihood(scaled_errors, scaled_em)
        else:
            scaled_log_lik = 0.0

        # unscaled log-likelihood (used in all modes)
        unscaled_log_lik = 0.0
        for assignment in nucleus_assignments:
            atom_id = assignment.candidate_atom_id
            shielding = candidate.averaged_shieldings.get(nucleus, {}).get(atom_id)
            if shielding is None:
                continue
            unsealed_error = assignment.exp_shift_ppm - shielding
            hyb_key = _hyb_key_for_nucleus(atom_id, nucleus, candidate)
            unscaled_em = _get_unscaled_error_params(params, hyb_key)
            if unscaled_em is not None:
                unscaled_log_lik += _compute_log_likelihood([unsealed_error], unscaled_em)

        nucleus_log_lik = scaled_log_lik + unscaled_log_lik

        mae, rmse = _compute_error_stats(scaled_errors)
        score.mae_by_nucleus[nucleus] = mae
        score.rmse_by_nucleus[nucleus] = rmse
        score.n_assignments_by_nucleus[nucleus] = len(nucleus_assignments)
        score.probabilities["_log_likelihood_by_nucleus"] = score.probabilities.get(
            "_log_likelihood_by_nucleus", {}
        )
        score.probabilities["_log_likelihood_by_nucleus"][nucleus] = nucleus_log_lik

    log_lik_by_nuc = score.probabilities.get("_log_likelihood_by_nucleus", {})
    score.joint_log_likelihood = sum(v for v in log_lik_by_nuc.values() if v is not None)
    return score


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------

def _normalize_probabilities(candidate_scores: list[CandidateScore], nuclei: tuple[str, ...]) -> None:
    for nucleus in nuclei:
        values = [
            score.probabilities.get("_log_likelihood_by_nucleus", {}).get(nucleus, float("-inf"))
            for score in candidate_scores
        ]
        finite = [v for v in values if math.isfinite(v)]
        if not finite:
            continue
        max_log = max(finite)
        weights = [math.exp(v - max_log) if math.isfinite(v) else 0.0 for v in values]
        total = sum(weights)
        if total <= 0:
            continue
        for score, weight in zip(candidate_scores, weights):
            score.probabilities[nucleus] = weight / total

    joint_values = [score.joint_log_likelihood for score in candidate_scores]
    finite_joint = [v for v in joint_values if math.isfinite(v)]
    if not finite_joint:
        return
    max_joint = max(finite_joint)
    weights = [math.exp(v - max_joint) if math.isfinite(v) else 0.0 for v in joint_values]
    total = sum(weights)
    if total <= 0:
        return
    for score, weight in zip(candidate_scores, weights):
        score.joint_probability = weight / total
    for score in candidate_scores:
        score.probabilities.pop("_log_likelihood_by_nucleus", None)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def score_candidates(
    candidates: list[CandidateIsomer],
    assignments: list[ExperimentalAssignment],
    config: DP4Config,
    parameter_table: dict,
    theory_level: str | None = None,
) -> list[CandidateScore]:
    """Legacy single-mode scoring (uses "scaled" mode)."""
    scores = [
        _score_candidate_single_mode(
            candidate=candidate,
            assignments=assignments,
            nuclei=config.nuclei,
            parameter_table=parameter_table,
            theory_level=theory_level,
            mode="scaled",
        )
        for candidate in candidates
    ]
    _normalize_probabilities(scores, config.nuclei)
    return sorted(scores, key=lambda item: item.joint_probability, reverse=True)


def score_candidates_all_modes(
    candidates: list[CandidateIsomer],
    assignments: list[ExperimentalAssignment],
    config: DP4Config,
    parameter_table: dict,
    theory_level: str | None = None,
    linear_fits: list[LinearFit] | None = None,
) -> list[ScoringSet]:
    """Run three scoring passes and return all results.

    Returns a list of three ScoringSet objects:
      - "raw":    unscaled error model on raw computed shieldings
      - "tms":    unscaled error model on TMS-referenced shifts
      - "scaled": combined sDP4+ + uDP4+ with per-isomer linear scaling

    Each candidate's original ``averaged_shieldings`` are assumed to be
    TMS-referenced (if TMS was applied). The "raw" mode uses the original
    raw shieldings stored in ``_raw_shieldings`` if available, otherwise
    falls back to the current shieldings.
    """
    # build per-isomer linear fit lookup
    linear_fit_map: dict[str, dict[str, tuple[float, float]]] = {}
    if linear_fits:
        for lf in linear_fits:
            linear_fit_map.setdefault(lf.candidate_name, {})[lf.nucleus] = (lf.intercept, lf.slope)

    # pick which data to use for "raw" vs "tms" modes
    # If TMS was applied, the current shieldings are TMS-referenced,
    # and _raw_shieldings (if set) holds the original raw values.
    scoring_sets: list[ScoringSet] = []

    # --- mode: raw (unscaled only, on raw shieldings) ---
    # Use _raw_shieldings if available, else fall back
    for candidate in candidates:
        if not hasattr(candidate, "_raw_shieldings") or candidate._raw_shieldings is None:
            candidate._raw_shieldings = dict(candidate.averaged_shieldings)

    saved_tms = {c.name: dict(c.averaged_shieldings) for c in candidates}

    # Temporarily restore raw shieldings for "raw" mode scoring
    for candidate in candidates:
        raw = getattr(candidate, "_raw_shieldings", None)
        if raw:
            candidate.averaged_shieldings = raw

    raw_scores = [
        _score_candidate_single_mode(c, assignments, config.nuclei, parameter_table,
                                     theory_level, mode="raw")
        for c in candidates
    ]
    _normalize_probabilities(raw_scores, config.nuclei)
    raw_sorted = sorted(raw_scores, key=lambda s: s.joint_probability, reverse=True)
    scoring_sets.append(ScoringSet(mode="raw", label="Raw shielding", candidate_scores=raw_sorted))

    # --- mode: tms (unscaled only, on TMS-referenced data) ---
    for candidate in candidates:
        candidate.averaged_shieldings = saved_tms[candidate.name]

    tms_scores = [
        _score_candidate_single_mode(c, assignments, config.nuclei, parameter_table,
                                     theory_level, mode="tms")
        for c in candidates
    ]
    _normalize_probabilities(tms_scores, config.nuclei)
    tms_sorted = sorted(tms_scores, key=lambda s: s.joint_probability, reverse=True)
    scoring_sets.append(ScoringSet(mode="tms", label="TMS referenced", candidate_scores=tms_sorted))

    # --- mode: scaled (combined sDP4+ + uDP4+, per-isomer linear scaling) ---
    scaled_scores = [
        _score_candidate_single_mode(c, assignments, config.nuclei, parameter_table,
                                     theory_level, mode="scaled", linear_fit_map=linear_fit_map)
        for c in candidates
    ]
    _normalize_probabilities(scaled_scores, config.nuclei)
    scaled_sorted = sorted(scaled_scores, key=lambda s: s.joint_probability, reverse=True)
    scoring_sets.append(ScoringSet(mode="scaled", label="Linear scaled", candidate_scores=scaled_sorted))

    return scoring_sets
