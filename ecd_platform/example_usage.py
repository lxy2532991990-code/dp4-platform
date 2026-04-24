#!/usr/bin/env python3
"""
ECD-Platform 使用示例
====================

本脚本演示了平台的三种典型使用场景：
  1. 最简调用：仅需指定目录和参数
  2. 高级配置：定制虚频策略、权重来源、比较参数
  3. 多候选异构体排名

目录结构要求：
  opt_conf/
    ├── opt-conf-1.out     # 构象1的优化/频率计算输出
    ├── opt-conf-2.out
    ├── ...
    └── ecd_weights.txt    # 可选：手动权重文件 (conf_id, weight)
  ecd_conf/
    ├── ecd-conf-1.out     # 构象1的 ECD/TDDFT 计算输出
    ├── ecd-conf-2.out
    └── ...
  experiment.csv           # 可选：实验 ECD 数据
"""

import os
import sys

# 确保可以导入 ecd_platform
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ecd_platform import ECDPipeline, ECDConfig, WeightingStrategy, ImagFreqPolicy
from ecd_platform.config import CDGauge


def example_basic():
    """
    场景1: 最简调用
    从 ORCA 输出直接生成 ECD 谱图和分析报告。
    """
    config = ECDConfig(
        opt_dir='opt_conf',
        ecd_dir='ecd_opt_60_roots',
        exp_file='experiment.csv',        # 可选
        sigma=0.3,
        shift=0.15,
        scale_factor=5.0,
        output_dir='results_basic',
    )

    pipeline = ECDPipeline(config)
    pipeline.run()

    # 运行后在 results_basic/ 下会自动生成：
    #   analysis_report.txt     - 完整分析报告
    #   ecd_comparison_*.png    - ECD 对比图
    #   shift_scan.png          - Shift 扫描图
    #   ecd_data_*.csv          - 数据 CSV
    #   config.json             - 参数存档
    #   conformer_mapping.csv   - 构象匹配映射表
    #   conformer_status.txt    - 异常报告


def example_advanced():
    """
    场景2: 高级配置
    定制虚频策略、权重来源和比较参数。
    """
    config = ECDConfig(
        opt_dir='opt_conf',
        ecd_dir='ecd_opt_60_roots',
        exp_file='experiment.csv',

        # ── 虚频容差策略（创新点3）──
        # TOLERANT 模式：仅 < -10 cm⁻¹ 才剔除
        # 适合天然产物中常见的小虚频情况
        imag_freq_policy=ImagFreqPolicy.TOLERANT,
        imag_freq_threshold=-10.0,

        # ── 权重策略 ──
        # 使用 Gibbs 自由能（含热校正）
        weighting=WeightingStrategy.GIBBS,
        temperature=298.15,

        # ── CD 规范 ──
        cd_gauge=CDGauge.LENGTH,

        # ── 光谱参数 ──
        sigma=0.25,
        shift=0.0,                        # 由 shift_scan 自动确定最优值
        scale_factor=1.0,
        wavelength_range=(200, 400),

        # ── 实验谱处理 ──
        smooth_method='fft',
        smooth_factor=0.08,               # 较强平滑

        # ── AC 判定参数 ──
        shift_scan_range=(-0.4, 0.4),
        shift_scan_step=0.01,             # 更精细的扫描
        similarity_metric='cosine',
        auto_invert=True,

        # ── 图例 ──
        plot_exp_label='Experimental ECD of compound 1',
        plot_calc_label='Calculated ECD of (R)-1',
        plot_ent_label='Calculated ECD of (S)-1',

        # ── 输出 ──
        output_dir='results_advanced',
        dpi=600,                          # 高分辨率
    )

    pipeline = ECDPipeline(config)
    pipeline.run()

    # 也可以单独访问中间结果
    if pipeline.ac_result:
        print(f"\n最佳匹配: {pipeline.ac_result.best_match.similarity:.4f}")
        print(f"置信度: {pipeline.ac_result.confidence}")


def example_multi_candidate():
    """
    场景3: 多候选异构体排名
    对同一化合物的多个可能构型分别计算 ECD，比较哪个与实验谱最匹配。
    """
    from ecd_platform.experimental import read_experimental_data
    from ecd_platform.comparison import multi_candidate_ranking

    # 读取实验数据
    exp_wl, exp_spec = read_experimental_data('experiment.csv')
    if exp_wl is None:
        print("无法读取实验数据")
        return

    # 对每个候选构型分别运行 pipeline（或手动提供谱数据）
    candidates = {}

    for name, opt_dir, ecd_dir in [
        ('(R,S)-isomer', 'isomer_RS/opt', 'isomer_RS/ecd'),
        ('(S,R)-isomer', 'isomer_SR/opt', 'isomer_SR/ecd'),
        ('(R,R)-isomer', 'isomer_RR/opt', 'isomer_RR/ecd'),
    ]:
        if not os.path.exists(opt_dir):
            continue
        config = ECDConfig(opt_dir=opt_dir, ecd_dir=ecd_dir, sigma=0.3)
        pipe = ECDPipeline(config)
        pipe.step1_match()
        pipe.step2_parse()
        pipe.step3_weight()
        pipe.step4_spectrum()

        if pipe.calc_spectrum is not None:
            candidates[name] = (pipe.calc_spectrum, pipe.energy_grid)

    if candidates:
        rankings = multi_candidate_ranking(
            candidates, exp_spec, exp_wl, metric='cosine'
        )
        print("\n── 候选异构体排名 ──")
        for rank, (name, ac) in enumerate(rankings, 1):
            print(f"  {rank}. {name}")
            print(f"     Similarity = {ac.best_match.similarity:.4f}")
            print(f"     {'(inverted)' if ac.best_match.is_inverted else '(normal)'}")
            print(f"     Confidence = {ac.confidence}")


def example_from_config_file():
    """
    场景4: 从 JSON 配置文件加载
    保证实验可复现。
    """
    config = ECDConfig.from_json('config.json')
    pipeline = ECDPipeline(config)
    pipeline.run()


if __name__ == '__main__':
    # 默认运行基础示例
    # 根据实际数据目录选择运行
    print("请根据您的数据目录修改示例中的路径后运行")
    print("可用示例: example_basic(), example_advanced(), example_multi_candidate()")
