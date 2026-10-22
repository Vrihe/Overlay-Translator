"""
tests/test_training_pipeline.py — YAML pipeline configs and run provenance of the NLLB fine-tune.

Covers:
  • training/train_config.py: validation, {reference} expansion, the shipped
    configs/train/*.yaml, the dataset hash and the git commit fallback;
  • training/pipeline.py: the commands of every stage, --name and the overwrite guards;
  • training/finetune_lora.py: config values become defaults, the command line wins.
Nothing runs a model: commands are only planned (--dry-run), and torch is never imported.
"""

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
_TRAINING_DIR = _ROOT / "training"

with mock.patch.object(sys, "path", [str(_TRAINING_DIR), *sys.path]):
    train_config = importlib.import_module("train_config")
    pipeline = importlib.import_module("pipeline")
    finetune_lora = importlib.import_module("finetune_lora")


def _raw(**overrides) -> dict:
    raw = {
        "name": "run-a",
        "base_model": "models/base",
        "data": {"dir": "data/{name}", "steps": ["training/build_dataset.py --out-dir data/{name}"]},
        "train": {"seed": 1, "lora_r": 8},
        "merge": {"out": "models/{name}-merged"},
        "convert": {"out": "models/{name}-int8"},
        "eval": {"test": ["data/t.jsonl"], "systems": {"{name}": "ct2:{convert.out}"}},
    }
    raw.update(overrides)
    return raw


class TestParseConfig(unittest.TestCase):
    def test_expands_name_and_section_references(self):
        cfg = train_config.parse_config(_raw())
        self.assertEqual(cfg["data"]["dir"], "data/run-a")
        self.assertEqual(cfg["data"]["steps"], ["training/build_dataset.py --out-dir data/run-a"])
        self.assertEqual(cfg["merge"]["out"], "models/run-a-merged")
        self.assertEqual(cfg["eval"]["systems"], {"run-a": "ct2:models/run-a-int8"})

    def test_name_override_reaches_every_derived_path(self):
        cfg = train_config.parse_config(_raw(), name="repro")
        self.assertEqual(cfg["name"], "repro")
        self.assertEqual(cfg["convert"]["out"], "models/repro-int8")
        self.assertEqual(cfg["eval"]["systems"], {"repro": "ct2:models/repro-int8"})

    def test_rejects_unknown_and_missing_keys(self):
        with self.assertRaises(train_config.ConfigError):
            train_config.parse_config(_raw(extra=1))
        with self.assertRaises(train_config.ConfigError):
            train_config.parse_config(_raw(train={"learning_rate": 1e-4}))  # the key is `lr`
        raw = _raw()
        del raw["train"]
        with self.assertRaises(train_config.ConfigError):
            train_config.parse_config(raw)
        with self.assertRaises(train_config.ConfigError):
            train_config.parse_config(_raw(data={"steps": []}))
        with self.assertRaises(train_config.ConfigError):
            train_config.parse_config(["not", "a", "mapping"])

    def test_base_model_env_override(self):
        with mock.patch.dict(os.environ, {"NLLB_BASE_MODEL_DIR": "D:/elsewhere/nllb"}):
            self.assertEqual(train_config.parse_config(_raw())["base_model"], "D:/elsewhere/nllb")
        with mock.patch.dict(os.environ, {"NLLB_BASE_MODEL_DIR": ""}):
            self.assertEqual(train_config.parse_config(_raw())["base_model"], "models/base")

    def test_does_not_mutate_the_input(self):
        raw = _raw()
        train_config.parse_config(raw, name="other")
        self.assertEqual(raw["name"], "run-a")
        self.assertEqual(raw["data"]["dir"], "data/{name}")


class TestShippedConfigs(unittest.TestCase):
    """configs/train/*.yaml must load and keep the hyperparameters of the published runs."""

    def test_v1_matches_the_published_run(self):
        cfg = train_config.load_config(_ROOT / "configs" / "train" / "v1.yaml")
        self.assertEqual(cfg["name"], "v1-final-b")
        self.assertEqual(cfg["data"]["dir"], "data/processed_final")
        train = cfg["train"]
        self.assertEqual((train["lora_r"], train["lora_alpha"], train["epochs"]), (16, 32, 5))
        self.assertEqual((train["lr"], train["seed"], train["eval_steps"]), (2e-4, 42, 100))
        self.assertEqual(len(cfg["config_sha256"]), 64)

    def test_v2_matches_the_published_run(self):
        cfg = train_config.load_config(_ROOT / "configs" / "train" / "v2.yaml")
        self.assertEqual(cfg["name"], "v2b-game")
        self.assertEqual(cfg["data"]["dir"], "data/processed_v2b")
        train = cfg["train"]
        self.assertEqual((train["lora_r"], train["lora_alpha"], train["epochs"]), (32, 64, 5))
        self.assertEqual((train["eval_steps"], train["group_by_length"]), (200, True))
        self.assertIn("data/processed_v2/test_v2.jsonl", cfg["eval"]["test"])

    def test_every_train_key_is_a_finetune_option(self):
        dests = {a.dest for a in finetune_lora.build_parser()._actions}
        self.assertLessEqual(train_config.TRAIN_KEYS, dests)


