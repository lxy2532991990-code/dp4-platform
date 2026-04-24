"""
能量与权重模块 —— 创新点3：可配置的虚频容差与加权策略。
支持多种能量来源的 Boltzmann 权重，以及手动权重导入。
"""

import os
import numpy as np
from typing import Optional, Dict, List
from .conformer import ConformerRecord, ConformerCollection, ConformerStatus
from .config import ECDConfig, WeightingStrategy


# ── 常数 ──
HARTREE_TO_KCAL = 627.5095
R_GAS = 1.987204e-3  # kcal/(mol·K)


def compute_boltzmann_weights(
    collection: ConformerCollection,
    config: ECDConfig
):
    """
    根据配置的能量来源计算 Boltzmann 权重。
    仅对 usable 构象计算，失败构象的权重为 0。
    """
    usable = collection.usable_records
    if not usable:
        return

    # 选择能量来源
    energies: Dict[int, float] = {}
    missing = []

    for rec in usable:
        e = _get_energy(rec, config.weighting)
        if e is not None:
            energies[rec.conf_id] = e
        else:
            missing.append(rec)

    # 处理缺失能量的构象
    for rec in missing:
        rec.add_warning(
            f"No energy available for strategy '{config.weighting.value}'; "
            f"conformer excluded from Boltzmann weighting"
        )
        rec.boltzmann_weight = 0.0

    if not energies:
        return

    # 计算相对能量
    e_min = min(energies.values())
    for cid, e_abs in energies.items():
        rec = collection.get(cid)
        rel_kcal = (e_abs - e_min) * HARTREE_TO_KCAL
        rec.relative_energy_kcal = rel_kcal

    # Boltzmann 分布
    T = config.temperature
    weights = {}
    for cid, e_abs in energies.items():
        rec = collection.get(cid)
        dE = rec.relative_energy_kcal
        weights[cid] = np.exp(-dE / (R_GAS * T))

    total = sum(weights.values())
    for cid, w in weights.items():
        rec = collection.get(cid)
        rec.boltzmann_weight = w / total


def _get_energy(rec: ConformerRecord, strategy: WeightingStrategy) -> Optional[float]:
    """根据策略选择能量值"""
    if strategy == WeightingStrategy.ELECTRONIC:
        return rec.scf_energy
    elif strategy == WeightingStrategy.GIBBS:
        if rec.gibbs_energy is not None:
            return rec.gibbs_energy
        # 回退到 SCF + Gibbs correction
        if rec.scf_energy is not None and rec.gibbs_correction is not None:
            return rec.scf_energy + rec.gibbs_correction
        # 再回退到纯 SCF
        if rec.scf_energy is not None:
            rec.add_warning("Gibbs energy unavailable, falling back to SCF energy")
            return rec.scf_energy
        return None
    elif strategy == WeightingStrategy.SINGLE_POINT:
        if rec.sp_energy is not None:
            return rec.sp_energy
        rec.add_warning("Single-point energy unavailable, falling back to Gibbs/SCF")
        return _get_energy(rec, WeightingStrategy.GIBBS)
    elif strategy == WeightingStrategy.MANUAL:
        # Manual 模式不使用 Boltzmann，直接用 manual_weight
        return rec.scf_energy  # 仍需能量做排序
    return None


def load_manual_weights(
    collection: ConformerCollection,
    weights_file: str
):
    """
    从外部权重文件加载手动权重。
    格式：每行 conf_id, weight  (CSV)
    """
    if not os.path.exists(weights_file):
        return

    for enc in ['utf-8', 'gbk', 'latin-1']:
        try:
            with open(weights_file, 'r', encoding=enc, errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split(',')
                    if len(parts) >= 2:
                        try:
                            cid = int(parts[0].strip())
                            w = float(parts[1].strip())
                            rec = collection.get(cid)
                            if rec is not None:
                                rec.manual_weight = w
                                rec.boltzmann_weight = w
                            else:
                                # 创建新记录
                                rec = ConformerRecord(conf_id=cid)
                                rec.manual_weight = w
                                rec.boltzmann_weight = w
                                collection.add(rec)
                        except ValueError:
                            continue
            break
        except UnicodeDecodeError:
            continue

    # 归一化
    collection.normalize_weights()


def weight_sensitivity_analysis(
    collection: ConformerCollection,
    config: ECDConfig,
    temperature_range: tuple = (248.15, 348.15),
    n_temps: int = 5
) -> Dict[float, Dict[int, float]]:
    """
    权重敏感性分析：在不同温度下计算 Boltzmann 权重，
    帮助评估权重对温度的敏感度。
    返回 {temperature: {conf_id: weight}}
    """
    temps = np.linspace(temperature_range[0], temperature_range[1], n_temps)
    results = {}

    for T in temps:
        temp_config = ECDConfig(
            weighting=config.weighting,
            temperature=T
        )
        # 临时计算
        usable = collection.usable_records
        energies = {}
        for rec in usable:
            e = _get_energy(rec, config.weighting)
            if e is not None:
                energies[rec.conf_id] = e

        if not energies:
            results[T] = {}
            continue

        e_min = min(energies.values())
        weights = {}
        for cid, e_abs in energies.items():
            dE = (e_abs - e_min) * HARTREE_TO_KCAL
            weights[cid] = np.exp(-dE / (R_GAS * T))

        total = sum(weights.values())
        results[T] = {cid: w / total for cid, w in weights.items()}

    return results
