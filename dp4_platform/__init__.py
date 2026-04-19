"""Standalone DP4-style workflow package."""

from .config import DP4Config, ImagFreqPolicy, ScalingMode, WeightingStrategy
from .pipeline import DP4Pipeline

__all__ = [
    "DP4Config",
    "DP4Pipeline",
    "ImagFreqPolicy",
    "ScalingMode",
    "WeightingStrategy",
]

__version__ = "0.1.0"
