# Fine-tune v1 (abbreviations): evaluation

Two evaluations, both produced by `training/evaluate.py` (raw hypotheses and scores in
`checkpoints/eval/` and `checkpoints/eval_final/`, not in git):

1. **Held-out abbreviation experiment** (`v1-lora`): 16 abbreviations never seen in
   training — measures how the fine-tune generalises to *unknown* abbreviations.
2. **Final model** (`v1-final-b`, released as `v1-abbr`): trained on all 102
   abbreviations, tested on *unseen phrases* of known abbreviations plus held-out FLORES
   sentences. This is the model that ships.

---

## Final model (`v1-abbr`)

### MVP criteria (fixed before training)

`v1-abbr` fp32 is the merged LoRA model in transformers; `v1-abbr` int8 is the
published CTranslate2 build (`models/nllb-v1-abbr-ct2-int8`), scored on the CPU exactly
like `v0-base`.

| Criterion | v0-base (int8) | v1-abbr fp32 | **v1-abbr int8** | |
|---|---:|---:|---:|---|
| General chrF (FLORES) not below v0-base − 1 | 55.65 | 57.33 | **57.41** (+1.76, CI +0.84 … +2.77) | ✅ |
| Keep terms preserved verbatim ≥ 90 % | 46.9 % | 93.7 % | **92.8 %** | ✅ |
| Translate-mode chrF above v0-base | 41.74 | 52.90 | **52.31** (+10.6) | ✅ |
| chrF, all abbreviation pairs | 51.21 | 59.10 | 58.46 (+7.25, CI +5.57 … +9.06) | |
| chrF, keep-mode pairs | 70.54 | 72.33 | 71.58 | |

int8 quantisation costs ~0.6 chrF on abbreviations and ~1 point of keep rate; general
quality is unchanged.

### Setup

| | |
|---|---|
| Data | `training/build_dataset.py --split-by phrase --out-dir data/processed_final`, seed 42. Every abbreviation is trained on; per abbreviation one phrase goes to test and one more (if it has 4+) to val. Keep terms were topped up to 5 phrases each (398 phrases total). |
| Train / val / test | 3093 / 689 / 1301 pairs (abbreviation 2165 / 482 / 911, FLORES 928 / 207 / 390). The FLORES pools are the same as in the held-out experiment. |
| Training | LoRA r=16, α=32 on q/k/v/out_proj; 5 epochs, 970 steps, effective batch 16 (4 × grad-accum 4), lr 2e-4 linear, warmup 30, bf16, seed 42; GPU memory capped at 80 % (peak 5.25 GB); 1088 s on RTX 3060 Ti. Best checkpoint by val loss: step 800 (1.084). |
| Decoding / metric | as below: beam 4, no sampling, sacrebleu chrF, paired bootstrap 95 % CI |

### How it got there

| Run | Change | Keep preserved | Translate chrF | General chrF |
|---|---|---:|---:|---:|
| v0-base | — | 46.9 % | 41.74 | 55.65 |
| v1-final-a | all abbreviations, 3 epochs, 2 train phrases per keep term | 83.2 %¹ | 48.15¹ | 57.36¹ |
| **v1-final-b** | + keep terms topped up to 5 phrases (3 in train), 5 epochs | **93.7 %** | **52.90** | **57.33** |

¹ measured on the test set before keep terms were topped up (v0-base there: 45.4 % / 42.02 / 55.76).

### Per language

| | be | cs | de | es | fr | hu | pl | ru | uk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| General, v0-base | 38.1 | 57.8 | 58.6 | 57.2 | 68.4 | 57.3 | 49.8 | 55.4 | 53.7 |
| General, v1-abbr fp32 | 40.6 | 57.5 | 62.4 | 57.4 | 71.7 | 56.9 | 49.6 | 58.7 | 56.3 |
| Abbreviations, v0-base | 50.6 | 50.4 | 53.8 | 55.1 | 57.9 | 51.5 | 50.0 | 46.5 | 43.7 |
| Abbreviations, v1-abbr fp32 | 55.1 | 60.8 | 60.8 | 65.7 | 64.4 | 59.0 | 58.7 | 54.7 | 52.1 |
| General, v1-abbr int8 | 40.4 | 57.0 | 60.8 | 57.1 | 72.6 | 57.8 | 51.4 | 59.0 | 56.0 |
| Abbreviations, v1-abbr int8 | 54.6 | 58.5 | 59.3 | 65.1 | 63.9 | 59.3 | 57.7 | 53.7 | 53.2 |

