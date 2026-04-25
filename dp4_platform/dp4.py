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
import re
from difflib import get_close_matches
from importlib import resources

from .config import DP4Config, ScalingMode, DataKind
from .diastereotopic import reassign_diastereotopic_pairs
from .halo import apply_mstd_unscaled, mstd_key
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
            return validate_parameter_table(json.load(fh))
    data_root = resources.files("dp4_platform.data")
    for filename in ("dp4plus_parameter_table.json", "default_parameter_table.json"):
        resource = data_root.joinpath(filename)
        if resource.is_file():
            with resource.open("r", encoding="utf-8") as fh:
                return validate_parameter_table(json.load(fh))
    raise FileNotFoundError("No DP4 parameter table is bundled with dp4_platform.data")


def validate_parameter_table(parameter_table: dict) -> dict:
    """Validate the minimal fields needed by v1/v2 parameter tables."""
    if parameter_table.get("schema_version") != 2:
        if "nuclei" not in parameter_table and "levels" not in parameter_table:
            raise ValueError("Parameter table must define either 'nuclei' or 'levels'")
        return parameter_table

    if not parameter_table.get("sources"):
        raise ValueError("schema v2 parameter table must define 'sources'")
    levels = parameter_table.get("levels")
    if not isinstance(levels, dict) or not levels:
        raise ValueError("schema v2 parameter table must define non-empty 'levels'")
    for level_name, level_data in levels.items():
        nuclei = level_data.get("nuclei")
        if not isinstance(nuclei, dict) or not ({"1H", "13C"} & set(nuclei)):
            raise ValueError(f"Level '{level_name}' must define at least one supported nucleus")
        for nucleus, params in nuclei.items():
            if "scaled_error" not in params:
                raise ValueError(f"Level '{level_name}' nucleus {nucleus} lacks scaled_error")
            if _get_scaling_input(params) not in {"shielding", "unscaled_shift"}:
                raise ValueError(f"Level '{level_name}' nucleus {nucleus} has invalid scaling_input")
            mstd = params.get("mstd_reference")
            if mstd is not None:
                if not isinstance(mstd, dict):
                    raise ValueError(
                        f"Level '{level_name}' nucleus {nucleus} mstd_reference must be a mapping"
                    )
                for key, entry in mstd.items():
                    if not isinstance(entry, dict):
                        raise ValueError(
                            f"Level '{level_name}' nucleus {nucleus} mstd_reference['{key}'] must be a mapping"
                        )
                    for field_name in ("shielding_standard", "reference_value"):
                        if not isinstance(entry.get(field_name), (int, float)):
                            raise ValueError(
                                f"Level '{level_name}' nucleus {nucleus} mstd_reference['{key}'] "
                                f"missing numeric '{field_name}'"
                            )
    return parameter_table


def _normalize_basis(name: str) -> str:
    n = name.lower().replace(" ", "")
    n = n.replace("\\", "/")
    n = n.replace("m06-2x", "m062x")
    n = n.replace("m06_2x", "m062x")
    n = n.replace("wb97x-d", "wb97xd")
    n = n.replace("w-b97xd", "wb97xd")
    n = n.replace("(d,p)", "**")
    n = n.replace("(d)", "*")
    n = n.replace("(p)", "*")
    n = n.replace("(f)", "*")
    return n


def _normalize_level_name(name: str) -> str:
    n = _normalize_basis(str(name))
    n = n.replace("dp4+app", "")
    n = n.replace("mm-dp4+", "mmdp4")
    n = n.replace("dp4+", "dp4")
    return re.sub(r"[^a-z0-9+*]+", "", n)


def _iter_level_aliases(level_name: str, level_data: dict):
    yield level_name
    if level_data.get("original_name"):
        yield str(level_data["original_name"])
    if level_data.get("nmr_level"):
        yield str(level_data["nmr_level"])
    for alias in level_data.get("aliases", []):
        yield str(alias)


def _level_alias_index(parameter_table: dict) -> dict[str, tuple[str, dict, str]]:
    index: dict[str, tuple[str, dict, str]] = {}
    for level_name, level_data in parameter_table.get("levels", {}).items():
        for alias in _iter_level_aliases(level_name, level_data):
            norm = _normalize_level_name(alias)
            index.setdefault(norm, (level_name, level_data, alias))
    return index


