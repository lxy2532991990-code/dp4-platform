"""
报告与可视化模块 —— 生成 publication-ready 的 ECD 图和分析报告。
"""

import os
import numpy as np
from typing import Optional, Dict, List, Tuple
from .config import ECDConfig
from .conformer import ConformerCollection
from .comparison import ACDetermination

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import AutoMinorLocator
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def plot_ecd_comparison(
    calc_wavelengths: np.ndarray,
    calc_spectrum: np.ndarray,
    config: ECDConfig,
    exp_wavelengths: Optional[np.ndarray] = None,
    exp_spectrum: Optional[np.ndarray] = None,
    ac_result: Optional[ACDetermination] = None,
    individual_spectra: Optional[Dict[int, np.ndarray]] = None,
    energy_grid: Optional[np.ndarray] = None,
    output_path: Optional[str] = None,
    show_individuals: bool = False,
) -> Optional[str]:
    """
    生成 publication-ready ECD 对比图。
    """
    if not HAS_MPL:
        return None

    plt.rcParams.update({
        'font.family': 'serif',
        'font.serif': ['Times New Roman', 'DejaVu Serif'],
        'mathtext.fontset': 'stix',
        'font.size': 11,
        'axes.linewidth': 1.0,
    })

    fig, ax = plt.subplots(figsize=(8, 5))

    # ── 归一化计算谱 ──
    max_abs = np.max(np.abs(calc_spectrum))
    if max_abs > 0:
        norm_calc = calc_spectrum / max_abs * config.scale_factor
    else:
        norm_calc = calc_spectrum

    inverted_calc = -norm_calc

    # ── 个别构象谱（淡色背景线）──
    if show_individuals and individual_spectra and energy_grid is not None:
        for cid, spec in individual_spectra.items():
            ind_wl = 1239.84193 / energy_grid
            s_idx = np.argsort(ind_wl)
            m = np.max(np.abs(spec))
            if m > 0:
                norm_ind = spec / max_abs * config.scale_factor * 0.5
            else:
                norm_ind = spec
            ax.plot(ind_wl[s_idx], norm_ind[s_idx],
                    color='gray', alpha=0.15, linewidth=0.6)

    # ── 计算谱 ──
    ax.plot(calc_wavelengths, norm_calc, 'r--', linewidth=1.5,
            label=config.plot_calc_label)
    ax.plot(calc_wavelengths, inverted_calc, 'b--', linewidth=1.5,
            alpha=0.7, label=config.plot_ent_label)

    # ── 实验谱 ──
    if exp_wavelengths is not None and exp_spectrum is not None:
        ax.plot(exp_wavelengths, exp_spectrum, 'k-', linewidth=1.5,
                label=config.plot_exp_label)

    # ── 零线 ──
    ax.axhline(0, color='black', linewidth=0.5, zorder=0)

    # ── 坐标轴 ──
    wl_min, wl_max = config.wavelength_range
    ax.set_xlim(wl_min, wl_max)
    ax.set_xlabel('Wavelength (nm)', fontsize=13, fontweight='bold')
    ax.set_ylabel(r'$\Delta\varepsilon$ (M$^{-1}$cm$^{-1}$)', fontsize=13, fontweight='bold')
    ax.xaxis.set_minor_locator(AutoMinorLocator())
    ax.yaxis.set_minor_locator(AutoMinorLocator())

    # ── 副坐标轴（能量）──
    def nm2ev(x): return 1239.84193 / x
    def ev2nm(x): return 1239.84193 / x
    ax2 = ax.secondary_xaxis('top', functions=(nm2ev, ev2nm))
    ax2.set_xlabel('Energy (eV)', fontsize=11)

    # ── 标题 ──
    title = f'σ = {config.sigma} eV,  shift = {config.shift:+.2f} eV'
    if ac_result:
        conf_str = ac_result.confidence.upper()
        title += f'\nConfidence: {conf_str}  (Δsim = {ac_result.delta_similarity:.3f})'
    ax.set_title(title, fontsize=11, pad=12)

    # ── 图例 ──
    ax.legend(loc='best', frameon=True, edgecolor='black',
              facecolor='white', fontsize=9, framealpha=0.9)

    ax.grid(True, alpha=0.2)
    fig.tight_layout()

    # ── 保存 ──
    if output_path is None:
        output_path = os.path.join(
            config.output_dir,
            f'ecd_comparison_s{config.sigma}_sh{config.shift}.png'
        )
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    fig.savefig(output_path, dpi=config.dpi, bbox_inches='tight')
    plt.close(fig)
    return output_path


