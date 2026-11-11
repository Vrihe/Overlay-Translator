"""
service/metrics.py — a tiny Prometheus text-format registry for the inference service.

Standard library only: counters, one latency histogram and a batch-size histogram are all the
service needs, so ``prometheus_client`` is not a dependency. Thread-safe.
"""

from __future__ import annotations

import threading

LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
BATCH_BUCKETS = (1, 2, 4, 8, 16, 32)


class _Histogram:
    def __init__(self, name: str, help_text: str, buckets: tuple[float, ...]):
        self.name, self.help, self.buckets = name, help_text, buckets
        self.counts = [0] * len(buckets)
        self.total = 0
        self.sum = 0.0

    def observe(self, value: float) -> None:
        self.total += 1
        self.sum += value
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self.counts[i] += 1

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for bound, count in zip(self.buckets, self.counts):
            lines.append(f'{self.name}_bucket{{le="{bound}"}} {count}')
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {self.total}')
        lines.append(f"{self.name}_sum {self.sum}")
        lines.append(f"{self.name}_count {self.total}")
        return lines


class Metrics:
    """Request counters, translation latency and batch size, rendered for ``GET /metrics``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.errors = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.latency = _Histogram("overlay_translate_latency_seconds", "Translation latency.", LATENCY_BUCKETS)
        self.batch = _Histogram("overlay_translate_batch_size", "Texts per request.", BATCH_BUCKETS)

    def record(self, *, latency: float, batch_size: int, error: bool = False, hits: int = 0) -> None:
        with self._lock:
            self.requests += 1
            if error:
                self.errors += 1
            else:
                self.latency.observe(latency)
            self.batch.observe(batch_size)
            if not error:
                self.cache_hits += hits
                self.cache_misses += batch_size - hits

    def render(self) -> str:
        with self._lock:
            lines = [
                "# HELP overlay_requests_total Translate requests.",
                "# TYPE overlay_requests_total counter",
                f"overlay_requests_total {self.requests}",
                "# HELP overlay_errors_total Failed translate requests.",
                "# TYPE overlay_errors_total counter",
                f"overlay_errors_total {self.errors}",
                "# HELP overlay_cache_total Cache lookups by result.",
                "# TYPE overlay_cache_total counter",
                f'overlay_cache_total{{result="hit"}} {self.cache_hits}',
                f'overlay_cache_total{{result="miss"}} {self.cache_misses}',
                *self.latency.render(),
                *self.batch.render(),
            ]
        return "\n".join(lines) + "\n"