### Remaining errors

- Keep terms still lost in 7 % of cases, mostly `ult` (8), `xd` (6), `jg` (3).
- **Wrong expansions.** Where v0-base silently drops an abbreviation, v1-abbr sometimes
  expands it to the wrong meaning (ru): `ngl` → «Я не сомневаюсь», `nvm` → «На мой
  взгляд», `lmao` → «Я знаю», `omg we won` → «О, нет сомнений, мы выиграли»,
  `smh at this team` → «Поздравляю с этой командой». Many others are now right:
  `ty` → «Спасибо», `tbh` → «По правде говоря», `gratz` → «Поздравляем»,
  `afaik` → «По крайней мере» (approximate). chrF rewards the right expansions but barely
  penalises a wrong short one, so the translate-mode gain overstates the quality somewhat.
- References inherit NLLB's own mistakes (`mount` → «гора», `healer` → «исцелитель»).


---

## Held-out abbreviation experiment (`v1-lora`)

Run before the keep terms were topped up: `data/processed/` was built from the first 345
phrases (`training/build_dataset.py` with the default `--split-by abbr`); rebuilding it
from the current 398-phrase file gives a different set.

### Setup

| | |
|---|---|
| Base model | NLLB-200-distilled-600M (fp32, `models/nllb-200-distilled-600M`) |
| Fine-tune | LoRA r=16, α=32, dropout 0.05 on `q/k/v/out_proj` of all self- and cross-attention blocks (4.7 M trainable params, 0.76 %) |
| Training | 3 epochs, 606 steps, effective batch 16 (8 × grad-accum 2), lr 2e-4 linear, warmup 30, bf16, seed 42, 350 s on RTX 3060 Ti; best checkpoint by val loss: step 400 (val loss 1.400) |
| Train data | 3230 pairs: 2261 abbreviation pairs (76 abbreviations) + 969 FLORES-200 dev pairs (30 %) |
| Test data | `data/processed/test.jsonl`, 771 pairs: 540 abbreviation pairs (315 translate, 225 keep) + 231 FLORES-200 dev pairs; en → de, fr, es, ru, uk, be, pl, cs, hu |
| Decoding | beam 4, no sampling, max 256 tokens, seed 42 — identical for every system |
| Metric | sacrebleu 2.6.0 chrF (β=2, char order 6); deltas with a paired bootstrap 95 % CI (1000 resamples, seed 42) |

**The test abbreviations are never seen in training.** 16 of 102 abbreviations are held out
entirely (afaik asap bbl dm gg ggwp gratz gz lmao pls pvp ty tysm ult wp wtb), so the
abbreviation score measures *generalisation to unseen abbreviations*, not memorisation.
FLORES sentences in test are disjoint from those in train/val.

Systems:

| Name | What it is |
|---|---|
| `v0-base` | Published `Alhite/overlay-translator-nllb-int8@v0-base` — CTranslate2 int8 on CPU, i.e. what the app runs (sha256 of `model.bin` verified against the tag) |
| `base-fp32` | The same base model in fp32 (transformers) — isolates the effect of the fine-tune from int8 quantisation |
| `v1-lora` | `base-fp32` + the LoRA adapter (`checkpoints/v1-abbr/adapter`) |

### Results

| Metric | v0-base | base-fp32 | v1-lora | v1 − v0 (95 % CI) |
|---|---:|---:|---:|---:|
| chrF, abbreviation pairs | 56.64 | 60.64 | 57.07 | +0.43 (−1.71 … +2.57) |
| — translate mode (afaik → "as far as I know") | 44.73 | 46.80 | **50.47** | +5.74 |
| — keep mode (gg, pvp stay as is) | 78.43 | 85.98 | 69.14 | −9.29 |
| Keep terms preserved verbatim, % | 66.2 | 69.8 | 63.1 | −3.1 |
| **chrF, general (FLORES-200)** | 54.67 | 55.16 | **56.66** | **+1.99 (+0.72 … +3.43)** |

