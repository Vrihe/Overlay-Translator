"""
training/tracking.py — optional experiment tracking with MLflow (DagsHub or a local store).

Only numbers, short parameters, hashes and the git sha are logged. Never log text from the
screen, gold-set rows or hypotheses: tracked runs live on an external service.

Backend (first match wins):
  * OVERLAY_TRACKING=off          tracking disabled, nothing is imported or written;
  * MLFLOW_TRACKING_URI set       that server (DagsHub: https://dagshub.com/<user>/<repo>.mlflow),
                                  credentials from MLFLOW_TRACKING_USERNAME / MLFLOW_TRACKING_PASSWORD;
  * otherwise                     a local SQLite store, mlruns/mlflow.db in the project root.

``log_run`` never raises: a missing ``mlflow`` package or an unreachable server prints one
warning and training / evaluation carries on.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_URI = "sqlite:///" + (_PROJECT_ROOT / "mlruns" / "mlflow.db").as_posix()
_BAD_KEY = re.compile(r"[^0-9A-Za-z_\-. :/]")
_MAX_PARAM = 500


def enabled() -> bool:
    return os.environ.get("OVERLAY_TRACKING", "").strip().lower() not in {"off", "0", "false", "no"}


def tracking_uri() -> str:
    return os.environ.get("MLFLOW_TRACKING_URI") or LOCAL_URI


def metric_key(key: str) -> str:
    """MLflow keys allow only ``[0-9A-Za-z_-. :/]``; anything else becomes ``_``."""
    return _BAD_KEY.sub("_", key)


def flatten_metrics(data: dict, prefix: str = "") -> dict[str, float]:
    """Nested dict -> ``{"a.b": number}``; non-numeric leaves (strings, None, lists) are skipped."""
    flat: dict[str, float] = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(flatten_metrics(value, name))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            flat[metric_key(name)] = float(value)
    return flat


def clean_params(params: dict) -> dict[str, str]:
    """Stringify parameters; a path keeps only its last component (no user directories leak)."""
    out: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        text = str(value)
        if isinstance(value, Path) or re.match(r"^[A-Za-z]:[\\/]|^/", text):
            text = re.split(r"[\\/]", text.rstrip("\\/"))[-1]
        out[metric_key(str(key))] = text[:_MAX_PARAM]
    return out


def log_run(
    experiment: str,
    run_name: str,
    *,
    params: dict | None = None,
    metrics: dict | None = None,
    tags: dict | None = None,
    history: list[tuple[int, dict]] | None = None,
    artifacts: list[Path] | None = None,
) -> str | None:
    """Log one finished run; return its MLflow run id, or None when tracking is off or failed.

    ``history`` is a list of ``(step, {metric: value})`` points (training curves).
    ``artifacts`` are small summary files; do not pass data files.
    """
    if not enabled():
        return None
    try:
        import mlflow  # lazy: training-only dependency

        uri = tracking_uri()
        if uri == LOCAL_URI:
            (_PROJECT_ROOT / "mlruns").mkdir(exist_ok=True)
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment)
        with mlflow.start_run(run_name=run_name) as run:
            if params:
                mlflow.log_params(clean_params(params))
            if tags:
                mlflow.set_tags({metric_key(str(k)): str(v)[:_MAX_PARAM] for k, v in tags.items() if v is not None})
            if metrics:
                mlflow.log_metrics(flatten_metrics(metrics))
            for step, point in history or []:
                mlflow.log_metrics(flatten_metrics(point), step=int(step))
            for path in artifacts or []:
                if Path(path).is_file():
                    mlflow.log_artifact(str(path))
            return run.info.run_id
    except Exception as exc:  # tracking must never break training or evaluation
        print(f"[tracking] skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