def _fallback_level_name(parameter_table: dict) -> str | None:
    levels = parameter_table.get("levels", {})
    fallback = parameter_table.get("fallback_level") or parameter_table.get("default_level")
    if fallback in levels:
        return fallback
    if fallback:
        match = _level_alias_index(parameter_table).get(_normalize_level_name(fallback))
        if match:
            return match[0]
    return next(iter(levels), None)


def resolve_level_match(parameter_table: dict, theory_level: str | None) -> dict:
    """Resolve a requested theory level to a parameter-table level with provenance."""
    levels = parameter_table.get("levels") or {}
    if not levels:
        return {
            "requested_level": theory_level,
            "matched": False,
            "fallback": False,
            "matched_by": "table_without_levels",
            "level_name": None,
            "level_data": None,
            "nuclei": parameter_table.get("nuclei", {}),
            "warnings": [],
            "candidates": [],
        }

    alias_index = _level_alias_index(parameter_table)
    warnings: list[str] = []
    candidates: list[str] = []
    if theory_level:
        normalized = _normalize_level_name(theory_level)
        if normalized in alias_index:
            level_name, level_data, alias = alias_index[normalized]
            matched_by = "exact" if _normalize_level_name(level_name) == normalized else f"alias:{alias}"
            return {
                "requested_level": theory_level,
                "matched": True,
                "fallback": False,
                "matched_by": matched_by,
                "level_name": level_name,
                "level_data": level_data,
                "nuclei": level_data.get("nuclei", {}),
                "warnings": [],
                "candidates": [],
            }
        candidates = get_close_matches(normalized, list(alias_index), n=5, cutoff=0.45)
        candidates = [alias_index[item][0] for item in candidates]
        # Keep order while removing duplicates.
        candidates = list(dict.fromkeys(candidates))

    fallback_name = _fallback_level_name(parameter_table)
    fallback_data = levels.get(fallback_name, {}) if fallback_name else {}
    if theory_level:
        warnings.append(
            f"Theory level '{theory_level}' was not found in the parameter library; "
            f"using fallback '{fallback_name}'. Treat this result as lower confidence."
        )
    else:
        warnings.append(
            f"No theory level was detected; using fallback '{fallback_name}'. "
            "Treat this result as lower confidence."
        )
    if candidates:
        warnings.append("Closest available parameter levels: " + ", ".join(candidates[:5]))
    return {
        "requested_level": theory_level,
        "matched": False,
        "fallback": True,
        "matched_by": "fallback",
        "level_name": fallback_name,
        "level_data": fallback_data,
        "nuclei": fallback_data.get("nuclei", parameter_table.get("nuclei", {})),
        "warnings": warnings,
        "candidates": candidates,
    }


def resolve_level_params(parameter_table: dict, theory_level: str | None) -> dict | None:
    match = resolve_level_match(parameter_table, theory_level)
    if match.get("matched"):
        return match.get("nuclei")
    return None


def _get_effective_nuclei(parameter_table: dict, theory_level: str | None) -> dict:
    match = resolve_level_match(parameter_table, theory_level)
    if match.get("nuclei"):
        return match["nuclei"]
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
            continue
        referenced[nucleus] = {
            atom_id: tms - shielding
            for atom_id, shielding in candidate.averaged_shieldings.get(nucleus, {}).items()
        }
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


def _betacf(a: float, b: float, x: float) -> float:
    max_iter = 200
    eps = 3.0e-14
    tiny = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    bt = math.exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_cdf(x: float, nu: float) -> float:
    if nu <= 0:
        raise ValueError("t-distribution requires nu > 0")
    if x == 0:
        return 0.5
    beta_x = nu / (nu + x * x)
    ib = _regularized_incomplete_beta(nu / 2.0, 0.5, beta_x)
    if x > 0:
        return 1.0 - 0.5 * ib
    return 0.5 * ib


