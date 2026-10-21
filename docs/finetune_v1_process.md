# Fine-tune v1 (abbreviations): how it was made and why

This document records how the local NLLB model was fine-tuned on English game-chat
abbreviations, from raw data to the published `v1-abbr` revision, and **why** each choice was
made. Results and metrics are in [finetune_v1_eval.md](finetune_v1_eval.md); the public model card
is on Hugging Face at `Alhite/overlay-translator-nllb-int8@v1-abbr`.

| | |
|---|---|
| Base model | `facebook/nllb-200-distilled-600M`, fp32 (`models/nllb-200-distilled-600M`) |
| Previous release | `v0-base`: plain CTranslate2 int8 conversion, no fine-tuning |
| Goal | Translate English chat abbreviations correctly: expand the ones with a meaning (`brb`, `ty`, `afaik`), keep gaming terms as they are (`gg`, `pvp`, `wtb`) |
| Directions | en → de, fr, es, ru, uk, be, pl, cs, hu |
| Hardware | RTX 3060 Ti 8 GB, Windows 11 |
| Result | `v1-abbr`: keep terms preserved 46.9 % → 92.8 %, translate-mode chrF 41.7 → 52.3, general chrF 55.7 → 57.4 (int8, held-out test) |
| Published | HF commit `2d95429f`, tag `v1-abbr`; the app config still points to `v0-base` |

---

## Pipeline at a glance

```
sms.csv (willwade/txt-sms-abbreviations)
  │  training/prepare_abbreviations.py    filter + rank
  ▼
data/interim/abbreviations_ranked.csv     ── manual selection, keep / translate ──┐
                                                                                   ▼
training/abbr_phrases.txt (hand-written)  ── training/abbr_phrases.py ──► data/interim/abbr_phrases.jsonl
  │  training/translate_phrases.py [--repair-keep]   NLLB fp32 translates the FULL phrases
  ▼
data/interim/abbr_translations.jsonl  +  FLORES-200 dev (data/raw/flores200)
  │  training/build_dataset.py [--split-by abbr|phrase]
  ▼
data/processed/ (held-out experiment)   data/processed_final/ (release)
  │  training/finetune_lora.py           LoRA, bf16
  ▼
checkpoints/<run>/adapter
  │  training/evaluate.py                chrF, keep rate, bootstrap CI
  │  training/merge_lora.py              merge_and_unload
  ▼
models/nllb-finetuned-v1-merged  ── ct2-transformers-converter --quantization int8 ──► models/nllb-v1-abbr-ct2-int8
```

All of `data/`, `models/`, `checkpoints/`, `.venv-train/` and `.train-cache/` are git-ignored.
Only the scripts, `training/abbr_phrases.txt` and the docs are tracked.

---

## 1. Abbreviation list

**What.** `willwade/txt-sms-abbreviations` (`sms.csv`, 1538 rows, Apache-2.0) was filtered by
`training/prepare_abbreviations.py`: rows flagged `IsWord` were dropped (e.g. `BAD`, `CAT`),
as were rows without letters (`143`, `.02`) and case-insensitive duplicates. 1339 abbreviations
remained. They were ranked by the Zipf frequency of the abbreviation in `wordfreq`, a
selection was made by hand for game chat, and 28 gaming abbreviations missing from the dataset
were added (`lfg`, `wts`, `wtb`, `dps`, `aggro`, `kite`, `ilvl`, `oom`, `rez`, `lf1m` ...).
Final list: **102 abbreviations, 38 keep + 64 translate**.

**Why these choices.**

- *`IsWord` filter.* An abbreviation that is also a normal word (`cat`, `bad`) cannot be told
  apart from the word by the model. Training on it would teach the model to rewrite ordinary
  English.
- *Digit-only filter.* The dataset card itself warns that numbers are not marked as words;
  `4`, `2`, `143` would teach the model to replace numbers in normal text.
- *wordfreq ranking.* The dataset has no usage counts. wordfreq covers web, Twitter, Reddit
  and subtitles, which is the closest available proxy for "how often does anyone write this".
- *keep vs translate.* Chat terms like `gg`, `pvp`, `dps` are written the same way by players
  of every language, so translating them makes the output *worse* for the actual reader.
  Abbreviations with a plain meaning (`ty`, `brb`) need to be translated. The mode is part of
  the data, so the model learns both behaviours.
- *Gaming meanings fixed by hand.* The dataset gives SMS meanings (`dm`, `op`, `cc`, `ks` mean
  something else in games); wrong expansions would have been learned verbatim.

