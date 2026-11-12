"""
tests/test_tracking.py — optional MLflow / DagsHub logging (training/tracking.py).

``mlflow`` is replaced by a mock: no network, no real tracking store.
"""

import importlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_TRAINING_DIR = Path(__file__).resolve().parent.parent / "training"
with mock.patch.object(sys, "path", [str(_TRAINING_DIR), *sys.path]):
    tracking = importlib.import_module("tracking")


def _fake_mlflow():
    mlflow = mock.MagicMock()
    mlflow.start_run.return_value.__enter__.return_value.info.run_id = "run-1"
    return mlflow


class HelpersTests(unittest.TestCase):
    def test_flatten_metrics_keeps_numbers_only(self):
        flat = tracking.flatten_metrics(
            {"chrf": 51.2, "by": {"ru": 40, "x": None}, "name": "text", "ok": True, "xs": [1, 2]}
        )
        self.assertEqual(flat, {"chrf": 51.2, "by.ru": 40.0})

    def test_metric_key_replaces_forbidden_characters(self):
        self.assertEqual(tracking.metric_key("chrf[abbr]"), "chrf_abbr_")

    def test_clean_params_strips_directories_and_none(self):
        params = tracking.clean_params(
            {
                "data_dir": r"C:\Users\someone\data\processed_v2",
                "model": Path("/home/x/models/nllb"),
                "lr": 1e-4,
                "n": None,
            }
        )
        self.assertEqual(params["data_dir"], "processed_v2")
        self.assertEqual(params["model"], "nllb")
        self.assertEqual(params["lr"], "0.0001")
        self.assertNotIn("n", params)

    def test_clean_params_truncates_long_values(self):
        self.assertEqual(len(tracking.clean_params({"k": "x" * 2000})["k"]), 500)


class BackendTests(unittest.TestCase):
    def test_disabled_by_env(self):
        with mock.patch.dict(os.environ, {"OVERLAY_TRACKING": "off"}):
            self.assertFalse(tracking.enabled())
            self.assertIsNone(tracking.log_run("e", "r", metrics={"a": 1}))

    def test_uri_from_env_or_local_default(self):
        with mock.patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "https://dagshub.com/u/r.mlflow"}):
            self.assertEqual(tracking.tracking_uri(), "https://dagshub.com/u/r.mlflow")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(tracking.tracking_uri(), tracking.LOCAL_URI)
            self.assertTrue(tracking.LOCAL_URI.startswith("sqlite:///"))


class LogRunTests(unittest.TestCase):
    def test_logs_params_tags_metrics_history(self):
        fake = _fake_mlflow()
        env = {"MLFLOW_TRACKING_URI": "https://dagshub.com/u/r.mlflow"}
        with mock.patch.dict(os.environ, env), mock.patch.dict(sys.modules, {"mlflow": fake}):
            run_id = tracking.log_run(
                "finetune",
                "v2-game",
                params={"seed": 42, "data_dir": Path("/x/processed_v2")},
                metrics={"eval_loss": 0.5, "by": {"ru": 3}},
                tags={"git_sha": "abc", "none": None},
                history=[(10, {"loss": 1.0}), (20, {"loss": 0.8})],
            )
        self.assertEqual(run_id, "run-1")
        fake.set_tracking_uri.assert_called_once_with("https://dagshub.com/u/r.mlflow")
        fake.set_experiment.assert_called_once_with("finetune")
        fake.start_run.assert_called_once_with(run_name="v2-game")
        fake.log_params.assert_called_once_with({"seed": "42", "data_dir": "processed_v2"})
        fake.set_tags.assert_called_once_with({"git_sha": "abc"})
        self.assertEqual(fake.log_metrics.call_args_list[0].args[0], {"eval_loss": 0.5, "by.ru": 3.0})
        self.assertEqual(fake.log_metrics.call_args_list[1].kwargs, {"step": 10})
        self.assertEqual(fake.log_metrics.call_args_list[2].kwargs, {"step": 20})

    def test_artifact_logged_only_if_file_exists(self):
        fake = _fake_mlflow()
        here = Path(__file__)
        with (
            mock.patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "http://x"}),
            mock.patch.dict(sys.modules, {"mlflow": fake}),
        ):
            tracking.log_run("e", "r", artifacts=[here, here.with_name("no_such_file.json")])
        fake.log_artifact.assert_called_once_with(str(here))

    def test_failure_is_swallowed(self):
        fake = _fake_mlflow()
        fake.start_run.side_effect = ConnectionError("offline")
        with (
            mock.patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "http://x"}),
            mock.patch.dict(sys.modules, {"mlflow": fake}),
        ):
            self.assertIsNone(tracking.log_run("e", "r", metrics={"a": 1}))

    def test_missing_mlflow_is_swallowed(self):
        with (
            mock.patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "http://x"}),
            mock.patch.dict(sys.modules, {"mlflow": None}),
        ):
            self.assertIsNone(tracking.log_run("e", "r", metrics={"a": 1}))


if __name__ == "__main__":
    unittest.main()