def _student_t_tail_log_probability(error: float, mu: float, sigma: float, nu: float) -> float:
    if sigma <= 0 or nu <= 0:
        raise ValueError("student_t_tail requires sigma > 0 and nu > 0")
    z = abs((error - mu) / sigma)
    tail = 1.0 - _t_cdf(z, nu)
    return math.log(max(tail, 1.0e-300))


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


def _normalize_error_params(entry: dict) -> dict:
    return {
        "distribution": entry.get("distribution", "t"),
        "mu": float(entry.get("mu", entry.get("mean", 0.0))),
        "sigma": float(entry.get("sigma", entry.get("stddev", 1.0))),
        "nu": float(entry.get("nu", 5.0)),
    }


def _get_unscaled_error_params(params: dict, hyb: str) -> dict | None:
    ue = params.get("unscaled_error")
    if not ue:
        return None
    entry = ue.get(hyb) or ue.get("default")
    if not entry:
        return None
    return _normalize_error_params(entry)


def _get_raw_error_params(params: dict, hyb: str) -> dict | None:
    raw = params.get("raw_shielding_error")
    if not raw:
        return None
    if any(key in raw for key in ("distribution", "mu", "mean", "sigma", "stddev")):
        return _normalize_error_params(raw)
    entry = raw.get(hyb) or raw.get("default")
    if not entry:
        return None
    return _normalize_error_params(entry)


def _get_scaling_input(params: dict) -> str:
    value = str(params.get("scaling_input", "shielding")).strip().lower()
    aliases = {
        "raw": "shielding",
        "sigma": "shielding",
        "shieldings": "shielding",
        "shift": "unscaled_shift",
        "chemical_shift": "unscaled_shift",
        "tms": "unscaled_shift",
        "tms_referenced": "unscaled_shift",
        "unscaled": "unscaled_shift",
    }
    value = aliases.get(value, value)
    if value not in {"shielding", "unscaled_shift"}:
        raise ValueError(f"Unsupported scaling_input: {value}")
    return value


def _compute_log_likelihood(errors: list[float], em: dict) -> float:
    total = 0.0
    for error in errors:
        if em["distribution"] in {"student_t_tail", "t_tail"}:
            total += _student_t_tail_log_probability(error, em["mu"], em["sigma"], em["nu"])
        elif em["distribution"] == "t":
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
    if _get_scaling_input(params) == "unscaled_shift":
        reference = params.get("reference_shielding")
        if reference is None:
            raise ValueError(
                "This parameter table scales unscaled chemical shifts; "
                "TMS-referenced values are required instead of raw shieldings."
            )
        shielding = float(reference) - shielding
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
    value_maps_by_candidate: dict[str, dict[str, dict[int, float]]] | None = None,
    regression_modes_by_nucleus: dict[str, str] | None = None,
) -> list[LinearFit]:
    """Compute per-isomer linear regression parameters.

    For DP4+App-style tables, fits ``computed = intercept + slope * exp``.
    Legacy shielding-domain tables can request ``direct`` mode, which fits
    ``exp = intercept + slope * computed``.
    """
    fits: list[LinearFit] = []

    for candidate in candidates:
        value_map = (
            value_maps_by_candidate.get(candidate.name, candidate.averaged_shieldings)
            if value_maps_by_candidate is not None
            else candidate.averaged_shieldings
        )
        for nucleus in nuclei:
            nucleus_assignments = [a for a in assignments if a.nucleus == nucleus]
            if not nucleus_assignments:
                continue

            calc_vals: list[float] = []
            exp_vals: list[float] = []
            for a in nucleus_assignments:
                calc_value = value_map.get(nucleus, {}).get(a.candidate_atom_id)
                if calc_value is None:
                    continue
                calc_vals.append(calc_value)
                exp_vals.append(a.exp_shift_ppm)

            if len(calc_vals) < 2:
                continue

            regression_mode = (regression_modes_by_nucleus or {}).get(nucleus, "inverse")
            if regression_mode == "direct":
                intercept, slope, r2 = fit_linear(calc_vals, exp_vals)
            else:
                intercept, slope, r2 = fit_linear(exp_vals, calc_vals)
                if not math.isfinite(slope) or abs(slope) < 1.0e-12:
                    continue
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