## 2. Training phrases

**What.** For every abbreviation 3–5 short chat phrases were written in
`training/abbr_phrases.txt`, each with an expanded version:

```
## brb | translate | be right back
brb, doorbell => be right back, doorbell
## gg | keep | good game
gg everyone
```

`training/abbr_phrases.py` validates the file: the abbreviation is present as a whole word,
`translate` phrases are really expanded, `keep` phrases have no expansion, 3–5 phrases per
abbreviation, no duplicates. First 345 phrases; later the keep terms were topped up to 5
phrases each (see §7), giving **398 phrases**.

**Why.**

- *Hand-written, short, chat-like.* The app translates OCR'd chat lines, typically 2–10 words.
  Real chat logs with these abbreviations were not available under a usable license.
- *Pair = phrase with abbreviation → translation of the expanded phrase.* This teaches the
  mapping "abbreviation → meaning in the target language" without needing anyone to translate
  slang directly.
- *A text file, not code.* Easy to review and edit by a human. The validator catches the
  typical mistakes (abbreviation left in the "full" version, typos in the header).

## 3. Target translations: NLLB itself, with placeholder repair

**What.** `training/translate_phrases.py` translated the **expanded** phrases into the 9 target
languages with the base fp32 model (transformers, beam 4): 397 unique phrases × 9 = 3573 translations.

**Why NLLB and not an LLM API.** Two options were on the table: NLLB (free, lower quality) or the
project's Claude API (better references). NLLB was chosen deliberately: the purpose of the
project is to show the fine-tuning of the model itself, and the self-distillation setup keeps the
whole pipeline local and reproducible. Known cost: NLLB's own mistakes end up in the targets
(`healer` → «врач», `mount` → «гора») and the model learns them; this is documented in the model
card.

**Problem: NLLB destroys keep terms.** Translating `gg everyone` or `anyone lfg? we need a tank`,
NLLB drops or transliterates the term: «ГГ», «ПВП», «аое», «нерва», «Wir brauchen einen Tank».
It lost the term in 633 of 1269 keep translations, and in Cyrillic almost always (ru 113/141).
Dropping those pairs would have left Russian with ~28 keep examples against ~95 for German,
exactly where the problem is worst.

**Fix: placeholders.** The rows that failed are translated again with the term replaced by a
placeholder, and the term is put back in its original spelling (`--repair-keep`). Candidates were
tested on 30 failed rows per language:

| Placeholder | ru | uk | de |
|---|---:|---:|---:|
| number `1079` | 30/30 | 30/30 | 29/30 |
| **`[1]`** | **30/30** | **30/30** | **29/30** |
| `X1` | 27 | 26 | 29 |
| `#1` | 4 | 2 | 4 |

`[1]` was chosen over the number because NLLB treats a number as a quantity and bends the
sentence around it ("so 1079 right now" → «столько 1079»). A repaired row is accepted only if
every placeholder survived. Result: 617 of 633 repaired (later 218 of 226 for the topped-up phrases);
the remaining **24 pairs were dropped**. Repaired rows carry `"repaired": true`.

## 4. General data: FLORES-200, 30 %

**What.** 30 % of every split are FLORES-200 `dev` sentence pairs (English → target, human
references), from the gated `facebook/flores` dataset (CC-BY-SA-4.0; access was requested on
Hugging Face).

**Why.** Fine-tuning only on short chat phrases risks catastrophic forgetting: the model can
start expanding words in normal sentences or degrade on longer input. Mixing in general data is
the standard guard. FLORES `dev` was chosen because it has human references in all 9 target
languages, is aligned across languages, and it is the benchmark NLLB is evaluated on, so a drop
in general quality is visible immediately. The FLORES sentences are split into disjoint
train / val / test pools (70 / 10 / 20 %), so the general test set is never trained on.

## 5. Splits: two experiments, two split modes

`training/build_dataset.py`, seed 42:

| Mode | Used for | How | Test answers |
|---|---|---|---|
| `--split-by abbr` (default) | held-out experiment → `data/processed/` | ~15 % of the **abbreviations** go to test, ~10 % to val, stratified by keep / translate; a phrase containing a test abbreviation goes to test. Asserted: no test abbreviation in train/val. | Does the model generalise to abbreviations it has **never seen**? |
| `--split-by phrase` | release model → `data/processed_final/` | Every abbreviation is trained on; per abbreviation one phrase goes to test, one more to val (if it has 4+). | How well does the model handle **known** abbreviations in **new** phrases? |

