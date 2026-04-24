"""
实验谱自动比较与绝对构型判定模块 —— 创新点5。
实现 shift 扫描、相似度评分、对映体比较、候选排序。
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict


@dataclass
class ComparisonResult:
    """单次比较结果"""
    shift_ev: float
    similarity: float
    metric: str
    is_inverted: bool = False   # True 表示对映体
    label: str = ""


@dataclass
class ACDetermination:
    """绝对构型判定结果"""
    best_match: ComparisonResult
    ent_match: ComparisonResult
    confidence: str = ""         # high / medium / low
    all_results: List[ComparisonResult] = field(default_factory=list)
    recommendation: str = ""

    @property
    def delta_similarity(self) -> float:
        return self.best_match.similarity - self.ent_match.similarity


# ── 相似度指标 ──

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度，范围 [-1, 1]"""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def pearson_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson 相关系数"""
    if len(a) < 3:
        return 0.0
    a_c = a - np.mean(a)
    b_c = b - np.mean(b)
    denom = np.linalg.norm(a_c) * np.linalg.norm(b_c)
    if denom == 0:
        return 0.0
    return float(np.dot(a_c, b_c) / denom)


def tanimoto_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Tanimoto 系数（连续向量版本）"""
    ab = np.dot(a, b)
    aa = np.dot(a, a)
    bb = np.dot(b, b)
    denom = aa + bb - ab
    if denom == 0:
        return 0.0
    return float(ab / denom)


_METRICS = {
    'cosine': cosine_similarity,
    'pearson': pearson_correlation,
    'tanimoto': tanimoto_similarity,
}


# ── 核心比较 ──

def compare_spectra(
    calc_spectrum: np.ndarray,
    calc_wavelengths: np.ndarray,
    exp_spectrum: np.ndarray,
    exp_wavelengths: np.ndarray,
    metric: str = "cosine"
) -> float:
    """
    在共同波长范围内插值后计算相似度。
    """
    # 确定公共波长范围
    wl_min = max(calc_wavelengths.min(), exp_wavelengths.min())
    wl_max = min(calc_wavelengths.max(), exp_wavelengths.max())

    if wl_min >= wl_max:
        return 0.0

    # 公共网格
    n = min(1000, max(len(calc_wavelengths), len(exp_wavelengths)))
    common_wl = np.linspace(wl_min, wl_max, n)

    # 插值
    calc_interp = np.interp(common_wl, calc_wavelengths, calc_spectrum)
    exp_interp = np.interp(common_wl, exp_wavelengths, exp_spectrum)

    func = _METRICS.get(metric, cosine_similarity)
    return func(calc_interp, exp_interp)


def shift_scan(
    calc_spectrum: np.ndarray,
    energy_grid: np.ndarray,
    exp_spectrum: np.ndarray,
    exp_wavelengths: np.ndarray,
    shift_range: Tuple[float, float] = (-0.5, 0.5),
    shift_step: float = 0.02,
    metric: str = "cosine",
    auto_invert: bool = True
) -> ACDetermination:
    """
    在指定的 shift 范围内扫描，找到最佳匹配。
    同时测试正常和倒置（对映体）版本。
    
    Parameters:
        calc_spectrum: 计算的加权谱（在能量网格上）
        energy_grid: 能量网格 (eV)
        exp_spectrum: 实验强度
        exp_wavelengths: 实验波长 (nm)
        shift_range: 扫描范围 (eV)
        shift_step: 扫描步长 (eV)
        metric: 相似度指标
        auto_invert: 是否自动测试对映体
    """
    shifts = np.arange(shift_range[0], shift_range[1] + shift_step / 2, shift_step)
    all_results: List[ComparisonResult] = []

    for s in shifts:
        shifted_e = energy_grid + s
        shifted_wl = 1239.84193 / shifted_e

        # 排序（波长升序）
        sort_idx = np.argsort(shifted_wl)
        wl_sorted = shifted_wl[sort_idx]
        spec_sorted = calc_spectrum[sort_idx]

        # 正常
        sim = compare_spectra(spec_sorted, wl_sorted, exp_spectrum, exp_wavelengths, metric)
        all_results.append(ComparisonResult(
            shift_ev=s, similarity=sim, metric=metric,
            is_inverted=False, label="normal"
        ))

        # 对映体
        if auto_invert:
            sim_inv = compare_spectra(-spec_sorted, wl_sorted, exp_spectrum, exp_wavelengths, metric)
            all_results.append(ComparisonResult(
                shift_ev=s, similarity=sim_inv, metric=metric,
                is_inverted=True, label="enantiomer"
            ))

    # 找最优
    normal_results = [r for r in all_results if not r.is_inverted]
    invert_results = [r for r in all_results if r.is_inverted]

    best_normal = max(normal_results, key=lambda r: r.similarity)
    best_invert = max(invert_results, key=lambda r: r.similarity) if invert_results else \
        ComparisonResult(shift_ev=0, similarity=-1, metric=metric, is_inverted=True)

    # 判定
    if best_normal.similarity >= best_invert.similarity:
        best = best_normal
        ent = best_invert
    else:
        best = best_invert
        ent = best_normal

    # 置信度评估
    delta = abs(best.similarity - ent.similarity)
    if delta > 0.3:
        confidence = "high"
    elif delta > 0.1:
        confidence = "medium"
    else:
        confidence = "low"

    recommendation = _generate_recommendation(best, ent, confidence)

    return ACDetermination(
        best_match=best,
        ent_match=ent,
        confidence=confidence,
        all_results=all_results,
        recommendation=recommendation
    )


def _generate_recommendation(
    best: ComparisonResult,
    ent: ComparisonResult,
    confidence: str
) -> str:
    lines = []
    lines.append(f"Best match: {'enantiomer (inverted)' if best.is_inverted else 'original'}")
    lines.append(f"  Similarity = {best.similarity:.4f} (shift = {best.shift_ev:+.3f} eV)")
    lines.append(f"  Metric: {best.metric}")
    lines.append(f"Enantiomer match:")
    lines.append(f"  Similarity = {ent.similarity:.4f} (shift = {ent.shift_ev:+.3f} eV)")
    lines.append(f"ΔSimilarity = {abs(best.similarity - ent.similarity):.4f}")
    lines.append(f"Confidence: {confidence}")
    if confidence == "low":
        lines.append("⚠ Low confidence: consider additional conformers or larger basis set.")
    return "\n".join(lines)


def multi_candidate_ranking(
    candidates: Dict[str, Tuple[np.ndarray, np.ndarray]],
    exp_spectrum: np.ndarray,
    exp_wavelengths: np.ndarray,
    shift_range: Tuple[float, float] = (-0.5, 0.5),
    shift_step: float = 0.02,
    metric: str = "cosine"
) -> List[Tuple[str, ACDetermination]]:
    """
    对多个候选异构体进行排名。
    
    candidates: {name: (calc_spectrum, energy_grid)}
    """
    rankings = []
    for name, (spec, e_grid) in candidates.items():
        ac = shift_scan(spec, e_grid, exp_spectrum, exp_wavelengths,
                        shift_range, shift_step, metric)
        rankings.append((name, ac))

    # 按最佳匹配的相似度排序（降序）
    rankings.sort(key=lambda x: x[1].best_match.similarity, reverse=True)
    return rankings
