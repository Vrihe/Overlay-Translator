"""
updater/check_update.py — GitHub Releases update checker.

Checks GitHub API for the latest release and compares semantic versions.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Tuple

import config

_logger = logging.getLogger("translator")


def _parse_version(v_str: str) -> tuple[int, ...]:
    """Parse version string like 'v1.2.3' or '1.2.3' into a tuple of integers."""
    clean = str(v_str).strip().lstrip("vV")
    parts = []
    for p in clean.split("."):
        num = ""
        for char in p:
            if char.isdigit():
                num += char
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def check_for_update(repo: str | None = None) -> Tuple[bool, str, str]:
    """Check GitHub Releases for a newer version.

    Parameters
    ----------
    repo : str, optional
        Repository in 'owner/repo' format. Defaults to ``config.GITHUB_REPO``.

    Returns
    -------
    tuple of (has_update: bool, new_version: str, download_url: str)
        Returns (True, tag_name, html_url) if a newer release exists.
        Returns (False, "", "") if app is up-to-date or if an error occurs.
    """
    if repo is None:
        repo = getattr(config, "GITHUB_REPO", "Vrihe/Overlay-Translator")

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OverlayTranslator-App",
            "Accept": "application/vnd.github.v3+json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return False, "", ""
            data = json.loads(resp.read().decode("utf-8"))

        tag_name = data.get("tag_name", "")
        html_url = data.get("html_url", "")

        if not tag_name or not html_url:
            return False, "", ""

        current_ver = getattr(config, "APP_VERSION", "1.0.0")
        if _parse_version(tag_name) > _parse_version(current_ver):
            return True, tag_name, html_url

    except Exception as e:
        _logger.debug("Update check failed (silent fallback): %s", e)
        return False, "", ""

    return False, "", ""