**Why two modes.** The original requirement was a test set with abbreviations that are not in
train: an honest test of generalisation. That experiment (§8) showed that the model cannot know
whether an unseen token should be kept or expanded, so a release model has to see every
abbreviation it is supposed to handle. The phrase split is the honest test for that model.

**Reproducibility detail.** The abbreviation split is always drawn first from the shared random
generator, and the phrase split uses its own generator (`seed + 1`). This keeps the FLORES pools
identical in both modes, so general scores are comparable across all runs, and
`data/processed/` rebuilds byte-for-byte from the 345-phrase file.

## 6. Training environment

**What.** A separate venv `.venv-train` with `torch 2.14.0+cu130`, transformers 5.17, peft 0.21,
sacrebleu, ctranslate2 4.8.2 (`requirements-train.txt`). pip cache, temp and HF cache live in
`.train-cache/` on drive E.

**Why.**

- *Separate venv.* The app venv has the CPU build of torch (EasyOCR and the PyInstaller build
  rely on it). Swapping it for a CUDA build would have changed the app environment.
- *Mirror.* `download.pytorch.org` is blocked on this network, and PyPI only has CPU torch
  for Windows. The official wheel was taken from the NJU mirror (`mirrors.nju.edu.cn/pytorch/whl`),
  downloaded in 8 parallel HTTP range requests (2 GB in 89 s instead of ~1 h from the Aliyun
  mirror at 0.3 MB/s) and checked with a full CRC test of the archive before installing.
- *cu130.* The driver (617) supports CUDA 13; 2.14 is the same torch version as the app's.
- *Nothing on drive C.* An explicit project constraint; every download and cache was redirected.

## 7. LoRA training

`training/finetune_lora.py`:

| Setting | Value | Why |
|---|---|---|
| Method | LoRA, not a full fine-tune | 8 GB VRAM. A full fine-tune of 600 M params with AdamW needs ~10 GB for weights + optimizer state alone. LoRA trains 4.7 M params (0.76 %) and the 18 MB adapter is easy to compare, keep and merge. |
| Target modules | `q_proj`, `k_proj`, `v_proj`, `out_proj` in all self- and cross-attention blocks | The task requested attention layers. Cross-attention is where the decoder reads the source, which is exactly where "`ty` means thank you" has to be learned. |
| r / α / dropout | 16 / 32 / 0.05 | Common defaults for a small task (α = 2r); enough capacity for ~100 abbreviations without overfitting 3 k pairs. |
| Precision | fp32 weights, bf16 autocast | Ampere supports bf16. Unlike fp16 it needs no loss scaling, and the base weights stay exact for merging. |
| Effective batch | 16 | Standard for this data size; kept constant across all memory changes below. |
| lr / schedule | 2e-4, linear, 30 warm-up steps | Typical LoRA learning rate (higher than for a full fine-tune, since only the small adapter moves). A short warm-up keeps Adam's first, poorly estimated updates small. |
| Selection | best checkpoint by val loss, 2 checkpoints kept | Protects against over-training without a separate early-stopping run. |
| Seed | 42 (`set_seed`, `data_seed`) | Reproducible data order and dropout. |
| Logging | `checkpoints/<run>/log.jsonl`: loss, val loss, lr, grad norm, peak VRAM, steps/s; `run_config.json` with all arguments | A training log that can be read without TensorBoard. |

**Problems found and fixed during the trial run (50 steps):**

