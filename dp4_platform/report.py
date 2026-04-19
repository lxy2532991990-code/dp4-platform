"""Report generation for the standalone DP4 workflow."""

from __future__ import annotations

import csv
import os

from .config import DP4Config
from .models import CandidateIsomer, DP4Result


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def write_reports(
    config: DP4Config,
    candidates: list[CandidateIsomer],
    result: DP4Result,
) -> DP4Result:
    os.makedirs(config.output_dir, exist_ok=True)
    generated: list[str] = []

    summary_path = os.path.join(config.output_dir, "dp4_summary.csv")
    with open(summary_path, "w", encoding="utf-8", newline="") as fh:
        fieldnames = ["candidate", "joint_probability", "joint_log_likelihood"]
        for nucleus in result.nuclei:
            fieldnames.extend(
                [
                    f"{nucleus}_probability",
                    f"{nucleus}_mae",
                    f"{nucleus}_rmse",
                    f"{nucleus}_n",
                ]
            )
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for score in result.ranking:
            row = {
                "candidate": score.candidate_name,
                "joint_probability": f"{score.joint_probability:.8f}",
                "joint_log_likelihood": f"{score.joint_log_likelihood:.8f}",
            }
            for nucleus in result.nuclei:
                row[f"{nucleus}_probability"] = f"{score.probabilities.get(nucleus, 0.0):.8f}"
                row[f"{nucleus}_mae"] = f"{score.mae_by_nucleus.get(nucleus, float('nan')):.6f}"
                row[f"{nucleus}_rmse"] = f"{score.rmse_by_nucleus.get(nucleus, float('nan')):.6f}"
                row[f"{nucleus}_n"] = score.n_assignments_by_nucleus.get(nucleus, 0)
            writer.writerow(row)
    generated.append(summary_path)

    for score in result.ranking:
        shift_path = os.path.join(
            config.output_dir,
            f"candidate_{_safe_name(score.candidate_name)}_shifts.csv",
        )
        with open(shift_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["candidate_atom_id", "nucleus", "label", "exp_shift_ppm", "predicted_shift_ppm", "error_ppm"])
            for row in sorted(score.shift_rows, key=lambda item: (item.nucleus, item.atom_id)):
                writer.writerow(
                    [
                        row.atom_id,
                        row.nucleus,
                        row.label,
                        f"{row.exp_shift_ppm:.6f}",
                        f"{row.predicted_shift_ppm:.6f}",
                        f"{row.error_ppm:.6f}",
                    ]
                )
        generated.append(shift_path)

    report_path = os.path.join(config.output_dir, "analysis_report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("DP4 PLATFORM ANALYSIS REPORT\n")
        fh.write("=" * 72 + "\n\n")
        fh.write(f"Candidates root: {config.candidates_root}\n")
        if config.candidate_paths:
            fh.write("Candidate paths:\n")
            for candidate_name, candidate_path in sorted(config.candidate_paths.items()):
                fh.write(f"  {candidate_name}: {candidate_path}\n")
        fh.write(f"Experimental CSV: {config.exp_nmr_file}\n")
        fh.write(f"Output dir: {config.output_dir}\n")
        fh.write(f"Program mode: {config.program_mode}\n")
        fh.write(f"Nuclei: {', '.join(config.nuclei)}\n")
        fh.write(f"Weighting: {config.weighting.value}\n")
        fh.write(f"Temperature: {config.temperature} K\n")
        fh.write(f"Imaginary frequency policy: {config.imag_freq_policy.value}\n")
        fh.write(f"Imaginary frequency threshold: {config.imag_freq_threshold} cm-1\n")
        fh.write(f"Auto pair strategy: {config.auto_pair_strategy}\n")
        fh.write("\nRanking\n")
        fh.write("-" * 72 + "\n")
        for index, score in enumerate(result.ranking, start=1):
            fh.write(f"{index}. {score.candidate_name}\n")
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

        fh.write("Candidate summary\n")
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

    config_path = None
    if config.save_config:
        config_path = os.path.join(config.output_dir, "config.json")
        config.to_json(config_path)
        generated.append(config_path)

    result.summary_file = summary_path
    result.report_file = report_path
    result.config_file = config_path
    result.generated_files = generated
    return result