def _halo_override_value_map(
    candidate: CandidateIsomer,
    nucleus: str,
    value_map: dict[int, float],
    params: dict,
    warnings_sink: list[str] | None,
    seen_warnings: set[str] | None = None,
) -> tuple[dict[int, float], dict[int, str]]:
    """Replace halogen-adjacent atom values with MSTD-corrected unscaled shifts.

    Returns ``(new_map, applied_halogens)`` where ``applied_halogens`` records
    which atom_ids actually got the override (so callers can populate
    ``ShiftRow.halogen_neighbor``). Atoms without an MSTD entry, or with
    unknown hybridization, fall back to the input value and emit a one-time
    warning into ``warnings_sink``.
    """
    halogen_map = candidate.halogen_neighbor or {}
    if not halogen_map:
        return value_map, {}

    mstd_table = params.get("mstd_reference") or {}
    raw_shieldings = candidate.averaged_shieldings.get(nucleus, {}) if candidate.averaged_shieldings else {}
    new_map = dict(value_map)
    applied: dict[int, str] = {}
    seen_warnings = seen_warnings if seen_warnings is not None else set()

    for atom_id, halogen in halogen_map.items():
        if atom_id not in new_map:
            continue
        raw_hyb = candidate.atom_hybridizations.get(atom_id)
        hyb = str(raw_hyb).lower() if raw_hyb is not None else "unknown"
        if hyb not in {"sp2", "sp3"}:
            warning_key = f"halo:{candidate.name}:{atom_id}:unknown_hyb"
            if warnings_sink is not None and warning_key not in seen_warnings:
                warnings_sink.append(
                    f"HALO override skipped for atom {atom_id} ({nucleus}) on candidate "
                    f"'{candidate.name}': hybridization '{hyb}' is outside sp2/sp3."
                )
                seen_warnings.add(warning_key)
            continue
        key = mstd_key(nucleus, halogen, hyb)
        if key is None:
            continue
        entry = mstd_table.get(key)
        if entry is None:
            warning_key = f"halo:{nucleus}:{key}"
            if warnings_sink is not None and warning_key not in seen_warnings:
                warnings_sink.append(
                    f"HALO override skipped: parameter table has no mstd_reference['{key}'] "
                    f"for nucleus {nucleus}. Falling back to default unscaled shift."
                )
                seen_warnings.add(warning_key)
            continue
        sigma = raw_shieldings.get(atom_id)
        if sigma is None:
            warning_key = f"halo:missing_sigma:{candidate.name}:{atom_id}"
            if warnings_sink is not None and warning_key not in seen_warnings:
                warnings_sink.append(
                    f"HALO override skipped for atom {atom_id} ({nucleus}) on candidate "
                    f"'{candidate.name}': raw shielding unavailable."
                )
                seen_warnings.add(warning_key)
            continue
        new_map[atom_id] = apply_mstd_unscaled(sigma, entry)
        applied[atom_id] = halogen

    return new_map, applied


# ---------------------------------------------------------------------------
# scoring helpers
# ---------------------------------------------------------------------------

def _candidate_value_map(candidate: CandidateIsomer, values_by_candidate: dict[str, dict[str, dict[int, float]]]) -> dict[str, dict[int, float]]:
    return values_by_candidate.get(candidate.name, {})


def _available_nuclei_for_values(
    candidates: list[CandidateIsomer],
    values_by_candidate: dict[str, dict[str, dict[int, float]]],
    nuclei: tuple[str, ...],
) -> tuple[str, ...]:
    available: list[str] = []
    for nucleus in nuclei:
        if all(_candidate_value_map(candidate, values_by_candidate).get(nucleus) for candidate in candidates):
            available.append(nucleus)
    return tuple(available)


def _raw_value_maps(candidates: list[CandidateIsomer]) -> dict[str, dict[str, dict[int, float]]]:
    return {
        candidate.name: {
            nucleus: dict(values)
            for nucleus, values in candidate.averaged_shieldings.items()
        }
        for candidate in candidates
    }


def _tms_value_maps(candidates: list[CandidateIsomer]) -> dict[str, dict[str, dict[int, float]]]:
    return {
        candidate.name: {
            nucleus: dict(values)
            for nucleus, values in candidate.tms_referenced_shifts.items()
        }
        for candidate in candidates
    }


