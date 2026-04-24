"""Pipeline entry point for the standalone DP4+ workflow."""

from __future__ import annotations

from collections.abc import Callable
from collections import Counter

from .config import DP4Config, DataKind
from .dp4 import (
    load_parameter_table,
    score_candidates,
    score_candidates_all_modes,
    detect_data_kind,
    apply_tms_referencing,
    resolve_level_match,
    per_isomer_linear_fits,
    build_scaled_input_maps,
    scaled_regression_modes,
)
from .energy import boltzmann_average_shieldings, compute_boltzmann_weights
from .experimental import load_experimental_assignments
from .hybridization import CarbonHyb, build_atom_hybridization_map
from .models import CandidateIsomer, DP4Result
from .parser import discover_candidate_directories, load_candidate_from_directory
from .report import write_reports
from .solvent import normalize_reference_solvent
from .tms_parser import parse_tms_file


def select_reference_shielding(
    level_data: dict,
    requested_solvent: str | None,
) -> tuple[dict, str | None, list[str]]:
    """Select equivalent TMS shielding for a solvent, falling back to the level default."""
    warnings: list[str] = []
    default_ref = level_data.get("reference_shielding") or {}
    by_solvent = level_data.get("reference_shielding_by_solvent") or {}
    solvent = normalize_reference_solvent(requested_solvent)
    if solvent and solvent in by_solvent:
        return by_solvent[solvent], solvent, warnings

    if solvent:
        available = ", ".join(sorted(by_solvent)) or "none"
        warnings.append(
            f"Reference solvent '{solvent}' is not available for this parameter level; "
            f"falling back to the default reference shielding. Available solvents: {available}."
        )

    default_solvent = None
    for candidate_solvent, ref in by_solvent.items():
        if dict(ref) == dict(default_ref):
            default_solvent = candidate_solvent
            break
    return default_ref, default_solvent, warnings


