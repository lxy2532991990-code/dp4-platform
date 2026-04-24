"""
解析器分派层。
根据 ECDConfig.program 或文件头部的特征字符串，把解析请求路由到
ORCA 解析器或 Gaussian 解析器。

暴露与子解析器同名的入口函数，pipeline 只需 import 本模块。
"""

from __future__ import annotations

import os
from typing import Optional

from . import gaussian_parser, parser as orca_parser
from .conformer import ConformerRecord, ConformerStatus
from .config import ECDConfig, QMProgram


# ── 程序自动识别 ──────────────────────────────────────────────────

def _sniff_program(filepath: str, head_bytes: int = 131_072) -> Optional[QMProgram]:
    """
    通过读取文件开头若干字节识别量化程序。
    返回 None 表示无法识别（可能是损坏或非法文件）。

    窗口默认 128 KiB，足以覆盖 Gaussian/ORCA 的版权页 + 输入回显；
    更大的文件再往后看通常是计算正文，特征串不会延迟出现。
    """
    if not filepath or not os.path.isfile(filepath):
        return None

    head = ""
    for enc in ("utf-8", "gbk", "latin-1", "utf-16"):
        try:
            with open(filepath, "r", encoding=enc, errors="ignore") as f:
                head = f.read(head_bytes)
            break
        except Exception:
            continue

    if not head:
        return None

    # Gaussian 输出通常在头部含 "Entering Gaussian System" 或 "Gaussian XX, Revision"
    if ("Entering Gaussian System" in head
            or "Gaussian, Inc." in head
            or "This is part of the Gaussian" in head):
        return QMProgram.GAUSSIAN

    # ORCA 输出通常在头部含 "O   R   C   A"（ASCII banner）或 "Program Version"
    if "O   R   C   A" in head or "* O   R   C   A *" in head:
        return QMProgram.ORCA

    return None


def same_output_file(path_a: Optional[str], path_b: Optional[str]) -> bool:
    """Return True when two path strings point to the same output file."""
    if not path_a or not path_b:
        return False
    try:
        return os.path.samefile(path_a, path_b)
    except OSError:
        norm_a = os.path.normcase(os.path.abspath(os.path.normpath(path_a)))
        norm_b = os.path.normcase(os.path.abspath(os.path.normpath(path_b)))
        return norm_a == norm_b


def resolve_program(
    filepath: str,
    config: ECDConfig,
    record: Optional[ConformerRecord] = None,
) -> Optional[QMProgram]:
    """
    根据 config 决定使用哪个程序的解析器：
      • config.program != AUTO → 直接使用配置值
      • config.program == AUTO → 基于文件头识别；识别失败时返回 None，
        并在 record 上记一条 error。调用方应据此标记 PARSE_FAILED，
        不再静默回退到任一解析器——否则后续产生的错误会误导用户。
    """
    sniffed = _sniff_program(filepath)

    if config.program != QMProgram.AUTO:
        if sniffed is not None and sniffed != config.program:
            if record is not None:
                record.add_error(
                    f"QM program mismatch for {os.path.basename(filepath)}: "
                    f"configured '{config.program.value}' but file looks like "
                    f"'{sniffed.value}'"
                )
                record.status = ConformerStatus.PARSE_FAILED
            return None
        return config.program

    if sniffed is not None:
        return sniffed

    if record is not None:
        record.add_error(
            f"Could not auto-detect QM program from "
            f"{os.path.basename(filepath)}; "
            f"set config.program explicitly (ORCA or GAUSSIAN)"
        )
        record.status = ConformerStatus.PARSE_FAILED
    return None


# ── 分派入口（与子解析器同名）────────────────────────────────────

def parse_opt_file(
    filepath: str,
    record: ConformerRecord,
    config: ECDConfig,
) -> None:
    program = resolve_program(filepath, config, record)
    if program == QMProgram.GAUSSIAN:
        gaussian_parser.parse_opt_file(filepath, record, config)
    elif program == QMProgram.ORCA:
        orca_parser.parse_opt_file(filepath, record, config)
    # program is None → resolve_program 已经记下 error 并设置 PARSE_FAILED


def parse_ecd_file(
    filepath: str,
    record: ConformerRecord,
    config: ECDConfig,
) -> None:
    program = resolve_program(filepath, config, record)
    if program == QMProgram.GAUSSIAN:
        gaussian_parser.parse_ecd_file(filepath, record, config)
    elif program == QMProgram.ORCA:
        orca_parser.parse_ecd_file(filepath, record, config)


def parse_single_file(
    filepath: str,
    record: ConformerRecord,
    config: ECDConfig,
) -> None:
    program = resolve_program(filepath, config, record)
    if program == QMProgram.GAUSSIAN:
        gaussian_parser.parse_single_file(filepath, record, config)
    elif program == QMProgram.ORCA:
        orca_parser.parse_single_file(filepath, record, config)
