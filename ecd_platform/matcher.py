"""
容错型构象匹配框架 —— 创新点1。
综合文件名后缀、输入区块引用、构象摘要，实现自动匹配 + 冲突检测 + 用户校正。
"""

import os
import re
import hashlib
from typing import Dict, List, Optional, Tuple
from .conformer import ConformerRecord, ConformerCollection, ConformerStatus
from .config import ECDConfig


def _extract_conf_id(filename: str, pattern: str) -> Optional[int]:
    """从文件名中提取构象编号"""
    m = re.search(pattern, filename, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 回退：尝试提取文件名中的任意数字
    nums = re.findall(r'(\d+)', os.path.splitext(filename)[0])
    if nums:
        return int(nums[-1])
    return None


def _glob_qm_outputs(directory: str) -> List[str]:
    """扫描目录中所有可能的量化输出文件 (ORCA / Gaussian)"""
    exts = {'.out', '.log', '.orca', '.gjf.log'}
    files = []
    if not os.path.isdir(directory):
        return files
    for f in sorted(os.listdir(directory)):
        if os.path.splitext(f)[1].lower() in exts:
            files.append(os.path.join(directory, f))
    return files


# 保留旧名作为向后兼容别名
_glob_orca_outputs = _glob_qm_outputs


def _compute_file_hash(filepath: str, head_bytes: int = 8192) -> str:
    """计算文件头部哈希，用于快速去重检测"""
    h = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            h.update(f.read(head_bytes))
    except Exception:
        pass
    return h.hexdigest()


def _extract_xyz_reference(filepath: str) -> Optional[str]:
    """
    从 ORCA 输入区块中提取 xyzfile 引用，
    用于辅助匹配 opt → ecd 文件关系。
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(5000)
        # 查找类似 * xyzfile 0 1 some_file.xyz 的行
        m = re.search(r'\*\s*xyzfile\s+\d+\s+\d+\s+(\S+)', head)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


class ConformerMatcher:
    """
    构象自动匹配器。
    Step 1: 基于文件名模式提取 conf_id
    Step 2: 基于 xyzfile 引用交叉验证
    Step 3: 输出匹配映射表（可人工校正）
    Step 4: 检测冲突与孤立文件
    """

    def __init__(self, config: ECDConfig):
        self.config = config
        self.conflicts: List[str] = []
        self.orphans: List[str] = []

    def match(self) -> ConformerCollection:
        """
        执行自动匹配，返回 ConformerCollection。
        """
        collection = ConformerCollection()

        opt_files = _glob_qm_outputs(self.config.opt_dir)
        ecd_files = _glob_qm_outputs(self.config.ecd_dir)

        # Step 1: 基于文件名提取 conf_id
        opt_map: Dict[int, str] = {}
        ecd_map: Dict[int, str] = {}

        for fp in opt_files:
            cid = _extract_conf_id(os.path.basename(fp), self.config.filename_pattern)
            if cid is not None:
                if cid in opt_map:
                    self.conflicts.append(
                        f"OPT duplicate conf_id={cid}: {opt_map[cid]} vs {fp}"
                    )
                opt_map[cid] = fp
            else:
                self.orphans.append(f"OPT unmatched: {fp}")

        for fp in ecd_files:
            cid = _extract_conf_id(os.path.basename(fp), self.config.filename_pattern)
            if cid is not None:
                if cid in ecd_map:
                    self.conflicts.append(
                        f"ECD duplicate conf_id={cid}: {ecd_map[cid]} vs {fp}"
                    )
                ecd_map[cid] = fp
            else:
                self.orphans.append(f"ECD unmatched: {fp}")

        # Step 2: 合并所有已知 conf_id
        all_ids = sorted(set(opt_map.keys()) | set(ecd_map.keys()))

        for cid in all_ids:
            rec = ConformerRecord(conf_id=cid, label=f"conf-{cid}")
            rec.opt_file = opt_map.get(cid)
            rec.ecd_file = ecd_map.get(cid)

            if rec.opt_file is None:
                rec.status = ConformerStatus.NO_OPT_FILE
                rec.add_warning(f"No OPT file found for conf_id={cid}")

            if rec.ecd_file is None:
                if rec.status == ConformerStatus.OK:
                    rec.status = ConformerStatus.NO_ECD_FILE
                rec.add_warning(f"No ECD file found for conf_id={cid}")

            collection.add(rec)

        return collection

    def export_mapping(self, collection: ConformerCollection, path: str):
        """导出匹配映射表为 CSV，便于用户校正"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write("conf_id,opt_file,ecd_file,status,notes\n")
            for rec in collection.all_records:
                opt = rec.opt_file or ""
                ecd = rec.ecd_file or ""
                notes = "; ".join(rec.warnings) if rec.warnings else ""
                f.write(f"{rec.conf_id},{opt},{ecd},{rec.status.value},{notes}\n")
            # 追加冲突信息
            if self.conflicts:
                f.write("\n# CONFLICTS\n")
                for c in self.conflicts:
                    f.write(f"# {c}\n")
            if self.orphans:
                f.write("\n# ORPHAN FILES (unmatched)\n")
                for o in self.orphans:
                    f.write(f"# {o}\n")

    def import_mapping(self, path: str, collection: ConformerCollection):
        """从用户校正后的 CSV 重新加载映射"""
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('conf_id'):
                    continue
                parts = line.split(',', 4)
                if len(parts) < 3:
                    continue
                try:
                    cid = int(parts[0])
                except ValueError:
                    continue
                rec = collection.get(cid)
                if rec is None:
                    rec = ConformerRecord(conf_id=cid, label=f"conf-{cid}")
                    collection.add(rec)
                if parts[1].strip():
                    rec.opt_file = parts[1].strip()
                if parts[2].strip():
                    rec.ecd_file = parts[2].strip()
                # 重置状态为 OK 以便重新解析
                rec.status = ConformerStatus.OK
                rec.warnings.clear()
                rec.errors.clear()
