"""
ECD 工作流主编排器 —— 将所有模块串联为完整的分析流程。

使用方式：
    from ecd_platform import ECDPipeline, ECDConfig
    
    config = ECDConfig(
        opt_dir='opt_conf',
        ecd_dir='ecd_opt_60_roots',
        exp_file='experiment.csv',
        sigma=0.3,
        shift=0.15,
    )
    pipeline = ECDPipeline(config)
    pipeline.run()
"""

import os
import time
import numpy as np
from typing import Optional
from .config import ECDConfig, WeightingStrategy
from .conformer import ConformerCollection
from .matcher import ConformerMatcher
from .parser_dispatch import (
    parse_opt_file,
    parse_ecd_file,
    parse_single_file,
    same_output_file,
)
from .energy import compute_boltzmann_weights, load_manual_weights
from .spectrum import (
    generate_wavelength_grid,
    compute_weighted_spectrum,
    normalize_spectrum,
)
from .experimental import read_experimental_data, smooth_spectrum
from .comparison import shift_scan, ACDetermination
from .report import (
    plot_ecd_comparison,
    plot_shift_scan,
    save_spectrum_csv,
    generate_full_report,
)


class ECDPipeline:
    """
    ECD 工作流管道。
    
    工作流程：
      1. 构象匹配（matcher）
      2. 文件解析（parser） → per-conformer fault isolation
      3. 能量提取 & Boltzmann 加权（energy）
      4. Gaussian 展宽 & 加权叠加（spectrum）
      5. 实验谱读取 & 平滑（experimental）
      6. Shift 扫描 & 相似度评分（comparison）
      7. 报告 & 可视化输出（report）
    """

    def __init__(self, config: ECDConfig):
        self.config = config
        self.collection: Optional[ConformerCollection] = None
        self.calc_wavelengths: Optional[np.ndarray] = None
        self.calc_spectrum: Optional[np.ndarray] = None
        self.energy_grid: Optional[np.ndarray] = None
        self.individual_spectra = {}
        self.exp_wavelengths: Optional[np.ndarray] = None
        self.exp_spectrum: Optional[np.ndarray] = None
        self.ac_result: Optional[ACDetermination] = None
        self._log: list = []

    def log(self, msg: str):
        self._log.append(msg)
        print(msg)

    # ── 完整流程 ──

    def run(self):
        """执行完整 ECD 分析流程"""
        t0 = time.time()
        self.log("=" * 60)
        self.log("ECD-Platform: Fault-Tolerant ECD Workflow")
        self.log("=" * 60)

        os.makedirs(self.config.output_dir, exist_ok=True)

        self.step1_match()
        self.step2_parse()
        self.step3_weight()
        self.step4_spectrum()
        self.step5_experimental()
        self.step6_compare()
        self.step7_report()

        elapsed = time.time() - t0
        self.log(f"\nTotal elapsed: {elapsed:.1f} s")
        self.log("=" * 60)

    # ── Step 1: 构象匹配 ──

    def step1_match(self):
        self.log("\n── Step 1: Conformer Matching ──")
        matcher = ConformerMatcher(self.config)
        self.collection = matcher.match()

        n_total = len(self.collection.all_records)
        self.log(f"Found {n_total} conformer(s)")

        if matcher.conflicts:
            self.log(f"  ⚠ {len(matcher.conflicts)} conflict(s) detected")
            for c in matcher.conflicts:
                self.log(f"    {c}")

        if matcher.orphans:
            self.log(f"  ⚠ {len(matcher.orphans)} orphan file(s)")

        # 导出映射表
        mapping_path = os.path.join(self.config.output_dir, 'conformer_mapping.csv')
        matcher.export_mapping(self.collection, mapping_path)
        self.log(f"  Mapping exported: {mapping_path}")

    # ── Step 2: 文件解析 ──

    def step2_parse(self):
        prog_label = self.config.program.value
        self.log(f"\n── Step 2: Parsing QM Outputs [{prog_label}] (per-conformer) ──")

        for rec in self.collection.all_records:
            # 两个路径指向同一个文件：只解析一次，避免重复报错
            if same_output_file(rec.opt_file, rec.ecd_file):
                if os.path.exists(rec.opt_file):
                    parse_single_file(rec.opt_file, rec, self.config)
                else:
                    rec.add_warning(f"File not found: {rec.opt_file}")
                continue

            # 分别解析 OPT 与 ECD
            if rec.opt_file and os.path.exists(rec.opt_file):
                parse_opt_file(rec.opt_file, rec, self.config)
            elif rec.opt_file:
                rec.add_warning(f"OPT file not found: {rec.opt_file}")

            if rec.ecd_file and os.path.exists(rec.ecd_file):
                parse_ecd_file(rec.ecd_file, rec, self.config)
            elif rec.ecd_file:
                rec.add_warning(f"ECD file not found: {rec.ecd_file}")

        n_ok = len(self.collection.usable_records)
        n_fail = len(self.collection.failed_records)
        self.log(f"  Usable: {n_ok}  |  Failed/Excluded: {n_fail}")

        for rec in self.collection.failed_records:
            self.log(f"    ✗ Conf-{rec.conf_id}: {rec.status.value}")
            for e in rec.errors:
                self.log(f"      → {e}")

    # ── Step 3: 权重计算 ──

    def step3_weight(self):
        self.log("\n── Step 3: Boltzmann Weighting ──")
        self.log(f"  Strategy: {self.config.weighting.value}")
        self.log(f"  Temperature: {self.config.temperature} K")

        # 加载手动权重（如果有）
        wf = self.config.weights_file
        if wf is None:
            # 自动查找
            candidates = [
                os.path.join(self.config.opt_dir, 'ecd_weights.txt'),
                os.path.join(self.config.opt_dir, 'weights.csv'),
                'ecd_weights.txt',
                'weights.csv',
            ]
            for c in candidates:
                if os.path.exists(c):
                    wf = c
                    break

        if wf and os.path.exists(wf):
            self.log(f"  Loading manual weights from: {wf}")
            load_manual_weights(self.collection, wf)
            self.config.weighting = WeightingStrategy.MANUAL
        else:
            compute_boltzmann_weights(self.collection, self.config)

        self.collection.normalize_weights()

        # 输出权重表
        usable = self.collection.usable_records
        self.log(f"  {len(usable)} conformer(s) contributing:")
        for r in sorted(usable, key=lambda x: x.effective_weight, reverse=True):
            de = f"{r.relative_energy_kcal:.2f}" if r.relative_energy_kcal is not None else "N/A"
            self.log(f"    Conf-{r.conf_id:>3d}  w={r.effective_weight:.4f}  ΔE={de} kcal/mol")

    # ── Step 4: 光谱计算 ──

    def step4_spectrum(self):
        self.log("\n── Step 4: Spectrum Generation ──")
        self.log(f"  σ = {self.config.sigma} eV,  shift = {self.config.shift} eV")

        wl_min, wl_max = self.config.wavelength_range
        self.calc_wavelengths, self.energy_grid = generate_wavelength_grid(
            wl_min, wl_max, self.config.n_points
        )

        self.calc_spectrum, self.individual_spectra = compute_weighted_spectrum(
            self.collection,
            self.calc_wavelengths,
            self.energy_grid,
            sigma=self.config.sigma,
            shift=self.config.shift,
        )

        max_val = np.max(np.abs(self.calc_spectrum))
        self.log(f"  Max |ΔΔε| = {max_val:.4f}")
        self.log(f"  {len(self.individual_spectra)} individual spectra computed")

    # ── Step 5: 实验谱 ──

    def step5_experimental(self):
        self.log("\n── Step 5: Experimental Spectrum ──")

        if not self.config.exp_file:
            self.log("  No experimental file specified, skipping.")
            return

        self.exp_wavelengths, self.exp_spectrum = read_experimental_data(
            self.config.exp_file
        )

        if self.exp_wavelengths is None:
            self.log(f"  ⚠ Could not read: {self.config.exp_file}")
            return

        self.log(f"  Read {len(self.exp_wavelengths)} data points")
        self.log(f"  Range: {self.exp_wavelengths.min():.1f} – {self.exp_wavelengths.max():.1f} nm")

        # 平滑
        if self.config.smooth_method != "none":
            self.exp_spectrum = smooth_spectrum(
                self.exp_spectrum,
                method=self.config.smooth_method,
                fft_cutoff=self.config.smooth_factor,
                sg_window=self.config.savgol_window,
                sg_order=self.config.savgol_order,
            )
            self.log(f"  Smoothed with {self.config.smooth_method} "
                     f"(factor={self.config.smooth_factor})")

    # ── Step 6: 比较与 AC 判定 ──

    def step6_compare(self):
        self.log("\n── Step 6: Comparison & AC Determination ──")

        if self.exp_wavelengths is None or self.exp_spectrum is None:
            self.log("  No experimental data, skipping comparison.")
            return

        self.ac_result = shift_scan(
            calc_spectrum=self.calc_spectrum,
            energy_grid=self.energy_grid,
            exp_spectrum=self.exp_spectrum,
            exp_wavelengths=self.exp_wavelengths,
            shift_range=self.config.shift_scan_range,
            shift_step=self.config.shift_scan_step,
            metric=self.config.similarity_metric,
            auto_invert=self.config.auto_invert,
        )

        self.log(f"  Metric: {self.config.similarity_metric}")
        self.log(f"  Best similarity: {self.ac_result.best_match.similarity:.4f} "
                 f"(shift={self.ac_result.best_match.shift_ev:+.3f} eV, "
                 f"{'inverted' if self.ac_result.best_match.is_inverted else 'normal'})")
        self.log(f"  Ent. similarity: {self.ac_result.ent_match.similarity:.4f}")
        self.log(f"  Confidence: {self.ac_result.confidence}")

    # ── Step 7: 报告输出 ──

    def step7_report(self):
        self.log("\n── Step 7: Report Generation ──")

        # 文本报告
        if self.config.save_report:
            rpath = generate_full_report(
                self.config, self.collection, self.ac_result
            )
            self.log(f"  Report: {rpath}")

        # CSV
        if self.config.save_csv:
            cpath = save_spectrum_csv(
                self.calc_wavelengths, self.calc_spectrum, self.config,
                self.exp_wavelengths, self.exp_spectrum
            )
            self.log(f"  CSV: {cpath}")

        # 配置存档
        conf_path = os.path.join(self.config.output_dir, 'config.json')
        self.config.to_json(conf_path)
        self.log(f"  Config: {conf_path}")

        # 图形
        if self.config.save_png:
            # 主对比图
            fig_path = plot_ecd_comparison(
                self.calc_wavelengths,
                self.calc_spectrum,
                self.config,
                self.exp_wavelengths,
                self.exp_spectrum,
                self.ac_result,
                self.individual_spectra,
                self.energy_grid,
            )
            if fig_path:
                self.log(f"  Figure: {fig_path}")

            # Shift 扫描图
            if self.ac_result:
                scan_path = plot_shift_scan(self.ac_result, self.config)
                if scan_path:
                    self.log(f"  Shift scan: {scan_path}")

        # 构象状态报告
        status_path = os.path.join(self.config.output_dir, 'conformer_status.txt')
        with open(status_path, 'w', encoding='utf-8') as f:
            f.write(self.collection.report_text())
        self.log(f"  Conformer status: {status_path}")

        # 日志
        log_path = os.path.join(self.config.output_dir, 'pipeline.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(self._log))
        self.log(f"  Log: {log_path}")