1. **OOM at batch 16.** The logits over NLLB's 256 k vocabulary dominate memory
   (batch × length × 256 k × 4 bytes ≈ 2 GB, plus a copy that accelerate casts to fp32). Fix:
   batch 8 × gradient accumulation 2, plus `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
2. **Loss doubled with gradient accumulation.** With accumulation 2 the logged train loss was
   3.4 against an eval loss of 1.6. Running 10 steps with accumulation 1 and 2 showed exactly ×2.
   Cause: `PeftModel.forward` takes `**kwargs`, so transformers 5 assumes the model normalises
   the loss by `num_items_in_batch` itself and skips dividing by the accumulation steps; M2M100
   ignores that argument. The loss **and the gradients** were summed instead of averaged.
   Fix: `trainer.model_accepts_loss_kwargs = False`; verified that the loss matches with and
   without accumulation.
3. **GPU memory cap at 80 %** (project requirement, so the PC stays usable during training):
   `torch.cuda.set_per_process_memory_fraction(0.8)` in training and evaluation. Batch 8 no longer
   fits under 6.4 GB, so the default became batch 4 × accumulation 4 (same effective batch 16).
   Peak 5.25 GB; speed 0.82 steps/s instead of 1.5.

## 8. Held-out experiment and what it changed

**Run `v1-abbr`** (`data/processed/`, 3 epochs, batch 8 × 2, 350 s). Evaluated against the
published `v0-base` and the fp32 base model on 16 never-seen abbreviations
(details in the eval report):

- general quality **improved** (+2.0 chrF), so the stop criterion (drop > 1–2 chrF) was not hit;
- unseen translate-mode abbreviations improved (+5.7 chrF);
- unseen keep terms **got worse**: the model learned "an unknown short token is an abbreviation,
  expand it" and invented meanings: `gg everyone` → «Мне жаль всех», `wtb healing potions` →
  «Czym są pocje lecznicze?». `gg` was kept in 13 of 45 cases (v0: 33).

**Decision.** Do not publish this model. A model can't tell from an unseen token whether to keep or
expand it, so the release model is trained on **all** abbreviations. The held-out numbers stay
in the model card as an honest estimate of behaviour on abbreviations outside the list.

## 9. Release model: MVP criteria fixed in advance

The criteria were written down **before** the final training runs, so they could not be fitted
to the results:

1. general chrF (FLORES test) not below `v0-base` − 1;
2. keep terms preserved verbatim in ≥ 90 % of cases;
3. translate-mode chrF above `v0-base`.

| Run | Change | Keep | Translate chrF | General chrF |
|---|---|---:|---:|---:|
| v0-base | — | 46.9 % | 41.74 | 55.65 |
| v1-final-a | all abbreviations, 3 epochs | 83.2 % | 48.15 | 57.36 |
| **v1-final-b** | keep terms topped up to 5 phrases, 5 epochs | **93.7 %** | **52.90** | **57.33** |

(v1-final-a was measured on the test set before the top-up; see the eval report.)

**Why those two changes.** In `v1-final-a` the failures were concentrated in specific terms
(`mia` 9/9, `gank` 8/8, `hp` 8/9, `jg` 7/9) that had only **2** training phrases after one went
to test and one to val. Most abbreviations had 3 phrases. Topping every keep term up to 5
phrases (the upper end of the planned 3–5) gives 3 training phrases each. The best checkpoint of
`v1-final-a` was its last one (val loss still falling), so training was extended to 5 epochs;
the best checkpoint of `v1-final-b` was step 800 of 970. Only the keep terms were topped up,
because only that criterion failed. The new phrases went through the same translate +
placeholder repair pipeline.

## 10. Evaluation method

`training/evaluate.py` runs every system on the same test file with the same deterministic
decoding (beam 4, no sampling, seed 42):

| System | Why it is there |
|---|---|
| `v0-base`, CTranslate2 int8 on CPU | What users run today, so this is the reference to beat. The local copy turned out to differ from the published tag (same size, different sha256), so the **published** `v0-base` was downloaded and its hash verified. |
| base fp32 + LoRA (transformers) | Isolates the effect of fine-tuning from quantization. |
| `v1-abbr` int8 on CPU | What will actually ship; the model card reports these numbers. |

Metrics:

- **chrF** (sacrebleu 2.6, β=2, char order 6, the same as `scripts/baseline_eval_nllb.py`),
  separately for abbreviation phrases (also split by keep / translate) and FLORES sentences,
  and per language. Character-level chrF suits the morphologically rich target languages
  (ru, uk, be, pl, cs, hu) better than BLEU.
- **Keep rate**: share of keep phrases whose term appears verbatim in the output. The keep
  references are NLLB's own output for the same sentence, which inflates chrF for the fp32 base
  model, so keep rate is the fair metric there.
- **Paired bootstrap 95 % CI** (1000 resamples) for every difference to `v0-base`, so "general
  quality did not drop" is a statistical statement rather than a single number.

## 11. Merge, conversion, publication

1. `training/merge_lora.py`: `merge_and_unload` into fp32 weights → `models/nllb-finetuned-v1-merged`.
   The script checks that every `q_proj` matrix actually changed, and copies the tokenizer files
   **byte-for-byte** from the base checkpoint instead of re-saving them with transformers 5. The
   new `config.json` differs only in fields that moved or are derived (`max_length` →
   `generation_config.json`, `num_hidden_layers`).
2. Conversion with **the same command as `v0-base`**
   (`ct2-transformers-converter --quantization int8 --copy_files ...`). Every file except
   `model.bin` is byte-identical to `v0-base`, so the two revisions are drop-in replacements.
3. `scripts/test_nllb_translation.py` passes (avg 382 ms vs 402 ms for v0). Non-English
   source pairs are unchanged, as expected.
4. int8 evaluation: keep 92.8 %, translate chrF 52.31, general 57.41, so all MVP criteria hold
   after quantization too (−0.6 chrF on abbreviations vs fp32).
5. Model card: every example was checked against the **int8** output. One example taken from
   the fp32 model (`tbh` → «По правде говоря») was wrong in int8 (`tbh` → «Я знаю») and was
   moved to Limitations.
6. Licensing:
   - weights: CC-BY-NC-4.0 (adaptation of Meta's model), with a list of the changes and a
     no-endorsement / no-warranty note;
   - attribution for willwade/txt-sms-abbreviations (Will Wade, Apache-2.0) and FLORES-200
     (NLLB Team, CC-BY-SA-4.0) with citations;
   - no training data is redistributed in the model repository; the project's own phrases
     are not given a license there.
7. Upload: one commit to `main` with only `model.bin` and `README.md`
   (`2d95429f`), then the annotated tag `v1-abbr`. Hashes verified after upload: `v1-abbr` and
   `main` serve the new `model.bin`, `v0-base` is unchanged (`a5622fe7…`).
8. `config.NLLB_HF_REVISION` was deliberately **not** changed: the app keeps using `v0-base`
   until the new model has been checked by hand.

## 12. Known limitations and ideas for v2

- **Wrong expansions** (`ngl` → «Я не сомневаюсь», `smh` → «Поздравляю»). The model is now eager
  to expand. Ideas: more phrases per translate abbreviation, negative examples with
  non-abbreviation short words and names, or better targets.
- **Self-distilled targets** carry NLLB's errors (`healer` → «врач»). An LLM- or human-reviewed
  target set would raise the ceiling; the pipeline already supports swapping
  `translate_phrases.py`.
- **Keep terms still lost in ~7 %** of cases, mostly `ult`, `xd`, `jg`.
- **Only English sources** were trained; ru → en chat abbreviations are a separate task.
- General per-language FLORES scores rest on ~43 sentences each; only the pooled number is reliable.

---

## Reproducing

```bat
:: environment (once): see requirements-train.txt for the torch wheel
py -3.13 -m venv .venv-train
.venv-train\Scripts\pip install .train-cache\wheels\torch-2.14.0+cu130-cp313-cp313-win_amd64.whl -r requirements-train.txt

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

