"""
tests/test_google_client.py — the paid Cloud Translation API v2 path: the key travels
in a header (never the URL) and the response is parsed into (detected, translated).

urlopen is mocked: no network.
"""

import io
import json
import unittest
from unittest import mock

from translate import google_client


def _response(payload: dict):
    resp = io.BytesIO(json.dumps(payload).encode("utf-8"))
    cm = mock.MagicMock()
    cm.__enter__.return_value = resp
    return cm


class TestOfficialApi(unittest.TestCase):
    def test_key_is_sent_in_a_header_not_the_url(self):
        payload = {"data": {"translations": [{"translatedText": "привет", "detectedSourceLanguage": "EN"}]}}
        with mock.patch.object(google_client.urllib.request, "urlopen", return_value=_response(payload)) as urlopen:
            result = google_client._translate_official("hello", "ru", None, "secret-key")
        req = urlopen.call_args.args[0]
        self.assertNotIn("secret-key", req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"), "secret-key")
        self.assertEqual(json.loads(req.data)["target"], "ru")
        self.assertEqual(result, ("en", "привет"))

    def test_malformed_key_is_a_clear_error_before_any_request(self):
        with mock.patch.object(google_client.urllib.request, "urlopen") as urlopen:
            for bad in ("key with space", "ключ"):
                with self.assertRaises(RuntimeError):
                    google_client._translate_official("hello", "ru", None, bad)
        urlopen.assert_not_called()

    def test_empty_response_is_an_error(self):
        with mock.patch.object(google_client.urllib.request, "urlopen", return_value=_response({"data": {}})):
            with self.assertRaises(RuntimeError):
                google_client._translate_official("hello", "ru", "en", "k")


if __name__ == "__main__":
    unittest.main()