def scaled_regression_modes(
    parameter_table: dict,
    nuclei: tuple[str, ...],
    theory_level: str | None = None,
) -> dict[str, str]:
    """Return per-nucleus regression semantics for scaled scoring."""
    modes: dict[str, str] = {}
    for nucleus in nuclei:
        params = _nucleus_params(parameter_table, nucleus, theory_level)
        modes[nucleus] = "inverse" if _get_scaling_input(params) == "unscaled_shift" else "direct"
    return modes


def build_scaled_input_maps(
    candidates: list[CandidateIsomer],
    config: DP4Config,
    parameter_table: dict,
    theory_level: str | None = None,
) -> tuple[dict[str, dict[str, dict[int, float]]], tuple[str, ...], list[str], str]:
    """Build the per-candidate input maps used by scaled scoring."""
    raw_maps = _raw_value_maps(candidates)
    tms_maps = _tms_value_maps(candidates)
    scaled_maps: dict[str, dict[str, dict[int, float]]] = {
        candidate.name: {} for candidate in candidates
    }
    warnings: list[str] = []
    formula_parts: list[str] = []

    for nucleus in config.nuclei:
        params = _nucleus_params(parameter_table, nucleus, theory_level)
        scaling_input = _get_scaling_input(params)
        if scaling_input == "shielding":
            for candidate in candidates:
                values = _candidate_value_map(candidate, raw_maps).get(nucleus, {})
                if values:
                    scaled_maps[candidate.name][nucleus] = dict(values)
            formula_parts.append(f"{nucleus}: delta_scaled = intercept + slope * sigma_sample")
            continue

        if scaling_input == "unscaled_shift":
            if nucleus not in _available_nuclei_for_values(candidates, tms_maps, (nucleus,)):
                warnings.append(
                    f"{nucleus} scaled scoring requires TMS-referenced chemical shifts; "
                    "this nucleus was skipped."
                )
                continue
            for candidate in candidates:
                scaled_maps[candidate.name][nucleus] = dict(
                    _candidate_value_map(candidate, tms_maps).get(nucleus, {})
                )
            formula_parts.append(
                f"{nucleus}: delta_unscaled = slope * delta_exp + intercept; "
                "delta_scaled = (delta_unscaled - intercept) / slope"
            )

    scaled_nuclei = _available_nuclei_for_values(candidates, scaled_maps, config.nuclei)
    if not scaled_nuclei:
        warnings.append("Scaled scoring has no usable nuclei after applying scaling_input requirements.")
    return scaled_maps, scaled_nuclei, warnings, "; ".join(formula_parts)