:: merge + convert + smoke test
.venv-train\Scripts\python training\merge_lora.py --adapter checkpoints\v1-final-b\adapter --out models\nllb-finetuned-v1-merged
.venv-train\Scripts\ct2-transformers-converter --model models\nllb-finetuned-v1-merged ^
    --output_dir models\nllb-v1-abbr-ct2-int8 --quantization int8 ^
    --copy_files tokenizer.json tokenizer_config.json special_tokens_map.json sentencepiece.bpe.model generation_config.json
.venv\Scripts\python scripts\test_nllb_translation.py --model models\nllb-v1-abbr-ct2-int8
```

The data step needs Hugging Face access to `facebook/flores` (gated, auto-approved) and the
FLORES `dev` parquet files in `data/raw/flores200/`. Translation and training are deterministic
for a fixed seed on the same GPU and library versions; bf16 kernels may differ slightly on
other hardware.

## Files

| File | Role |
|---|---|
| `training/prepare_abbreviations.py` | Filter and rank the raw abbreviation list |
| `training/abbr_phrases.txt` | Hand-written phrases (source of truth) |
| `training/abbr_phrases.py` | Validate the phrase file, export JSONL |
| `training/translate_phrases.py` | NLLB translation of expanded phrases; `--repair-keep` placeholder pass |
| `training/build_dataset.py` | Pairs + FLORES mix + splits (`--split-by abbr / phrase`) |
| `training/finetune_lora.py` | LoRA training (bf16, 80 % VRAM cap, logging) |
| `training/evaluate.py` | chrF / keep rate / bootstrap comparison of systems |
| `training/merge_lora.py` | Merge the adapter, copy tokenizer files |
| `requirements-train.txt` | Training venv and how to install CUDA torch here |
| `docs/finetune_v1_eval.md` | Full evaluation results |
