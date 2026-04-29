from __future__ import annotations

from pathlib import Path

import tomli

_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_DIR = _ROOT / "config"


def load_config() -> dict:
    path = _CONFIG_DIR / "config.toml"
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found at {path}. Copy config.example.toml to config.toml and fill in your API keys."
        )
    return tomli.loads(path.read_text())


def project_root() -> Path:
    return _ROOT