def _score_candidate_values(
    candidate: CandidateIsomer,
    assignments: list[ExperimentalAssignment],
    nuclei: tuple[str, ...],
    parameter_table: dict,
    theory_level: str | None,
    calc_values: dict[str, dict[int, float]],
    mode: str,
    unscaled_values: dict[str, dict[int, float]] | None = None,
    linear_fit_map: dict[str, dict[str, tuple[float, float]]] | None = None,
    warnings_sink: list[str] | None = None,
    halo_warning_dedup: set[str] | None = None,
) -> CandidateScore:
    score = CandidateScore(candidate_name=candidate.name)

    for nucleus in nuclei:
        values_for_nucleus = calc_values.get(nucleus, {})
        if not values_for_nucleus:
            continue
        nucleus_assignments = [a for a in assignments if a.nucleus == nucleus]
        if not nucleus_assignments:
            continue
        params = _nucleus_params(parameter_table, nucleus, theory_level)

        scaling_input = _get_scaling_input(params)
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

        # HALO MSTD override (mode-dependent, runs before diastereotopic swap so the
        # swap re-pairs against post-override values, matching upstream HALO_module).
        halo_applied: dict[int, str] = {}
        if mode == "tms" and candidate.halogen_neighbor:
            values_for_nucleus, halo_applied = _halo_override_value_map(
                candidate, nucleus, values_for_nucleus, params,
                warnings_sink, halo_warning_dedup,
            )

        sense = "shielding" if mode == "raw" or scaling_input == "shielding" else "shift"
        nucleus_calc_map = {
            a.candidate_atom_id: values_for_nucleus.get(a.candidate_atom_id)
            for a in nucleus_assignments
            if values_for_nucleus.get(a.candidate_atom_id) is not None
        }
        swapped_calc, swaps = reassign_diastereotopic_pairs(
            nucleus_assignments, nucleus_calc_map, sense=sense
        )
        if swaps:
            values_for_nucleus = {**values_for_nucleus, **swapped_calc}
        unscaled_for_nucleus = dict((unscaled_values or {}).get(nucleus, {}))
        unscaled_halo_applied: dict[int, str] = {}
        if mode == "scaled" and unscaled_for_nucleus and candidate.halogen_neighbor:
            unscaled_for_nucleus, unscaled_halo_applied = _halo_override_value_map(
                candidate, nucleus, unscaled_for_nucleus, params,
                warnings_sink, halo_warning_dedup,
            )
        if swaps and unscaled_for_nucleus:
            for atom_a, atom_b in swaps:
                if atom_a in unscaled_for_nucleus and atom_b in unscaled_for_nucleus:
                    unscaled_for_nucleus[atom_a], unscaled_for_nucleus[atom_b] = (
                        unscaled_for_nucleus[atom_b],
                        unscaled_for_nucleus[atom_a],
                    )
        swap_lookup: dict[int, int] = {}
        for atom_a, atom_b in swaps:
            swap_lookup[atom_a] = atom_b
            swap_lookup[atom_b] = atom_a
        applied_halogens = halo_applied or unscaled_halo_applied

        errors: list[float] = []
        predicted_by_atom: dict[int, float] = {}
        for assignment in nucleus_assignments:
            atom_id = assignment.candidate_atom_id
            calc_value = values_for_nucleus.get(atom_id)
            if calc_value is None:
                raise ValueError(
                    f"Candidate '{candidate.name}' is missing {mode} value for atom "
                    f"{atom_id} nucleus {nucleus}."
                )
            if mode == "scaled" and scaling_input == "unscaled_shift":
                if math.isfinite(sc_slope) and abs(sc_slope) >= 1.0e-12:
                    predicted = (calc_value - sc_intercept) / sc_slope
                else:
                    predicted = calc_value
            elif mode == "scaled":
                predicted = sc_intercept + sc_slope * calc_value
            else:
                predicted = calc_value
            error = predicted - assignment.exp_shift_ppm
            errors.append(error)
            predicted_by_atom[atom_id] = predicted
            score.shift_rows.append(
                ShiftRow(
                    atom_id=atom_id,
                    nucleus=nucleus,
                    exp_shift_ppm=assignment.exp_shift_ppm,
                    predicted_shift_ppm=predicted,
                    error_ppm=error,
                    label=assignment.label,
                    unscaled_shift_ppm=unscaled_for_nucleus.get(atom_id),
                    exchange_group=assignment.exchange_group,
                    swapped_with=swap_lookup.get(atom_id),
                    halogen_neighbor=applied_halogens.get(atom_id, ""),
                )
            )

        if mode == "scaled":
            nucleus_log_lik = _compute_log_likelihood(errors, _get_scaled_error_params(params))
            for assignment in nucleus_assignments:
                atom_id = assignment.candidate_atom_id
                unscaled_value = unscaled_for_nucleus.get(atom_id)
                if unscaled_value is None:
                    continue
                hyb_key = _hyb_key_for_nucleus(atom_id, nucleus, candidate)
                unscaled_em = _get_unscaled_error_params(params, hyb_key)
                if unscaled_em is not None:
                    nucleus_log_lik += _compute_log_likelihood(
                        [unscaled_value - assignment.exp_shift_ppm], unscaled_em
                    )
        elif mode == "tms":
            nucleus_log_lik = 0.0
            for assignment in nucleus_assignments:
                atom_id = assignment.candidate_atom_id
                hyb_key = _hyb_key_for_nucleus(atom_id, nucleus, candidate)
                unscaled_em = _get_unscaled_error_params(params, hyb_key)
                if unscaled_em is not None:
                    nucleus_log_lik += _compute_log_likelihood(
                        [predicted_by_atom[atom_id] - assignment.exp_shift_ppm], unscaled_em
                    )
        else:
            nucleus_log_lik = 0.0
            used_raw_model = False
            for assignment in nucleus_assignments:
                atom_id = assignment.candidate_atom_id
                hyb_key = _hyb_key_for_nucleus(atom_id, nucleus, candidate)
                raw_em = _get_raw_error_params(params, hyb_key)
                if raw_em is None:
                    continue
                used_raw_model = True
                nucleus_log_lik += _compute_log_likelihood(
                    [predicted_by_atom[atom_id] - assignment.exp_shift_ppm], raw_em
                )
            if not used_raw_model:
                nucleus_log_lik = -0.5 * sum(error * error for error in errors)

        mae, rmse = _compute_error_stats(errors)
        score.mae_by_nucleus[nucleus] = mae
        score.rmse_by_nucleus[nucleus] = rmse
        score.n_assignments_by_nucleus[nucleus] = len(nucleus_assignments)
        score.probabilities["_log_likelihood_by_nucleus"] = score.probabilities.get(
            "_log_likelihood_by_nucleus", {}
        )
        score.probabilities["_log_likelihood_by_nucleus"][nucleus] = nucleus_log_lik

    log_lik_by_nuc = score.probabilities.get("_log_likelihood_by_nucleus", {})
    if log_lik_by_nuc:
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
    scaled_maps, scaled_nuclei, _warnings, _formula = build_scaled_input_maps(
        candidates, config, parameter_table, theory_level
    )
    regression_modes = scaled_regression_modes(parameter_table, scaled_nuclei, theory_level)
    linear_fits = per_isomer_linear_fits(
        candidates,
        assignments,
        scaled_nuclei,
        value_maps_by_candidate=scaled_maps,
        regression_modes_by_nucleus=regression_modes,
    )
    linear_fit_map: dict[str, dict[str, tuple[float, float]]] = {}
    for lf in linear_fits:
        linear_fit_map.setdefault(lf.candidate_name, {})[lf.nucleus] = (lf.intercept, lf.slope)
    tms_maps = _tms_value_maps(candidates)
    scores = [
        _score_candidate_values(
            candidate=candidate,
            assignments=assignments,
            nuclei=scaled_nuclei,
            parameter_table=parameter_table,
            theory_level=theory_level,
            calc_values=_candidate_value_map(candidate, scaled_maps),
            mode="scaled",
            unscaled_values=_candidate_value_map(candidate, tms_maps),
            linear_fit_map=linear_fit_map,
        )
        for candidate in candidates
    ]
    _normalize_probabilities(scores, scaled_nuclei)
    return sorted(scores, key=lambda item: item.joint_probability, reverse=True)


