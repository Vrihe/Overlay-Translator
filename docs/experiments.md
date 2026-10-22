# Reproducing experiments

Every published model version can be rebuilt and re-scored from the scripts in `training/`. Set up
the training environment first ([Training → Environment](training.md#environment)). Commands are
for Windows `cmd`; `.venv` is the app venv, `.venv-train` the training one.

## Results so far

Scores from `training/evaluate.py` (sacrebleu chrF, beam 4, no sampling). int8 is the CTranslate2
build scored on the CPU, as the app runs it.

| Version | General chrF (FLORES) | Keep rate, v1 terms | Translate-mode chrF, v1 | Keep rate, v2 glossary | Report |
|---|---:|---:|---:|---:|---|
| `v0-base` | 55.65 | 46.9 % | 41.74 | 39.9 % | [Baseline](baseline_eval.md) |
| `v1-abbr` int8 | 57.41 | 92.8 % | 52.31 | 76.4 % | [v1 evaluation](finetune_v1_eval.md) |
| `v2-game` int8 | 57.78 | 96.4 % | 53.65 | 94.4 % | [v2 results](finetune_v2_process.md#5-results) |

Known weak spot: v2 leaves more ordinary words untranslated than v0 (the "plain chrF" criterion
of v2 failed; see the v2 report). The current test sets are built from generated phrases and
FLORES, not from real chat; a hand-checked test set is planned in the
[roadmap](https://github.com/Vrihe/Overlay-Translator/blob/main/ROADMAP.md) (stage 4).

## One command

The commands below are also captured as configs, so a version can be rebuilt with one command
into fresh directories (see [Training → One command per stage](training.md#one-command-per-stage)):

```bat
.venv-train\Scripts\python training\pipeline.py all --config configs\train\v1.yaml --name v1-repro
.venv-train\Scripts\python training\pipeline.py all --config configs\train\v2.yaml --name v2-repro
```

v2 builds on the v1 data, so run the v1 `data` stage first. The published v2 scores come from
`data\processed_v2\test_*.jsonl`, an earlier build of the v2 splits, while the model was
trained on `data\processed_v2b`. The two `test_v2.jsonl` files differ, and `build_dataset_v2.py`
now writes only the v2b version. `configs/train/v2.yaml` therefore scores on the
`processed_v2` files, which are kept as a fixed artifact so the numbers stay comparable.

## v0-base: the plain model

```bat
python scripts\download_model.py --revision v0-base --dest models\nllb-v0-base
```

`v0-base` is the int8 conversion of the original checkpoint, used as the reference point by both
fine-tunes. `scripts/baseline_eval_nllb.py` scores it on exported history; that early baseline used
only 6 pairs and is kept for the record, not for comparison.

## v1-abbr: abbreviations

```bat
:: data
python training\prepare_abbreviations.py
python training\abbr_phrases.py
.venv-train\Scripts\python training\translate_phrases.py
.venv-train\Scripts\python training\translate_phrases.py --repair-keep
.venv-train\Scripts\python training\build_dataset.py --split-by phrase --out-dir data\processed_final

:: train (trial, then full)
.venv-train\Scripts\python training\finetune_lora.py --max-steps 50 --run-name trial --data-dir data\processed_final
.venv-train\Scripts\python training\finetune_lora.py --epochs 5 --run-name v1-final-b --data-dir data\processed_final

:: evaluate
.venv-train\Scripts\python training\evaluate.py --test data\processed_final\test.jsonl --out-dir checkpoints\eval_final ^
    v0-base=ct2:models\nllb-v0-base ^
    v1-final-b=lora:models\nllb-200-distilled-600M+checkpoints\v1-final-b\adapter

:: merge, convert, smoke test
.venv-train\Scripts\python training\merge_lora.py --adapter checkpoints\v1-final-b\adapter --out models\nllb-finetuned-v1-merged
.venv-train\Scripts\ct2-transformers-converter --model models\nllb-finetuned-v1-merged ^
    --output_dir models\nllb-v1-abbr-ct2-int8 --quantization int8 ^
    --copy_files tokenizer.json tokenizer_config.json special_tokens_map.json sentencepiece.bpe.model generation_config.json
.venv\Scripts\python scripts\test_nllb_translation.py --model models\nllb-v1-abbr-ct2-int8
```

The held-out experiment (16 abbreviations never seen in training) uses
`build_dataset.py --split-by abbr` (the default) with `--out-dir data\processed`.

## v2-game: game-chat glossary

```bat
.venv\Scripts\python training\game_abbreviations.py
.venv-train\Scripts\python training\translate_phrases.py --input data\interim\v2\game_phrases.jsonl --output data\interim\v2\game_translations.jsonl --batch-size 32
.venv-train\Scripts\python training\translate_phrases.py --input data\interim\v2\game_phrases.jsonl --output data\interim\v2\game_translations.jsonl --batch-size 32 --repair-keep
.venv-train\Scripts\python training\build_dataset_v2.py --out-dir data\processed_v2b
.venv-train\Scripts\python training\finetune_lora.py --data-dir data\processed_v2b --run-name v2b-game --epochs 5 ^
    --eval-steps 200 --batch-size 4 --grad-accum 4 --lora-r 32 --lora-alpha 64 --group-by-length
.venv-train\Scripts\python training\merge_lora.py --adapter checkpoints\v2b-game\adapter --out models\nllb-finetuned-v2-merged
.venv-train\Scripts\ct2-transformers-converter --model models\nllb-finetuned-v2-merged --output_dir models\nllb-v2-game-ct2-int8 ^
    --quantization int8 --copy_files tokenizer.json tokenizer_config.json special_tokens_map.json sentencepiece.bpe.model generation_config.json
.venv-train\Scripts\python training\evaluate.py --test data\processed_v2\test_v2.jsonl --out-dir checkpoints\eval_v2 ^
    v0-base=ct2:models\nllb-v0-base v2-game-int8=ct2:models\nllb-v2-game-ct2-int8
```

`game_abbreviations.py` needs `wordfreq` in the app venv.

## How close a rerun gets

Translation and training are deterministic for a fixed seed (42) on the same GPU and library
versions. bf16 kernels can differ slightly on other hardware, so expect chrF within a few tenths
of a point, not identical numbers.

### Reproduction from the configs (October 2026)

Both versions were rebuilt from scratch with `training/pipeline.py all` (runs `v1-repro` and
`v2-repro`) on the same RTX 3060 Ti and library versions as the published runs. int8 builds
were scored on the CPU:

| Run | Test set | chrF abbr | chrF general | Translate mode | Keep rate |
|---|---|---:|---:|---:|---:|
| `v1-abbr` published | `test_v1` | 58.46 | 57.41 | 52.31 | 92.8 % |
| `v1-repro` | `test_v1` | 58.46 | 57.41 | 52.31 | 92.8 % |
| `v2-game` published | `test_v1` | 59.54 | 57.78 | 53.65 | 96.4 % |
| `v2-repro` | `test_v1` | 57.67 | 57.77 | 50.83 | 94.0 % |
| `v2-game` published | `test_v2` | 60.22 | — | 53.31 | 94.4 % |
| `v2-repro` | `test_v2` | 59.18 | — | 52.42 | 92.2 % |

- **v1 is reproduced exactly.** The data splits are byte-identical, and the training curve,
  best checkpoint (step 800, eval loss 1.0841) and every score match.
- **v2 differs by 1–3 points.** The cause is the data, not the training code. The published
  `game_translations.jsonl` was built over several resumed runs of `translate_phrases.py`
  while the phrase list was still changing: it held 7,365 stale rows, and 31 of the current
  rows were translated differently, presumably because batches were composed differently.
  Through the splits, 30 training targets and 1 `test_v2` target differ. The training losses
  match until step 90, the first batch with a changed target, then drift slightly.
- **The best-checkpoint choice amplifies small differences.** Validation loss of the two v2
  runs stays within ±0.007 at every step, but the published run's minimum was at step 6600
  (0.9166) and the rerun's at step 4600 (0.9205). Checkpoints that far apart differ by a few
  points of keep rate. Comparing versions on one seed is therefore fragile; stage 4 of the
  roadmap adds several seeds.
- **The data stage is now deterministic.** `data.clean` deletes the resumable outputs first,
  and a second translation run produced a byte-identical file. `game_abbreviations.py`
  reproduces `translate/glossary/game_en.json` exactly (it now writes the trailing newline
  that the committed file has).

The published v2 data is kept in `data/processed_v2` (test files, tracked by DVC). The new
`data/processed_v2b` and the rerun's outputs are recorded in `dvc.lock`. Run configurations and logs are written to
`checkpoints/<run>/run_config.json` and `checkpoints/<run>/`. Runs started from a config also
record the git commit, library versions and the dataset hash there. The data of every version
is versioned with DVC ([Training → Data versioning](training.md#data-versioning-dvc)).
