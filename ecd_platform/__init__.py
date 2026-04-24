"""
ECD-Platform: 面向天然产物绝对构型解析的高容错 ECD 工作流平台
"""

__version__ = "0.2.0"
__author__ = "ECD-Platform Contributors"

from .config import ECDConfig, WeightingStrategy, ImagFreqPolicy, CDGauge, QMProgram
from .conformer import ConformerStatus, ConformerRecord
from .pipeline import ECDPipeline

__all__ = [
    "__version__",
    "__author__",
    "ECDConfig",
    "WeightingStrategy",
    "ImagFreqPolicy",
    "CDGauge",
    "QMProgram",
    "ConformerStatus",
    "ConformerRecord",
    "ECDPipeline",
]
