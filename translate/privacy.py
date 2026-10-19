"""
translate/privacy.py — keeps captured screen text out of the log files.

Whatever the user selects on screen (private chats, passwords, card numbers)
must not pile up in app.log / translator.log. Log calls pass text through
``loggable()``, which only reports its length unless ``OVERLAY_LOG_TEXT=1``
is set for a debugging session.
"""

import config


def loggable(text: str | None, limit: int = 80) -> str:
    """Return *text* in a form that is safe to write to a log file."""
    if text is None:
        return "None"
    if config.LOG_TEXT:
        return repr(text[:limit])
    return f"<{len(text)} chars>"
