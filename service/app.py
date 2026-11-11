"""
service/app.py — the local NLLB inference service (roadmap stage 11).

    POST /translate   {"texts": ["..."], "target_lang": "ru", "source_lang": "en"|null}
                      -> {"translations": ["..."], "latency_ms": 12.3}
    GET  /health      200 {"status": "ok"} once the model can be loaded, 503 otherwise
    GET  /version     {"service": ..., "model": ...}
    GET  /metrics     Prometheus text format (latency, batch size, errors, cache hits)

The service wraps ``translate.nllb_backend`` and never touches the network (the offline
guarantee of the local backend). Screen text is user data: it is never logged here and never
appears in the metrics.

``create_app`` takes the translate and health callables, so tests run without a model.
FastAPI is imported inside ``create_app`` (the desktop app does not need it); install
``requirements-service.txt`` to run the service.

Run:  python -m service            (127.0.0.1:8765, see ``--help``)
"""

# No ``from __future__ import annotations`` here: FastAPI resolves the annotations of the handlers
# below, which refer to classes and imports local to ``create_app``.

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from service.metrics import Metrics

SERVICE_VERSION = "1.0.0"
MAX_TEXTS = 32
MAX_CHARS = 5000
CACHE_SIZE = 256  # this LRU lives in memory only; the NLLB backend keeps its own SQLite history (cache/store.py)


def _default_translate(text: str, target_lang: str, source_lang: str | None) -> str:
    from translate import nllb_backend

    return nllb_backend.translate(text, target_lang=target_lang, source_lang=source_lang)


def _default_ready() -> bool:
    from translate import nllb_backend

    return nllb_backend.is_available()


def _default_model_version() -> str:
    import config

    return str(getattr(config, "NLLB_HF_REVISION", "unknown"))


def create_app(
    translate: Callable[[str, str, str | None], str] | None = None,
    ready: Callable[[], bool] | None = None,
    model_version: Callable[[], str] | None = None,
    metrics: Metrics | None = None,
):
    """Build the FastAPI application. All collaborators are injectable for tests."""
    from fastapi import FastAPI, HTTPException, Response
    from pydantic import BaseModel, Field

    translate = translate or _default_translate
    ready = ready or _default_ready
    model_version = model_version or _default_model_version
    metrics = metrics or Metrics()

    cache: OrderedDict[tuple, str] = OrderedDict()
    cache_lock = threading.Lock()

    def cached_translate(text: str, target_lang: str, source_lang: str | None) -> tuple[str, bool]:
        key = (text, target_lang, source_lang)
        with cache_lock:
            if key in cache:
                cache.move_to_end(key)
                return cache[key], True
        result = translate(text, target_lang, source_lang)
        with cache_lock:
            cache[key] = result
            while len(cache) > CACHE_SIZE:
                cache.popitem(last=False)
        return result, False

    class TranslateRequest(BaseModel):
        texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)
        target_lang: str = Field(min_length=2, max_length=8)
        source_lang: str | None = Field(default=None, max_length=8)

    app = FastAPI(title="Overlay-Translator local service", version=SERVICE_VERSION)

    @app.post("/translate")
    def translate_endpoint(body: TranslateRequest):
        if any(len(t) > MAX_CHARS for t in body.texts):
            raise HTTPException(status_code=413, detail=f"a text is longer than {MAX_CHARS} characters")
        started = time.perf_counter()
        try:
            results = [cached_translate(t, body.target_lang, body.source_lang) for t in body.texts]
        except Exception as exc:
            metrics.record(latency=time.perf_counter() - started, batch_size=len(body.texts), error=True)
            # the message of the exception, never the request text
            raise HTTPException(status_code=502, detail=f"translation failed: {type(exc).__name__}") from exc
        elapsed = time.perf_counter() - started
        out = [text for text, _hit in results]
        metrics.record(latency=elapsed, batch_size=len(body.texts), hits=sum(hit for _t, hit in results))
        return {"translations": out, "latency_ms": round(elapsed * 1000, 2)}

    @app.get("/health")
    def health(response: Response):
        if ready():
            return {"status": "ok"}
        response.status_code = 503
        return {"status": "model unavailable"}

    @app.get("/version")
    def version():
        return {"service": SERVICE_VERSION, "model": model_version()}

    @app.get("/metrics")
    def metrics_endpoint():
        return Response(metrics.render(), media_type="text/plain; version=0.0.4")

    return app
