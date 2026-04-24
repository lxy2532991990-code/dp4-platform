"""Report generation for the standalone DP4+ workflow.

Outputs three scoring modes: raw shielding, TMS referenced, linear scaled.
"""

from __future__ import annotations

import csv
import os

from .config import DP4Config
from .models import CandidateIsomer, DP4Result, ScoringSet


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def _write_summary_csv(
    path: str,
    scoring_set: ScoringSet,
    nuclei: tuple[str, ...],
) -> None:
    """Write one summary CSV for a single scoring mode."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fieldnames = ["candidate", "joint_probability", "joint_log_likelihood"]
        for nucleus in nuclei:
            fieldnames.extend([
                f"{nucleus}_probability",
                f"{nucleus}_mae",
                f"{nucleus}_rmse",
                f"{nucleus}_n",
            ])
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for score in scoring_set.ranking:
            row = {
                "candidate": score.candidate_name,
                "joint_probability": f"{score.joint_probability:.8f}",
                "joint_log_likelihood": f"{score.joint_log_likelihood:.8f}",
            }
            for nucleus in nuclei:
                row[f"{nucleus}_probability"] = f"{score.probabilities.get(nucleus, 0.0):.8f}"
                row[f"{nucleus}_mae"] = f"{score.mae_by_nucleus.get(nucleus, float('nan')):.6f}"
                row[f"{nucleus}_rmse"] = f"{score.rmse_by_nucleus.get(nucleus, float('nan')):.6f}"
                row[f"{nucleus}_n"] = score.n_assignments_by_nucleus.get(nucleus, 0)
            writer.writerow(row)


def write_reports(
    config: DP4Config,
    candidates: list[CandidateIsomer],
    result: DP4Result,
) -> DP4Result:
    os.makedirs(config.output_dir, exist_ok=True)
    generated: list[str] = []

    # ---- per-mode summary CSVs ----
    for ss in result.scoring_sets:
        summary_path = os.path.join(config.output_dir, f"dp4_summary_{ss.mode}.csv")
        _write_summary_csv(summary_path, ss, result.nuclei)
        generated.append(summary_path)

    # ---- legacy default: use "scaled" as dp4_summary.csv ----
    scaled_set = next((s for s in result.scoring_sets if s.mode == "scaled"), None)
    if scaled_set:
        legacy_path = os.path.join(config.output_dir, "dp4_summary.csv")
        _write_summary_csv(legacy_path, scaled_set, result.nuclei)
        generated.append(legacy_path)

    # ---- linear fit table ----
    if result.linear_fits:
        fit_path = os.path.join(config.output_dir, "linear_fits.csv")
        with open(fit_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["candidate", "nucleus", "intercept", "slope", "r2"])
            for lf in result.linear_fits:
                writer.writerow([
                    lf.candidate_name,
                    lf.nucleus,
                    f"{lf.intercept:.6f}",
                    f"{lf.slope:.6f}",
                    f"{lf.r_squared:.6f}",
                ])
        generated.append(fit_path)

    # ---- per-candidate shift CSVs (from "scaled" mode) ----
    if scaled_set:
        for score in scaled_set.ranking:
            shift_path = os.path.join(
                config.output_dir,
                f"candidate_{_safe_name(score.candidate_name)}_shifts.csv",
            )
            with open(shift_path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow([
                    "candidate_atom_id", "nucleus", "label",
                    "exp_shift_ppm", "predicted_shift_ppm", "error_ppm",
                ])
                for row in sorted(score.shift_rows, key=lambda item: (item.nucleus, item.atom_id)):
                    writer.writerow([
                        row.atom_id,
                        row.nucleus,
                        row.label,
                        f"{row.exp_shift_ppm:.6f}",
                        f"{row.predicted_shift_ppm:.6f}",
                        f"{row.error_ppm:.6f}",
                    ])
            generated.append(shift_path)

    # ---- analysis report ----
    report_path = os.path.join(config.output_dir, "analysis_report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("DP4+ PLATFORM ANALYSIS REPORT\n")
        fh.write("=" * 72 + "\n\n")

        # Config summary
        fh.write(f"Candidates root: {config.candidates_root}\n")
        if config.candidate_paths:
            for name, path in sorted(config.candidate_paths.items()):
                fh.write(f"  {name}: {path}\n")
        fh.write(f"Experimental CSV: {config.exp_nmr_file}\n")
        fh.write(f"Output dir: {config.output_dir}\n")
        fh.write(f"Program mode: {config.program_mode}\n")
        fh.write(f"Nuclei: {', '.join(config.nuclei)}\n")
        fh.write(f"Weighting: {config.weighting.value}\n")
        fh.write(f"Temperature: {config.temperature} K\n")
        fh.write(f"Data kind: {config.data_kind.value}\n")
        if result.tms_shielding_1h is not None:
            fh.write(f"TMS 1H shielding: {result.tms_shielding_1h:.4f}\n")
        if result.tms_shielding_13c is not None:
            fh.write(f"TMS 13C shielding: {result.tms_shielding_13c:.4f}\n")

        # Linear fits
        if result.linear_fits:
            fh.write("\nPer-Isomer Linear Regression Fits\n")
            fh.write("-" * 72 + "\n")
            fh.write(f"{'Candidate':20s} {'Nucleus':6s} {'Intercept':>10s} {'Slope':>10s} {'R2':>8s}\n")
            for lf in result.linear_fits:
                fh.write(
                    f"{lf.candidate_name:20s} {lf.nucleus:6s} "
                    f"{lf.intercept:10.4f} {lf.slope:10.4f} {lf.r_squared:8.4f}\n"
                )

        # Three-mode ranking
        for ss in result.scoring_sets:
            fh.write(f"\n{'─' * 72}\n")
            fh.write(f"Mode: {ss.label} ({ss.mode})\n")
            fh.write(f"{'─' * 72}\n")
            for idx, score in enumerate(ss.ranking, start=1):
                fh.write(f"{idx}. {score.candidate_name}\n")
                fh.write(f"   Joint probability: {score.joint_probability:.6f}\n")
                fh.write(f"   Joint log likelihood: {score.joint_log_likelihood:.6f}\n")
                for nucleus in result.nuclei:
                    fh.write(
                        f"   {nucleus}: P={score.probabilities.get(nucleus, 0.0):.6f}  "
                        f"MAE={score.mae_by_nucleus.get(nucleus, float('nan')):.4f}  "
                        f"RMSE={score.rmse_by_nucleus.get(nucleus, float('nan')):.4f}  "
                        f"N={score.n_assignments_by_nucleus.get(nucleus, 0)}\n"
                    )
                fh.write("\n")

        # Candidate conformer details
        fh.write("\nCandidate Conformer Summary\n")
        fh.write("-" * 72 + "\n")
        for candidate in candidates:
            fh.write(f"{candidate.name}: {len(candidate.collection.all_records)} conformers\n")
            fh.write(f"  Usable conformers: {len(candidate.collection.usable_records)}\n")
            fh.write(f"  Unpaired OPT files: {len(candidate.unpaired_opt)}\n")
            fh.write(f"  Unpaired NMR files: {len(candidate.unpaired_nmr)}\n")
            for record in candidate.collection.all_records:
                file_text = record.combined_file or f"opt={record.opt_file} nmr={record.nmr_file}"
                fh.write(
                    f"  Conf-{record.conf_id}: status={record.status.value} "
                    f"weight={record.effective_weight:.6f} "
                    f"file={file_text}\n"
                )
                for warning in record.warnings:
                    fh.write(f"    WARNING: {warning}\n")
                for error in record.errors:
                    fh.write(f"    ERROR: {error}\n")
            fh.write("\n")
    generated.append(report_path)

    # config
    config_path = None
    if config.save_config:
        config_path = os.path.join(config.output_dir, "config.json")
        config.to_json(config_path)
        generated.append(config_path)

    # set summary paths on result
    for ss in result.scoring_sets:
        if ss.mode == "scaled":
            result.summary_file = os.path.join(config.output_dir, "dp4_summary.csv")
            break
    result.report_file = report_path
    result.config_file = config_path
    result.generated_files = generated
    return result
