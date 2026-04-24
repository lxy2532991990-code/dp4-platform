"""Unified project persistence for the DP4 Platform application."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import DP4Config


PROJECT_SCHEMA_VERSION = 1


@dataclass
class PlatformProject:
    dp4: DP4Config = field(default_factory=DP4Config)
    ecd: dict = field(default_factory=dict)
    active_module: str = "home"
    schema_version: int = PROJECT_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "active_module": self.active_module,
            "dp4": self.dp4.to_dict(),
            "ecd": dict(self.ecd),
        }


def load_platform_project(path: str) -> PlatformProject:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, dict) and "dp4" in data:
        return PlatformProject(
            schema_version=int(data.get("schema_version", PROJECT_SCHEMA_VERSION)),
            active_module=str(data.get("active_module", "home")),
            dp4=DP4Config.from_dict(data.get("dp4") or {}),
            ecd=dict(data.get("ecd") or {}),
        )

    return PlatformProject(dp4=DP4Config.from_dict(data), ecd={}, active_module="dp4")


def save_platform_project(path: str, project: PlatformProject) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(project.to_dict(), fh, indent=2, ensure_ascii=False)