def plot_shift_scan(
    ac_result: ACDetermination,
    config: ECDConfig,
    output_path: Optional[str] = None
) -> Optional[str]:
    """绘制 shift 扫描曲线"""
    if not HAS_MPL:
        return None

    fig, ax = plt.subplots(figsize=(7, 4))

    normal = [(r.shift_ev, r.similarity) for r in ac_result.all_results if not r.is_inverted]
    invert = [(r.shift_ev, r.similarity) for r in ac_result.all_results if r.is_inverted]

    if normal:
        s, sim = zip(*sorted(normal))
        ax.plot(s, sim, 'r-o', markersize=3, label='Original', linewidth=1.2)
    if invert:
        s, sim = zip(*sorted(invert))
        ax.plot(s, sim, 'b-s', markersize=3, label='Enantiomer', linewidth=1.2)

    ax.set_xlabel('Energy shift (eV)', fontsize=12)
    ax.set_ylabel(f'Similarity ({ac_result.best_match.metric})', fontsize=12)
    ax.set_title('Shift Scan for AC Determination', fontsize=12)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if output_path is None:
        output_path = os.path.join(config.output_dir, 'shift_scan.png')
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    fig.savefig(output_path, dpi=config.dpi, bbox_inches='tight')
    plt.close(fig)
    return output_path


def save_spectrum_csv(
    calc_wavelengths: np.ndarray,
    calc_spectrum: np.ndarray,
    config: ECDConfig,
    exp_wavelengths: Optional[np.ndarray] = None,
    exp_spectrum: Optional[np.ndarray] = None,
    output_path: Optional[str] = None
) -> str:
    """保存计算谱与实验谱的 CSV 数据"""
    if output_path is None:
        output_path = os.path.join(
            config.output_dir,
            f'ecd_data_s{config.sigma}_sh{config.shift}.csv'
        )
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    max_abs = np.max(np.abs(calc_spectrum))
    if max_abs > 0:
        norm = calc_spectrum / max_abs * config.scale_factor
    else:
        norm = calc_spectrum
    inv = -norm

    has_exp = exp_wavelengths is not None and exp_spectrum is not None

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# ECD-Platform v{__import__('ecd_platform').__version__}\n")
        f.write(f"# sigma={config.sigma}, shift={config.shift}, scale={config.scale_factor}\n")
        f.write(f"# weighting={config.weighting.value}, temperature={config.temperature} K\n")
        f.write(f"# imag_freq_policy={config.imag_freq_policy.value}, "
                f"threshold={config.imag_freq_threshold} cm-1\n")

        if has_exp:
            # 插值实验数据到计算波长网格
            exp_interp = np.interp(calc_wavelengths, exp_wavelengths, exp_spectrum,
                                   left=np.nan, right=np.nan)
            f.write("Wavelength(nm),Calc_Scaled,Calc_Inverted,Exp_Intensity\n")
            for wl, c, ci, e in zip(calc_wavelengths, norm, inv, exp_interp):
                f.write(f"{wl:.4f},{c:.6f},{ci:.6f},{e:.6f}\n")
        else:
            f.write("Wavelength(nm),Calc_Scaled,Calc_Inverted\n")
            for wl, c, ci in zip(calc_wavelengths, norm, inv):
                f.write(f"{wl:.4f},{c:.6f},{ci:.6f}\n")

    return output_path


def generate_full_report(
    config: ECDConfig,
    collection: ConformerCollection,
    ac_result: Optional[ACDetermination] = None,
    output_path: Optional[str] = None
) -> str:
    """生成完整的文本分析报告"""
    if output_path is None:
        output_path = os.path.join(config.output_dir, 'analysis_report.txt')
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    lines = []
    lines.append("=" * 72)
    lines.append("ECD-PLATFORM ANALYSIS REPORT")
    lines.append("=" * 72)
    lines.append("")

    # 配置摘要
    lines.append("── CONFIGURATION ──")
    lines.append(f"Gaussian broadening (σ):  {config.sigma} eV")
    lines.append(f"Energy shift:             {config.shift} eV")
    lines.append(f"Scale factor:             {config.scale_factor}")
    lines.append(f"Weighting strategy:       {config.weighting.value}")
    lines.append(f"Temperature:              {config.temperature} K")
    lines.append(f"Imag freq policy:         {config.imag_freq_policy.value}")
    lines.append(f"Imag freq threshold:      {config.imag_freq_threshold} cm⁻¹")
    lines.append(f"CD gauge:                 {config.cd_gauge.value}")
    lines.append(f"Wavelength range:         {config.wavelength_range[0]}-{config.wavelength_range[1]} nm")
    lines.append(f"Similarity metric:        {config.similarity_metric}")
    lines.append("")

    # 构象报告
    lines.append(collection.report_text())
    lines.append("")

    # Boltzmann 权重表
    usable = collection.usable_records
    if usable:
        lines.append("── BOLTZMANN WEIGHTS ──")
        lines.append(f"{'Conf':>6s}  {'ΔE (kcal/mol)':>14s}  {'Weight':>8s}  {'Status':>20s}")
        lines.append("-" * 56)
        for r in sorted(usable, key=lambda x: x.effective_weight, reverse=True):
            de = f"{r.relative_energy_kcal:.2f}" if r.relative_energy_kcal is not None else "N/A"
            lines.append(
                f"{r.conf_id:>6d}  {de:>14s}  {r.effective_weight:>8.4f}  {r.status.value:>20s}"
            )
        lines.append("")

    # AC 判定
    if ac_result:
        lines.append("── ABSOLUTE CONFIGURATION DETERMINATION ──")
        lines.append(ac_result.recommendation)
        lines.append("")

    lines.append("=" * 72)

    text = "\n".join(lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)
    return output_path
