"""
命令行接口 —— 支持命令行参数运行完整 ECD 分析流程。

用法:
    python -m ecd_platform --opt-dir opt_conf --ecd-dir ecd_opt --exp experiment.csv
    python -m ecd_platform --config config.json
"""

import argparse
import sys
from .config import ECDConfig, WeightingStrategy, ImagFreqPolicy, CDGauge, QMProgram
from .pipeline import ECDPipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ecd_platform",
        description="ECD-Platform: Fault-tolerant ECD workflow for natural product AC determination",
    )

    # 输入
    p.add_argument("--config", type=str, help="Load configuration from JSON file")
    p.add_argument("--opt-dir", type=str, default="opt_conf", help="OPT/FREQ output directory")
    p.add_argument("--ecd-dir", type=str, default="ecd_conf", help="ECD output directory")
    p.add_argument("--exp-file", type=str, default=None, help="Experimental ECD data file")
    p.add_argument("--weights-file", type=str, default=None, help="Manual weights file (CSV)")
    p.add_argument("--program", choices=[p.value for p in QMProgram],
                   default="auto",
                   help="QM program for input files (auto-detected by default)")

    # 光谱参数
    p.add_argument("--sigma", type=float, default=0.3, help="Gaussian broadening σ (eV)")
    p.add_argument("--shift", type=float, default=0.0, help="Energy shift (eV)")
    p.add_argument("--scale", type=float, default=1.0, help="Scaling factor")
    p.add_argument("--wl-range", nargs=2, type=float, default=[180, 450],
                   help="Wavelength range (nm)")

    # 策略
    p.add_argument("--weighting", choices=[w.value for w in WeightingStrategy],
                   default="gibbs", help="Boltzmann weighting strategy")
    p.add_argument("--imag-freq-policy", choices=[p.value for p in ImagFreqPolicy],
                   default="tolerant", help="Imaginary frequency policy")
    p.add_argument("--imag-freq-threshold", type=float, default=-10.0,
                   help="Imaginary frequency threshold (cm⁻¹, TOLERANT mode)")
    p.add_argument("--cd-gauge", choices=[g.value for g in CDGauge],
                   default="length", help="CD rotatory strength gauge")
    p.add_argument("--temperature", type=float, default=298.15, help="Temperature (K)")

    # 平滑
    p.add_argument("--smooth", choices=["fft", "savgol", "none"], default="fft",
                   help="Smoothing method for experimental data")
    p.add_argument("--smooth-factor", type=float, default=0.1,
                   help="FFT smoothing cutoff ratio (0-1)")

    # 比较
    p.add_argument("--metric", choices=["cosine", "pearson", "tanimoto"],
                   default="cosine", help="Similarity metric")
    p.add_argument("--shift-scan", nargs=2, type=float, default=[-0.5, 0.5],
                   help="Shift scan range (eV)")
    p.add_argument("--shift-step", type=float, default=0.02, help="Shift scan step (eV)")

    # 输出
    p.add_argument("--output-dir", type=str, default="ecd_results", help="Output directory")
    p.add_argument("--no-png", action="store_true", help="Skip PNG generation")
    p.add_argument("--dpi", type=int, default=300, help="Figure DPI")

    return p


def _enable_utf8_console():
    """Ensure stdout/stderr can emit non-ASCII characters (e.g. cm⁻¹, σ, Δ).

    On Windows, the default console encoding is often GBK/cp936, which raises
    UnicodeEncodeError when argparse prints help text or the pipeline logs
    progress containing these characters. Reconfiguring the text streams is
    a no-op on systems that already use UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _enable_utf8_console()
    parser = build_parser()
    args = parser.parse_args(argv)

    # 构建配置
    if args.config:
        config = ECDConfig.from_json(args.config)
    else:
        config = ECDConfig(
            opt_dir=args.opt_dir,
            ecd_dir=args.ecd_dir,
            exp_file=args.exp_file,
            weights_file=args.weights_file,
            program=QMProgram(args.program),
            sigma=args.sigma,
            shift=args.shift,
            scale_factor=args.scale,
            wavelength_range=tuple(args.wl_range),
            weighting=WeightingStrategy(args.weighting),
            imag_freq_policy=ImagFreqPolicy(args.imag_freq_policy),
            imag_freq_threshold=args.imag_freq_threshold,
            cd_gauge=CDGauge(args.cd_gauge),
            temperature=args.temperature,
            smooth_method=args.smooth,
            smooth_factor=args.smooth_factor,
            similarity_metric=args.metric,
            shift_scan_range=tuple(args.shift_scan),
            shift_scan_step=args.shift_step,
            output_dir=args.output_dir,
            save_png=not args.no_png,
            dpi=args.dpi,
        )

    # 运行
    pipeline = ECDPipeline(config)
    pipeline.run()


if __name__ == "__main__":
    main()