**General translation did not degrade** — it improved by 2.0 chrF over `v0-base` (CI excludes 0)
and by 1.5 over `base-fp32`. The stop criterion (general drop > 1–2 chrF) is not triggered.

#### Per language

General (FLORES, ~25 sentences per language — individual numbers are noisy):

| | be | cs | de | es | fr | hu | pl | ru | uk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v0-base | 35.5 | 56.9 | 57.5 | 56.9 | 67.4 | 57.0 | 50.5 | 53.4 | 52.0 |
| base-fp32 | 35.3 | 56.6 | 57.1 | 56.1 | 71.0 | 55.0 | 50.1 | 54.6 | 54.1 |
| v1-lora | 37.1 | 55.9 | 61.7 | 57.2 | 71.3 | 57.8 | 50.9 | 55.9 | 56.0 |
| v1 − v0 | +1.7 | −1.0 | +4.2 | +0.3 | +3.9 | +0.9 | +0.4 | +2.6 | +3.9 |

Abbreviation pairs:

| | be | cs | de | es | fr | hu | pl | ru | uk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v0-base | 56.6 | 59.1 | 60.3 | 59.2 | 58.9 | 51.0 | 60.7 | 52.7 | 50.7 |
| base-fp32 | 57.8 | 62.5 | 66.6 | 63.1 | 64.2 | 55.8 | 65.3 | 57.1 | 52.4 |
| v1-lora | 55.2 | 54.5 | 63.5 | 63.1 | 58.3 | 50.5 | 55.1 | 59.8 | 51.9 |
| v1 − v0 | −1.4 | −4.6 | +3.2 | +3.9 | −0.6 | −0.5 | −5.6 | +7.1 | +1.2 |

#### Keep terms, per abbreviation (preserved / total)

| Term(s) | v0-base | base-fp32 | v1-lora |
|---|---:|---:|---:|
| gg | 33 / 45 | 35 / 45 | **13 / 45** |
| wtb | 17 / 27 | 19 / 27 | **0 / 27** |
| pvp | 29 / 36 | 30 / 36 | 36 / 36 |
| ult | 13 / 36 | 13 / 36 | 24 / 36 |
| wp | 19 / 27 | 18 / 27 | 19 / 27 |
| ggwp | 25 / 27 | 26 / 27 | 27 / 27 |
| cd + ult | 4 / 9 | 4 / 9 | 8 / 9 |
| noob | 4 / 9 | 6 / 9 | 6 / 9 |
| nerf + op | 5 / 9 | 6 / 9 | 9 / 9 |

### Interpretation

1. **Unseen "translate" abbreviations are understood better**: +5.7 chrF over `v0-base`
   (+3.7 over `base-fp32`). The model learned to expand chat abbreviations it has never seen.
2. **The same skill hurts unseen "keep" terms.** The model now treats an unknown short token
   as an abbreviation to expand and invents a meaning: `gg everyone` → ru «Мне жаль всех»,
   es «Quiero hablar con todos»; `wtb healing potions` → pl «Czym są pocje lecznicze?».
   `gg` and `wtb` collapse; `pvp`, `ult`, `ggwp`, `nerf`, `op` improve. With the terms
   held out the model has no way to know whether an unseen token should be kept or
   expanded, so this half of the test measures a guess.
3. **General translation improved** (+2.0 chrF), most likely because the FLORES share
   nudges the model toward the human references and away from some of its own habits.

### Caveats

- **Abbreviation references are NLLB output** (fp32 translation of the expanded phrase,
  with keep terms restored via `[n]` placeholders). For keep phrases the source *is* the
  expanded phrase, so `base-fp32` reproduces many references token for token — its
  keep-mode chrF (85.98) is inflated and is not a fair upper bound. `keep_rate` is the
  fairer keep metric.
- General per-language scores rest on ~25 sentences each; only the pooled number and its
  CI are reliable.
- `v1-lora` is fp32 + adapter. The int8 CTranslate2 build of v1 is scored in stage 5.
