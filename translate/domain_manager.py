"""
translate/domain_manager.py — domain profiles loader & manager.

Loads JSON-based domain prompts and few-shot examples for adaptive translation.
Supports custom user-defined domain profiles.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("translator")


def _get_user_data_dir() -> Path:
    """Return user AppData directory for persistent app data."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / "translator-overlay"
            p.mkdir(parents=True, exist_ok=True)
            return p
    p = Path.home() / ".config" / "translator-overlay"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_profiles_dir() -> Path:
    """Return absolute path to built-in domain_profiles directory (PyInstaller compatible)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "translate" / "domain_profiles"
            if p.exists():
                return p
    return Path(__file__).resolve().parent / "domain_profiles"


def _get_custom_profiles_dirs() -> list[Path]:
    """Return list of search directories for custom profiles.
    
    1. Local translate/domain_profiles/custom/
    2. %APPDATA%/translator-overlay/domain_profiles/custom/
    """
    dirs: list[Path] = []
    
    # 1. Project local directory
    local_dir = _get_profiles_dir() / "custom"
    dirs.append(local_dir)
    
    # 2. AppData user directory
    user_dir = _get_user_data_dir() / "domain_profiles" / "custom"
    dirs.append(user_dir)
    
    return dirs


def _get_writable_custom_dir() -> Path:
    """Return writable directory for saving custom profiles."""
    local_dir = _get_profiles_dir() / "custom"
    try:
        local_dir.mkdir(parents=True, exist_ok=True)
        # Test write permission
        test_file = local_dir / ".perm_test"
        with open(test_file, "w") as f:
            f.write("ok")
        test_file.unlink()
        return local_dir
    except (OSError, PermissionError):
        pass
    
    user_dir = _get_user_data_dir() / "domain_profiles" / "custom"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


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
    "is_custom": False,
}

_BUILTIN_IDS = {"general", "game", "documentation", "chat"}


def generate_slug(display_name: str) -> str:
    """Generate a clean URL/filename-safe slug from display_name."""
    s = display_name.strip().lower()
    translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    res = []
    for char in s:
        if char in translit:
            res.append(translit[char])
        elif char.isalnum():
            res.append(char)
        elif char in (' ', '_', '-'):
            res.append('_')
    slug = re.sub(r'_+', '_', ''.join(res)).strip('_')
    if not slug or slug in _BUILTIN_IDS:
        slug = f"custom_{slug}" if slug else "custom_profile"
    return slug


def load_domain_profile(domain_id: str) -> dict[str, Any]:
    """Read and parse JSON domain profile by *domain_id*.

    Searches custom profiles first, then built-in profiles.
    Falls back to 'general.json' if missing or corrupted.
    """
    clean_id = str(domain_id or "general").strip().lower()

    # 1. Search in custom directories
    for custom_dir in _get_custom_profiles_dirs():
        fp = custom_dir / f"{clean_id}.json"
        if fp.exists():
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "system_prompt" in data:
                    data["is_custom"] = True
                    return data
            except Exception as e:
                logger.warning("Error reading custom profile %s: %s", fp, e)

    # 2. Search in built-in directory
    profiles_dir = _get_profiles_dir()
    filepath = profiles_dir / f"{clean_id}.json"
    if not filepath.exists() and clean_id != "general":
        filepath = profiles_dir / "general.json"

    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "system_prompt" in data:
                data["is_custom"] = False
                return data
        except Exception as e:
            logger.warning("Error reading domain profile %s: %s", filepath, e)

    return dict(_DEFAULT_PROFILE)


def list_available_domains() -> list[dict[str, Any]]:
    """Return a list of all available domains (built-in + custom) with metadata."""
    domains: list[dict[str, Any]] = []
    preferred_order = ["general", "game", "documentation", "chat"]
    seen = set()

    profiles_dir = _get_profiles_dir()

    # 1. Built-in preferred
    for dom_id in preferred_order:
        fp = profiles_dir / f"{dom_id}.json"
        if fp.exists():
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                domains.append({
                    "id": data.get("id", dom_id),
                    "display_name": data.get("display_name", dom_id.capitalize()),
                    "is_custom": False,
                })
                seen.add(dom_id)
            except Exception:
                pass

    # 2. Other built-in
    if profiles_dir.exists():
        for fp in sorted(profiles_dir.glob("*.json")):
            dom_id = fp.stem
            if dom_id not in seen and dom_id != "custom":
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    domains.append({
                        "id": data.get("id", dom_id),
                        "display_name": data.get("display_name", dom_id.capitalize()),
                        "is_custom": False,
                    })
                    seen.add(dom_id)
                except Exception:
                    pass

    # 3. Custom profiles
    for custom_dir in _get_custom_profiles_dirs():
        if custom_dir.exists():
            for fp in sorted(custom_dir.glob("*.json")):
                dom_id = fp.stem
                if dom_id not in seen:
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        domains.append({
                            "id": data.get("id", dom_id),
                            "display_name": data.get("display_name", dom_id.capitalize()),
                            "is_custom": True,
                        })
                        seen.add(dom_id)
                    except Exception:
                        pass

    if not domains:
        domains.append({"id": "general", "display_name": "Общий", "is_custom": False})

    return domains


def save_custom_profile(
    display_name: str,
    system_prompt: str,
    few_shot_examples: list[dict[str, str]],
    existing_id: str | None = None,
) -> dict[str, Any]:
    """Save custom domain profile JSON to the custom directory."""
    if not display_name.strip():
        raise ValueError("Название профиля не может быть пустым.")
    if not system_prompt.strip():
        raise ValueError("Системный промпт не может быть пустым.")

    profile_id = existing_id if existing_id else generate_slug(display_name)
    target_dir = _get_writable_custom_dir()
    filepath = target_dir / f"{profile_id}.json"

    # Filter clean examples
    clean_examples = []
    for ex in few_shot_examples:
        s = str(ex.get("source", "")).strip()
        t = str(ex.get("translation", "")).strip()
        if s and t:
            clean_examples.append({"source": s, "translation": t})

    profile_data = {
        "id": profile_id,
        "display_name": display_name.strip(),
        "system_prompt": system_prompt.strip(),
        "few_shot_examples": clean_examples,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2, ensure_ascii=False)

    profile_data["is_custom"] = True
    logger.info("Saved custom domain profile '%s' to %s", profile_id, filepath)
    return profile_data


def delete_custom_profile(domain_id: str) -> bool:
    """Delete custom domain profile JSON by domain_id."""
    clean_id = str(domain_id or "").strip().lower()
    if clean_id in _BUILTIN_IDS or not clean_id:
        raise ValueError("Нельзя удалить предустановленный профиль.")

    deleted = False
    for custom_dir in _get_custom_profiles_dirs():
        fp = custom_dir / f"{clean_id}.json"
        if fp.exists():
            try:
                fp.unlink()
                deleted = True
                logger.info("Deleted custom profile %s", fp)
            except Exception as e:
                logger.error("Failed to delete custom profile %s: %s", fp, e)

    return deleted