def score_candidates_all_modes(
    candidates: list[CandidateIsomer],
    assignments: list[ExperimentalAssignment],
    config: DP4Config,
    parameter_table: dict,
    theory_level: str | None = None,
    linear_fits: list[LinearFit] | None = None,
) -> list[ScoringSet]:
    """Run raw diagnostic, TMS-unscaled, and scaled DP4+ scoring passes."""
    # build per-isomer linear fit lookup
    linear_fit_map: dict[str, dict[str, tuple[float, float]]] = {}
    if linear_fits:
        for lf in linear_fits:
            linear_fit_map.setdefault(lf.candidate_name, {})[lf.nucleus] = (lf.intercept, lf.slope)

    scoring_sets: list[ScoringSet] = []
    raw_maps = _raw_value_maps(candidates)
    raw_nuclei = _available_nuclei_for_values(candidates, raw_maps, config.nuclei)
    tms_maps = _tms_value_maps(candidates)
    tms_nuclei = _available_nuclei_for_values(candidates, tms_maps, config.nuclei)

    raw_warnings_sink: list[str] = [
        "Raw mode is a fallback diagnostic and is not the classical uDP4+ chemical-shift model."
    ]
    raw_dedup: set[str] = set()
    raw_scores = [
        _score_candidate_values(
            candidate=c,
            assignments=assignments,
            nuclei=raw_nuclei,
            parameter_table=parameter_table,
            theory_level=theory_level,
            calc_values=_candidate_value_map(c, raw_maps),
            mode="raw",
            warnings_sink=raw_warnings_sink,
            halo_warning_dedup=raw_dedup,
        )
        for c in candidates
    ]
    _normalize_probabilities(raw_scores, raw_nuclei)
    raw_sorted = sorted(raw_scores, key=lambda s: s.joint_probability, reverse=True)
    scoring_sets.append(
        ScoringSet(
            mode="raw",
            label="Raw shielding diagnostic",
            candidate_scores=raw_sorted,
            formula="diagnostic score on sigma_sample; TMS is not used",
            warnings=raw_warnings_sink,
        )
    )

    tms_warnings: list[str] = []
    tms_dedup: set[str] = set()
    if not tms_nuclei:
        tms_warnings.append("No TMS-referenced chemical shifts are available; tms mode was not scored.")
        tms_scores = []
    else:
        missing = [nucleus for nucleus in config.nuclei if nucleus not in tms_nuclei]
        for nucleus in missing:
            tms_warnings.append(f"{nucleus} lacks TMS-referenced shifts and was skipped in tms mode.")
        tms_scores = [
            _score_candidate_values(
                candidate=c,
                assignments=assignments,
                nuclei=tms_nuclei,
                parameter_table=parameter_table,
                theory_level=theory_level,
                calc_values=_candidate_value_map(c, tms_maps),
                mode="tms",
                warnings_sink=tms_warnings,
                halo_warning_dedup=tms_dedup,
            )
            for c in candidates
        ]
        _normalize_probabilities(tms_scores, tms_nuclei)
    tms_sorted = sorted(tms_scores, key=lambda s: s.joint_probability, reverse=True)
    scoring_sets.append(
        ScoringSet(
            mode="tms",
            label="TMS referenced unscaled shift",
            candidate_scores=tms_sorted,
            formula="delta_unscaled = sigma_TMS - sigma_sample",
            warnings=tms_warnings,
        )
    )

    scaled_maps, scaled_nuclei, scaled_warnings, scaled_formula = build_scaled_input_maps(
        candidates, config, parameter_table, theory_level
    )
    regression_modes = scaled_regression_modes(parameter_table, scaled_nuclei, theory_level)
    missing_inverse_fits: list[str] = []
    for candidate in candidates:
        candidate_fits = linear_fit_map.get(candidate.name, {})
        for nucleus in scaled_nuclei:
            if regression_modes.get(nucleus) == "inverse" and nucleus not in candidate_fits:
                missing_inverse_fits.append(f"{candidate.name}/{nucleus}")
    if missing_inverse_fits:
        scaled_warnings.append(
            "DP4+App inverse scaled regression fell back to unscaled shifts for: "
            + ", ".join(missing_inverse_fits)
        )
    if tms_nuclei:
        missing_u = [nucleus for nucleus in scaled_nuclei if nucleus not in tms_nuclei]
        for nucleus in missing_u:
            scaled_warnings.append(
                f"{nucleus} scaled score omits the uDP4+ unscaled term because TMS-referenced shifts are unavailable."
            )
    else:
        scaled_warnings.append("Scaled score omits all uDP4+ unscaled terms because TMS-referenced shifts are unavailable.")

    scaled_dedup: set[str] = set()
    scaled_scores = [
        _score_candidate_values(
            candidate=c,
            assignments=assignments,
            nuclei=scaled_nuclei,
            parameter_table=parameter_table,
            theory_level=theory_level,
            calc_values=_candidate_value_map(c, scaled_maps),
            mode="scaled",
            unscaled_values=_candidate_value_map(c, tms_maps),
            linear_fit_map=linear_fit_map,
            warnings_sink=scaled_warnings,
            halo_warning_dedup=scaled_dedup,
        )
        for c in candidates
    ] if scaled_nuclei else []
    _normalize_probabilities(scaled_scores, scaled_nuclei)
    scaled_sorted = sorted(scaled_scores, key=lambda s: s.joint_probability, reverse=True)
    scoring_sets.append(
        ScoringSet(
            mode="scaled",
            label="Scaled chemical shift",
            candidate_scores=scaled_sorted,
            formula=scaled_formula or "no scaled formula available",
            warnings=scaled_warnings,
        )
    )

    return scoring_sets