class TestProvenance(unittest.TestCase):
    def test_dataset_hash_tracks_content_and_split_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "train.jsonl").write_text('{"src": "a"}\n', encoding="utf-8")
            (d / "val.jsonl").write_text('{"src": "b"}\n', encoding="utf-8")
            first = train_config.dataset_hash(d)
            self.assertEqual(first, train_config.dataset_hash(d))
            (d / "val.jsonl").write_text('{"src": "c"}\n', encoding="utf-8")
            self.assertNotEqual(first, train_config.dataset_hash(d))
            # moving a line from train to val changes the hash even if the bytes concatenate equally
            (d / "train.jsonl").write_text("", encoding="utf-8")
            (d / "val.jsonl").write_text('{"src": "a"}\n{"src": "b"}\n', encoding="utf-8")
            moved = train_config.dataset_hash(d)
            (d / "train.jsonl").write_text('{"src": "a"}\n', encoding="utf-8")
            (d / "val.jsonl").write_text('{"src": "b"}\n', encoding="utf-8")
            self.assertNotEqual(moved, train_config.dataset_hash(d))

    def test_git_state_falls_back_to_the_environment(self):
        with (
            mock.patch.object(train_config.subprocess, "run", side_effect=FileNotFoundError),
            mock.patch.dict(os.environ, {"OVERLAY_GIT_SHA": "abc123"}),
        ):
            self.assertEqual(train_config.git_state(), {"sha": "abc123", "dirty": None})

    def test_git_state_reads_the_commit(self):
        def fake_run(cmd, **kwargs):
            out = "deadbeef\n" if cmd[1] == "rev-parse" else " M training/pipeline.py\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=out)

        with mock.patch.object(train_config.subprocess, "run", side_effect=fake_run):
            self.assertEqual(train_config.git_state(), {"sha": "deadbeef", "dirty": True})

    def test_library_versions_marks_missing_packages(self):
        versions = train_config.library_versions(("surely-not-an-installed-package",))
        self.assertEqual(versions, {"surely-not-an-installed-package": None})


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.cfg = train_config.parse_config(_raw())
        self.cfg["config_path"] = "configs/train/x.yaml"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patcher = mock.patch.object(pipeline, "CHECKPOINTS", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_data_steps_run_with_the_current_interpreter(self):
        (cmd,) = pipeline.stage_commands(self.cfg, "data")
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(Path(cmd[1]), _ROOT / "training" / "build_dataset.py")
        self.assertEqual(cmd[2:], ["--out-dir", "data/run-a"])

    def test_train_passes_the_config_and_run_name(self):
        (cmd,) = pipeline.stage_commands(self.cfg, "train")
        self.assertIn("finetune_lora.py", cmd[1])
        self.assertEqual(cmd[2:], ["--config", "configs/train/x.yaml", "--run-name", "run-a"])

    def test_train_refuses_to_overwrite_a_finished_run(self):
        (self.tmp / "run-a" / "adapter").mkdir(parents=True)
        with self.assertRaises(pipeline.StageError):
            pipeline.stage_commands(self.cfg, "train")
        self.assertEqual(len(pipeline.stage_commands(self.cfg, "train", force=True)), 1)

    def test_merge_and_convert_chain_their_outputs(self):
        (merge,) = pipeline.stage_commands(self.cfg, "merge")
        (convert,) = pipeline.stage_commands(self.cfg, "convert")
        merged = str(train_config.resolve("models/run-a-merged"))
        self.assertEqual(merge[merge.index("--out") + 1], merged)
        self.assertEqual(merge[merge.index("--adapter") + 1], str(self.tmp / "run-a" / "adapter"))
        self.assertEqual(convert[convert.index("--model") + 1], merged)
        self.assertEqual(convert[convert.index("--quantization") + 1], "int8")
        self.assertIn("sentencepiece.bpe.model", convert)

    def test_eval_runs_once_per_test_file(self):
        self.cfg["eval"]["test"] = ["data/a/test_v1.jsonl", "data/a/test_v2.jsonl"]
        cmds = pipeline.stage_commands(self.cfg, "eval")
        self.assertEqual(len(cmds), 2)
        out_dirs = [Path(c[c.index("--out-dir") + 1]).name for c in cmds]
        self.assertEqual(out_dirs, ["test_v1", "test_v2"])
        self.assertTrue(all(c[-1] == "run-a=ct2:models/run-a-int8" for c in cmds))

    def test_clean_accepts_only_files_under_data(self):
        self.cfg["data"]["clean"] = ["data/interim/x.jsonl"]
        self.assertEqual(pipeline.clean_paths(self.cfg), [_ROOT / "data" / "interim" / "x.jsonl"])
        for bad in ("translate/glossary/game_en.json", "data/../config.py", "data"):
            self.cfg["data"]["clean"] = [bad]
            with self.assertRaises(pipeline.StageError, msg=bad):
                pipeline.clean_paths(self.cfg)

    def test_shipped_configs_clean_the_resumable_translations(self):
        for version, path in (("v1", "abbr_translations.jsonl"), ("v2", "v2/game_translations.jsonl")):
            cfg = train_config.load_config(_ROOT / "configs" / "train" / f"{version}.yaml")
            self.assertEqual(pipeline.clean_paths(cfg), [_ROOT / "data" / "interim" / Path(path)])

    def test_dry_run_deletes_nothing(self):
        root = self.tmp.resolve()
        victim = root / "data" / "keep.jsonl"
        victim.parent.mkdir()
        victim.write_text("x\n", encoding="utf-8")
        cfg_file = root / "c.yaml"
        cfg_file.write_text(
            f"name: t\nbase_model: m\ndata: {{dir: d, clean: ['{victim.as_posix()}']}}\ntrain: {{}}\n",
            encoding="utf-8",
        )
        with mock.patch.object(pipeline, "PROJECT_ROOT", root), mock.patch("builtins.print"):
            self.assertEqual(pipeline.main(["data", "--config", str(cfg_file), "--dry-run"]), 0)
            self.assertTrue(victim.exists())
            self.assertEqual(pipeline.main(["data", "--config", str(cfg_file)]), 0)
        self.assertFalse(victim.exists())

    def test_missing_section_is_an_error(self):
        del self.cfg["merge"]
        with self.assertRaises(pipeline.StageError):
            pipeline.stage_commands(self.cfg, "merge")

    def test_dry_run_prints_without_running(self):
        with (
            mock.patch.object(pipeline.subprocess, "run") as run,
            mock.patch("builtins.print"),
        ):
            code = pipeline.main(
                ["all", "--config", str(_ROOT / "configs" / "train" / "v2.yaml"), "--name", "t-dry", "--dry-run"]
            )
        self.assertEqual(code, 0)
        run.assert_not_called()

    def test_bad_config_returns_an_error_code(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("name: x\n")
        self.addCleanup(os.unlink, f.name)
        with mock.patch("builtins.print"):
            self.assertEqual(pipeline.main(["train", "--config", f.name, "--dry-run"]), 2)


class TestDvcPipeline(unittest.TestCase):
    """dvc.yaml repeats the config commands; they must not drift apart."""

    @classmethod
    def setUpClass(cls):
        import yaml

        cls.stages = yaml.safe_load((_ROOT / "dvc.yaml").read_text(encoding="utf-8"))["stages"]
        cls.commands = []
        for stage in cls.stages.values():
            cmd = stage["cmd"]
            cls.commands += cmd if isinstance(cmd, list) else [cmd]

    def test_every_config_data_step_is_a_dvc_command(self):
        for version in ("v1", "v2"):
            cfg = train_config.load_config(_ROOT / "configs" / "train" / f"{version}.yaml")
            for step in cfg["data"]["steps"]:
                self.assertIn(f"python {step}", self.commands, f"{version}: {step}")

    def test_model_stages_go_through_the_pipeline_with_repro_names(self):
        for version in ("v1", "v2"):
            for stage in ("train", "merge", "convert", "eval"):
                cmd = self.stages[f"{version}_{stage}"]["cmd"]
                self.assertEqual(
                    cmd,
                    f"python training/pipeline.py {stage} --config configs/train/{version}.yaml --name {version}-repro",
                )

    def test_screen_text_export_is_never_tracked(self):
        text = (_ROOT / "dvc.yaml").read_text(encoding="utf-8")
        for stage in self.stages.values():
            for out in stage.get("outs", []):
                path = next(iter(out)) if isinstance(out, dict) else out
                self.assertNotIn("history", path)
        self.assertFalse((_ROOT / "data" / "history_pairs.jsonl.dvc").exists())
        self.assertIn("history_pairs.jsonl is exported screen text", text)


class TestFinetuneArgs(unittest.TestCase):
    def test_config_supplies_defaults(self):
        args, cfg = finetune_lora.parse_args(["--config", str(_ROOT / "configs" / "train" / "v2.yaml")])
        self.assertEqual(args.run_name, "v2b-game")
        self.assertEqual(args.data_dir, _ROOT / "data" / "processed_v2b")
        self.assertEqual((args.lora_r, args.lora_alpha, args.group_by_length), (32, 64, True))
        self.assertEqual(args.precision, "bf16")
        self.assertEqual(cfg["name"], "v2b-game")

    def test_command_line_wins_over_the_config(self):
        args, _ = finetune_lora.parse_args(
            ["--config", str(_ROOT / "configs" / "train" / "v2.yaml"), "--lr", "1e-4", "--precision", "fp16"]
        )
        self.assertEqual((args.lr, args.precision, args.lora_r), (1e-4, "fp16", 32))

    def test_without_config_the_old_defaults_stay(self):
        args, cfg = finetune_lora.parse_args([])
        self.assertIsNone(cfg)
        self.assertEqual((args.run_name, args.lora_r, args.precision), ("v1-abbr", 16, "bf16"))


if __name__ == "__main__":
    unittest.main()
