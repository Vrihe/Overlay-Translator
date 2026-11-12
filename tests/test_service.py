"""
tests/test_service.py — the local inference service (service/app.py, service/metrics.py).

The translate function is a stub: no model, no GPU, no network. The HTTP tests need the optional
``requirements-service.txt`` (fastapi + httpx) and are skipped without it; the metrics registry is
plain Python and always runs.
"""

import importlib.util
import unittest

from service.metrics import Metrics

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("httpx") is not None


class TestMetrics(unittest.TestCase):
    def test_render_counts_requests_errors_cache_and_buckets(self):
        m = Metrics()
        m.record(latency=0.2, batch_size=3, hits=1)
        m.record(latency=0.0, batch_size=1, error=True)
        text = m.render()
        self.assertIn("overlay_requests_total 2", text)
        self.assertIn("overlay_errors_total 1", text)
        self.assertIn('overlay_cache_total{result="hit"} 1', text)
        self.assertIn('overlay_cache_total{result="miss"} 2', text)
        self.assertIn('overlay_translate_latency_seconds_bucket{le="0.25"} 1', text)
        self.assertIn('overlay_translate_latency_seconds_bucket{le="0.1"} 0', text)
        self.assertIn("overlay_translate_latency_seconds_count 1", text)  # the failed call is not a latency sample
        self.assertIn('overlay_translate_batch_size_bucket{le="4"} 2', text)


@unittest.skipUnless(_HAS_FASTAPI, "fastapi / httpx are not installed (requirements-service.txt)")
class TestApp(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from service.app import create_app

        self.calls = []
        self.ready = True

        def fake_translate(text, target, source):
            self.calls.append((text, target, source))
            if text == "boom":
                raise RuntimeError("secret screen text must not leak")
            return f"[{target}] {text}"

        self.metrics = Metrics()
        app = create_app(
            translate=fake_translate,
            ready=lambda: self.ready,
            model_version=lambda: "v-test",
            metrics=self.metrics,
        )
        self.client = TestClient(app)

    def test_translate_batch_and_cache(self):
        body = {"texts": ["a", "b", "a"], "target_lang": "ru"}
        r = self.client.post("/translate", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["translations"], ["[ru] a", "[ru] b", "[ru] a"])
        self.assertEqual(len(self.calls), 2)  # the repeated "a" came from the cache
        self.assertIn('overlay_cache_total{result="hit"} 1', self.client.get("/metrics").text)

    def test_source_lang_reaches_the_backend(self):
        self.client.post("/translate", json={"texts": ["x"], "target_lang": "ru", "source_lang": "en"})
        self.assertEqual(self.calls, [("x", "ru", "en")])

    def test_validation_errors(self):
        self.assertEqual(self.client.post("/translate", json={"texts": [], "target_lang": "ru"}).status_code, 422)
        self.assertEqual(self.client.post("/translate", json={"texts": ["x"]}).status_code, 422)
        big = {"texts": ["x" * 5001], "target_lang": "ru"}
        self.assertEqual(self.client.post("/translate", json=big).status_code, 413)

    def test_backend_error_is_502_without_leaking_text(self):
        r = self.client.post("/translate", json={"texts": ["boom"], "target_lang": "ru"})
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("secret", r.text)
        self.assertIn("overlay_errors_total 1", self.client.get("/metrics").text)

    def test_health_and_version(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.ready = False
        self.assertEqual(self.client.get("/health").status_code, 503)
        self.assertEqual(self.client.get("/version").json()["model"], "v-test")

    def test_metrics_never_contain_request_text(self):
        self.client.post("/translate", json={"texts": ["very private line"], "target_lang": "ru"})
        self.assertNotIn("private", self.client.get("/metrics").text)


if __name__ == "__main__":
    unittest.main()
