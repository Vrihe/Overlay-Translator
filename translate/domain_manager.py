"""
translate/domain_manager.py — domain profiles loader.

Loads JSON-based domain prompts and few-shot examples for adaptive translation.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("translator")


def _get_profiles_dir() -> Path:
    """Return absolute path to domain_profiles directory (PyInstaller compatible)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "translate" / "domain_profiles"
            if p.exists():
                return p
    return Path(__file__).resolve().parent / "domain_profiles"


_DEFAULT_PROFILE: dict[str, Any] = {
    "id": "general",
    "display_name": "Общий",
    "system_prompt": (
        "Ты высококвалифицированный профессиональный переводчик. "
        "Переводи предоставленный текст точным, естественным и грамматически правильным языком. "
        "Сохраняй исходный смысл, тон и структуру оригинала. "
        "Не добавляй от себя никаких комментариев, пояснений или вводных фраз. "
        "Возвращай ИСКЛЮЧИТЕЛЬНО готовый перевод."
    ),
    "few_shot_examples": [],
}


def load_domain_profile(domain_id: str) -> dict[str, Any]:
    """Read and parse JSON domain profile by *domain_id*.

    Falls back to 'general.json' if file is missing, corrupted, or *domain_id* is invalid.

    Parameters
    ----------
    domain_id : str
        Domain identifier (e.g. 'game', 'documentation', 'chat', 'general').

    Returns
    -------
    dict
        Parsed profile dictionary containing 'id', 'display_name', 'system_prompt',
        and 'few_shot_examples'.
    """
    clean_id = str(domain_id or "general").strip().lower()
    profiles_dir = _get_profiles_dir()
    filepath = profiles_dir / f"{clean_id}.json"

    if not filepath.exists() and clean_id != "general":
        filepath = profiles_dir / "general.json"

    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "system_prompt" in data:
                return data
        except Exception as e:
            logger.warning("Error reading domain profile %s: %s", filepath, e)

    if clean_id != "general":
        general_path = profiles_dir / "general.json"
        if general_path.exists():
            try:
                with open(general_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "system_prompt" in data:
                    return data
            except Exception:
                pass

    return dict(_DEFAULT_PROFILE)


def list_available_domains() -> list[dict[str, str]]:
    """Return a list of all available domains with 'id' and 'display_name'."""
    domains: list[dict[str, str]] = []
    profiles_dir = _get_profiles_dir()

    preferred_order = ["general", "game", "documentation", "chat"]
    seen = set()

    for dom_id in preferred_order:
        fp = profiles_dir / f"{dom_id}.json"
        if fp.exists():
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                domains.append({
                    "id": data.get("id", dom_id),
                    "display_name": data.get("display_name", dom_id.capitalize()),
                })
                seen.add(dom_id)
            except Exception:
                pass

    if profiles_dir.exists():
        for fp in sorted(profiles_dir.glob("*.json")):
            dom_id = fp.stem
            if dom_id not in seen:
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    domains.append({
                        "id": data.get("id", dom_id),
                        "display_name": data.get("display_name", dom_id.capitalize()),
                    })
                except Exception:
                    pass

    if not domains:
        domains.append({"id": "general", "display_name": "Общий"})

    return domains
