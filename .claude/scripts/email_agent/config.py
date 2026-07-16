"""
email_agent/config.py — Load and validate config.json.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

# config.py lives at <repo>/.claude/scripts/email_agent/config.py → parents[3] is the repo root
_AGENT_DIR = Path(__file__).resolve().parents[3]  # EmailPrioritizationAgent/

# Connector mode needs no Azure credentials — auth is handled by the
# Microsoft 365 connector, not this script.
REQUIRED_KEYS: set[str] = set()
WEIGHT_KEYS = {"sender_authority", "action_language", "recency",
               "thread_depth", "importance_flag", "has_attachment"}


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load, validate, and return the config dict.

    Resolution order:
    1. Explicit config_path argument
    2. config.json in the agent root
    3. Single config-*.json in the agent root (auto-select)
    """
    if config_path:
        path = Path(config_path)
        if not path.is_absolute():
            path = _AGENT_DIR / path
    else:
        default = _AGENT_DIR / "config.json"
        if default.exists():
            path = default
        else:
            candidates = list(_AGENT_DIR.glob("config-*.json"))
            if len(candidates) == 1:
                path = candidates[0]
            elif len(candidates) == 0:
                raise FileNotFoundError("No config.json found. See HELP-CONFIG.md.")
            else:
                names = [c.name for c in candidates]
                raise FileNotFoundError(
                    f"Multiple config files found and no default config.json.\n"
                    f"Pass --config <file> to choose one of: {names}"
                )

    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)

    _validate(cfg, path)
    return cfg


def _validate(cfg: dict, path: Path) -> None:
    missing = REQUIRED_KEYS - set(cfg)
    if missing:
        raise ValueError(f"config {path.name} missing required keys: {missing}")

    weights = cfg.get("weights", {})
    missing_w = WEIGHT_KEYS - set(weights)
    if missing_w:
        raise ValueError(f"config 'weights' missing keys: {missing_w}")

    total = sum(weights.values())
    if not (0.99 <= total <= 1.01):
        raise ValueError(
            f"config 'weights' must sum to 1.0 (got {total:.4f}). "
            "Check HELP-CONFIG.md."
        )