class DP4Pipeline:
    def __init__(
        self,
        config: DP4Config,
        logger: Callable[[str], None] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ):
        self.config = config
        self.logger = logger
        self.progress_callback = progress_callback
        self.candidates = []
        self.assignments = []
        self.parameter_table = {}
        self.parameter_match = {}
        self.theory_level: str | None = None
        self.reference_solvent: str | None = None
        self.reference_solvent_source: str = ""
        self._log: list[str] = []

    def log(self, message: str) -> None:
        self._log.append(message)
        if self.logger is not None:
            self.logger(message)
        print(message)

    def _emit_progress(self, done: int, total: int) -> None:
        if self.progress_callback is not None:
            self.progress_callback(done, total)

    @property
    def logs(self) -> list[str]:
        return list(self._log)

    def _candidate_sources(self) -> list[tuple[str, str]]:
        if self.config.candidate_paths:
            return sorted(self.config.candidate_paths.items(), key=lambda item: item[0])
        return discover_candidate_directories(self.config.candidates_root)

    def _failed_status_summary(self, candidate: CandidateIsomer) -> str:
        counts = Counter(record.status.value for record in candidate.collection.failed_records)
        if not counts:
            return "none"
        return ", ".join(f"{status}={counts[status]}" for status in sorted(counts))

    def _collect_theory_level(self) -> str | None:
        for candidate in self.candidates:
            for record in candidate.collection.usable_records:
                if record.theory_level:
                    return record.theory_level
        return None

    def _collect_reference_solvent(self) -> tuple[str | None, str]:
        configured = normalize_reference_solvent(self.config.reference_solvent)
        if configured:
            return configured, "manual"

        solvents = [
            record.reference_solvent
            for candidate in self.candidates
            for record in candidate.collection.usable_records
            if record.reference_solvent
        ]
        if not solvents:
            return None, "default"

        counts = Counter(solvents)
        solvent, count = counts.most_common(1)[0]
        if len(counts) > 1:
            details = ", ".join(f"{name}={counts[name]}" for name in sorted(counts))
            self.log(f"WARNING: Multiple solvents detected in calculation files ({details}); using {solvent}.")
        return solvent, "auto"

    def run(self) -> DP4Result:
        self.log("Loading experimental assignments...")
        self.assignments = load_experimental_assignments(self.config.exp_nmr_file, self.config.nuclei)

        self.log("Loading parameter table...")
        self.parameter_table = load_parameter_table(self.config.parameter_table)

        self.log("Discovering candidate isomers...")
        candidate_dirs = self._candidate_sources()
        total = len(candidate_dirs) + 2
        self._emit_progress(0, total)

        self.candidates = []
        for index, (name, directory) in enumerate(candidate_dirs):
            self.log(f"Parsing candidate '{name}'...")
            candidate = load_candidate_from_directory(name=name, directory=directory, config=self.config)
            self.log(
                f"  Found {len(candidate.collection.all_records)} conformers "
                f"({len(candidate.collection.usable_records)} usable, "
                f"{len(candidate.unpaired_opt) + len(candidate.unpaired_nmr)} unpaired files)"
            )
            if candidate.collection.failed_records:
                self.log(f"  Failed status summary: {self._failed_status_summary(candidate)}")
            if not candidate.collection.usable_records:
                raise ValueError(
                    f"Candidate '{name}' has no usable conformers "
                    f"({self._failed_status_summary(candidate)})"
                )

            for record in candidate.collection.usable_records:
                if record.theory_level:
                    self.log(f"  Theory level: {record.theory_level}")
                    if record.reference_solvent:
                        self.log(f"  Detected solvent: {record.reference_solvent}")
                    break

            compute_boltzmann_weights(candidate, self.config)
            boltzmann_average_shieldings(candidate, self.config.nuclei)

            for record in candidate.collection.usable_records:
                if record.atom_elements and record.coordinates:
                    hyb_map = build_atom_hybridization_map(record.atom_elements, record.coordinates)
                    candidate.atom_hybridizations = {
                        atom_id: hyb.value for atom_id, hyb in hyb_map.items()
                    }
                    sp2 = sum(
                        1 for aid, h in hyb_map.items()
                        if h == CarbonHyb.SP2 and record.atom_elements.get(aid, "").upper() == "C"
                    )
                    sp3 = sum(
                        1 for aid, h in hyb_map.items()
                        if h == CarbonHyb.SP3 and record.atom_elements.get(aid, "").upper() == "C"
                    )
                    self.log(f"  Hybridization: {sp2} sp2, {sp3} sp3 carbons detected")
                    break

            self.candidates.append(candidate)
            self._emit_progress(index + 1, total)

        # --- data kind detection ---
        if self.config.data_kind == DataKind.AUTO:
            detected = detect_data_kind(self.candidates, self.config.nuclei)
            self.config.data_kind = detected
            self.log(f"Auto-detected data kind: {detected.value}")

        # --- theory level matching ---
        self.theory_level = self._collect_theory_level()
        self.reference_solvent, self.reference_solvent_source = self._collect_reference_solvent()
        if self.reference_solvent:
            self.log(f"Reference solvent: {self.reference_solvent} ({self.reference_solvent_source})")
        else:
            self.log("Reference solvent: parameter-table default")
        self.parameter_match = resolve_level_match(self.parameter_table, self.theory_level)
        if self.parameter_match.get("matched"):
            level_name = self.parameter_match.get("level_name")
            matched_by = self.parameter_match.get("matched_by")
            self.log(f"Theory level '{self.theory_level}' matched parameters: {level_name} ({matched_by})")
        else:
            for warning in self.parameter_match.get("warnings", []):
                self.log(f"WARNING: {warning}")

        # --- TMS referencing ---
        tms_1h = self.config.tms_shielding_1h
        tms_13c = self.config.tms_shielding_13c

        if self.config.tms_shielding_file:
            self.log(f"Parsing TMS shielding from: {self.config.tms_shielding_file}")
            tms_data = parse_tms_file(self.config.tms_shielding_file)
            if "1H" in tms_data:
                tms_1h = tms_data["1H"]
                self.log(f"  TMS 1H shielding: {tms_1h:.4f}")
            if "13C" in tms_data:
                tms_13c = tms_data["13C"]
                self.log(f"  TMS 13C shielding: {tms_13c:.4f}")

        shift_input = self.config.data_kind in (DataKind.TMS_REFERENCED, DataKind.CHEMICAL_SHIFT)
        level_ref, selected_ref_solvent, ref_warnings = select_reference_shielding(
            self.parameter_match.get("level_data") or {},
            self.reference_solvent,
        )
        requested_reference_solvent = self.reference_solvent
        for warning in ref_warnings:
            self.log(f"WARNING: {warning}")
            self.parameter_match.setdefault("warnings", []).append(warning)
        if selected_ref_solvent:
            self.reference_solvent = selected_ref_solvent
            if requested_reference_solvent and selected_ref_solvent != requested_reference_solvent:
                self.reference_solvent_source = "fallback"
        if not shift_input and level_ref:
            if tms_1h is None and "1H" in level_ref:
                tms_1h = float(level_ref["1H"])
                self.log(
                    f"Using parameter-table equivalent reference for 1H: {tms_1h:.4f} "
                    f"({self.reference_solvent or 'default'}, {self.parameter_match.get('level_name')})"
                )
            if tms_13c is None and "13C" in level_ref:
                tms_13c = float(level_ref["13C"])
                self.log(
                    f"Using parameter-table equivalent reference for 13C: {tms_13c:.4f} "
                    f"({self.reference_solvent or 'default'}, {self.parameter_match.get('level_name')})"
                )

        if shift_input:
            self.log(
                "Input NMR values are treated as chemical shifts; "
                "TMS-referenced modes will use the parsed values directly."
            )
            for candidate in self.candidates:
                candidate.tms_referenced_shifts = {
                    nuc: dict(vals) for nuc, vals in candidate.averaged_shieldings.items()
                }
        elif tms_1h is not None or tms_13c is not None:
            self.log(
                "Applying TMS referencing"
                + (f" (1H: {tms_1h:.4f})" if tms_1h is not None else "")
                + (f" (13C: {tms_13c:.4f})" if tms_13c is not None else "")
            )
            for candidate in self.candidates:
                candidate.tms_referenced_shifts = apply_tms_referencing(candidate, tms_1h, tms_13c)
        else:
            self.log(
                "No TMS reference available. Raw diagnostic and shielding-domain scaled modes can run; "
                "TMS/unscaled terms will be skipped."
            )

        # --- per-isomer linear fitting ---
        self.log("Computing per-isomer linear regression fits...")
        scaled_input_maps, scaled_fit_nuclei, scaled_input_warnings, scaled_formula = build_scaled_input_maps(
            self.candidates,
            self.config,
            self.parameter_table,
            self.theory_level,
        )
        for warning in scaled_input_warnings:
            self.log(f"  WARNING: {warning}")
        if scaled_formula:
            self.log(f"  Scaled formula: {scaled_formula}")
        linear_fits = per_isomer_linear_fits(
            self.candidates,
            self.assignments,
            scaled_fit_nuclei,
            value_maps_by_candidate=scaled_input_maps,
            regression_modes_by_nucleus=scaled_regression_modes(
                self.parameter_table,
                scaled_fit_nuclei,
                self.theory_level,
            ),
        )
        for lf in linear_fits:
            self.log(
                f"  {lf.candidate_name} {lf.nucleus}: "
                f"intercept={lf.intercept:.4f}, slope={lf.slope:.4f}, R²={lf.r_squared:.4f}"
            )

        # --- three-mode scoring ---
        self.log("Scoring candidates (3 modes: raw / TMS / scaled)...")
        scoring_sets = score_candidates_all_modes(
            candidates=self.candidates,
            assignments=self.assignments,
            config=self.config,
            parameter_table=self.parameter_table,
            theory_level=self.theory_level,
            linear_fits=linear_fits,
        )
        # legacy compatibility: prefer scaled, then TMS/unscaled, then raw diagnostic fallback
        primary_set = next((s for s in scoring_sets if s.mode == "scaled" and s.candidate_scores), None)
        if primary_set is None:
            primary_set = next((s for s in scoring_sets if s.mode == "tms" and s.candidate_scores), None)
        if primary_set is None:
            primary_set = next((s for s in scoring_sets if s.mode == "raw" and s.candidate_scores), scoring_sets[-1])
        candidate_scores = primary_set.candidate_scores
        self._emit_progress(len(candidate_dirs) + 1, total)

        result = DP4Result(
            candidate_scores=candidate_scores,
            nuclei=self.config.nuclei,
            total_assignments=len(self.assignments),
            output_dir=self.config.output_dir,
            scoring_sets=scoring_sets,
            linear_fits=linear_fits,
            tms_shielding_1h=tms_1h,
            tms_shielding_13c=tms_13c,
            reference_solvent=self.reference_solvent,
            reference_solvent_source=self.reference_solvent_source,
            parameter_match=self.parameter_match,
        )
        self.log("Writing reports...")
        report_result = write_reports(self.config, self.candidates, result)
        self._emit_progress(total, total)
        return report_result
