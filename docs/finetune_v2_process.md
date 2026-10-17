# Fine-tune v2 (game glossary): how it was made, results

v2 extends the v1 abbreviation fine-tune ([finetune_v1_process.md](finetune_v1_process.md)) with
the game-chat glossary `training/game_abbreviations_en.txt` (3035 rows, 13 sections). Same base
model, same LoRA recipe, same evaluation code; v1's release data and test set are reused unchanged.

| | |
|---|---|
| Base model | `facebook/nllb-200-distilled-600M`, fp32 |
| Release candidate | `checkpoints/v2b-game/adapter` (best step 6600) → `models/nllb-v2-game-ct2-int8` |
| Result (int8, vs v1-abbr) | v1 test: keep 92.8 → 96.4 %, translate chrF 52.31 → 53.65, general 57.41 → 57.78; glossary test: keep 76.4 → 94.4 %, translate chrF 49.38 → 53.31 |
| Open issue | ordinary single words: chrF 66.6 vs 86.0 for v0-base (v1: 54.4); criterion 6 failed |
| Published | HF commit `93244659` (only `model.bin` + `README.md`), tag `v2-game`; the app config still points to `v0-base` |

---

## 1. Curating the glossary (`training/game_abbreviations.py`)

The file is a glossary, not a phrase set: 2789 of 3035 examples are the abbreviation alone,
1337 rows are ordinary words (`armor | armor`, `head | head | KEEP`, `push | push | KEEP`), and
the header itself calls the policy "a first guess". Trained verbatim, it would teach the model
to leave ordinary English untranslated. Each row is resolved first:

| Rule | Why | Rows |
|---|---|---:|
| meaning == abbreviation and wordfreq Zipf ≥ 3 → `plain` (normal translation, used as a negative) | `armor`, `sword`, `kill` are words, not abbreviations | 768 entries |
| KEEP spelling with Zipf ≥ 4 (except an allow-list: `op hp cc dps aoe ...`) → dropped | `a`, `top`, `black`, `de` cannot be told apart from the word | 146 |
| CONTEXT: proper-name meaning → keep; social section → translate; else dropped | `creep = creep tumor`, `all = alliance` would be wrong in most chat | 83 dropped |
| Meanings with `/` or `*`, single letters (except `u r y k`), a deny-list (`fixed → fixed price`) → dropped | ambiguous or censored expansions | 27 |
| Abbreviation already in v1 → v1's mode and expansion win | v1 was validated (`gl`, `hp`, `lfg`, `dm` conflicted) | 102 |
| Rows of one abbreviation that still disagree → dropped | `lol` = laughing / League of Legends | 16 |

Result: 2046 lexicon entries (1101 keep, 177 translate, 768 plain). Expansion and keep terms are
computed **per token** with the lexicon, so mixed lines get correct "full" versions:
`lfm +10, need tank and dps` → `looking for more +10, need tank and dps`, keep `+10`, `dps`.
Number suffixes (`500g`, `2kk`) are keep terms.

**Phrases.** Per entry: the real example, the abbreviation alone, two chat wrappers
(`guys, idk`, `IDK, ok?`). Section 13 template sentences → test; ~20 % of real examples → test,
~10 % → val (the abbreviation stays in train through its other phrases). v1 phrases are
excluded (they already have their own split). Train phrases get 3 target languages (seeded by the
phrase text, so edits don't reshuffle others), plain negatives and val/test all 9.

## 2. Targets

`translate_phrases.py --input/--output` (fp32 NLLB, beam 4) on 17,478 (phrase, language) pairs,
then `--repair-keep` with `[n]` placeholders as in v1. New rule: if a phrase is nothing but keep
terms and punctuation (`sks!`), the target is the source itself — on a bare `[1]` NLLB
hallucinated in es/fr ("En el caso de los Estados miembros,"). All keep terms preserved after repair.

## 3. Data (`training/build_dataset_v2.py` → `data/processed_v2b/`)

| Split | Pairs |
|---|---|
| train | 23,575: v1 abbr 2,165 + v2 abbr 15,516 + FLORES 5,894 (25 %) |
| val | 1,112 (v1 689 + v2 423) |
| test_v1 | 1,301 — v1 release test, byte-identical |
| test_v2 | 1,539 — 171 phrases × 9 languages (templates, held-out examples, plain words) |

FLORES pools are recomputed exactly as in v1, so the general test sentences are never trained on.

## 4. Training

LoRA r 32 / α 64 (2× v1: ~20× more abbreviations), q/k/v/out_proj, 5 epochs, batch 4 × accum 4,
lr 2e-4, bf16, group-by-length, seed 42. **GPU limited to 90 % during training only:**
`--gpu-mem-fraction 0.9` (VRAM cap) and `--gpu-duty 0.9` (sleep after each step so compute ≤ 90 %
of wall time; a power limit would need admin rights). Peak 5.49 GB, ~1 step/s, RTX 3060 Ti.

Problems fixed on the way: batch 8 OOM'd on long FLORES batches; evaluation OOM'd because the
Trainer kept every val batch's fp32 logits (`prediction_loss_only=True`); the v2b run was killed
by host RAM pressure at step ~4400 and resumed from `checkpoint-4400` (`--resume`).

| Run | Change | Best val loss | test_v2 plain chrF |
|---|---|---:|---:|
| v2-game | plain negatives in 3 languages | 0.9275 (step 5400) | 57.19 |
| **v2b-game** | plain negatives in all 9 languages | **0.9166** (step 6600) | **70.78** |

## 5. Results

Criteria were fixed before training. int8 = CTranslate2 build on CPU, as the app runs it.

| Criterion | v0-base | v1-abbr int8 | v2b fp32 | **v2 int8** | |
|---|---:|---:|---:|---:|---|
| 1. test_v1 general chrF ≥ v1 − 1 | 55.65 | 57.41 | 57.70 | **57.78** | ✅ |
| 2. test_v1 keep ≥ 90 % | 46.9 | 92.8 | 96.7 | **96.4** | ✅ |
| 3. test_v1 translate chrF ≥ v1 − 1 | 41.74 | 52.31 | 54.81 | **53.65** | ✅ |
| 4. test_v2 keep ≥ 90 % and > v1 | 39.9 | 76.4 | 93.2 | **94.4** | ✅ |
| 5. test_v2 translate chrF > v0, v1 | 35.63 | 49.38 | 53.56 | **53.31** | ✅ |
| 6. test_v2 plain chrF ≥ v0 − 2 | 76.95 | 48.97 | 70.78 | **59.67** | ❌ |
| test_v2 all abbreviation pairs | 49.34 | 54.54 | 61.24 | 60.22 (+10.9, CI +9.2 … +12.6) | |

**About criterion 6.** Plain references are the base model's own translation of an isolated
word, so valid alternatives lose points (`kill` → «убить» vs «убивать») and some references are
broken (`wii` → «- ¿Por qué no?»; `grinding` (hu) is a 100× repeated word). That one hu reference
alone explains the fp32 → int8 drop (hu 79.1 → 34.1). Without it: v0 86.0, v1 54.4, v2b fp32
68.2, v2 int8 66.6. The criterion still fails: v2 leaves more ordinary words untranslated (96 of
513 vs 53 for v0) — but it recovers a large part of what v1 lost.

## 6. Sample translations (fresh lines, int8, en → ru)

| Input | v0-base | v1-abbr | v2 |
|---|---|---|---|
| idk where the vendor is, lmk if you find it | Я знаю, где продавец, я знаю, если ты найдешь его. | Я не знаю, где продавец, я точно знаю, если найдешь его. | **Я не знаю, где продавец, дай мне знать, если найдешь его.** |
| tbh this patch is mid, rogues are op | Тбх этот патч в середине, злодеи находятся в оперативной. | По моему мнению, этот патч в середине, … | **Если честно**, эта пачка в середине, злодеи op |
| omw to the boss, wait for me | Омв к боссу, подождите меня. | Передай мне босс, подожди меня. | **Отправляюсь к боссу, подожди меня.** |
| wts epic sword, 500g, pm me | Эпический меч, 500 граммов, пожалуйста. | wts эпический меч, 500 г, отправьте мне сообщение | **wts эпический меч, 500g, посылайте мне сообщение** |
| ty all, gg wp, see you tomorrow | Всем, ГГ ВП, увидимся завтра. | Спасибо всем, gg wp, увидимся завтра. | Спасибо всем, gg wp, увидимся завтра |
| lf2m for mythic dungeon, need tank and healer | Иф2м для мифического подземелья, … | lf2m для мифического подземелья, … | ✗ Я хочу вернуться в мифический подземелье, … |
| gz on the drop, rng finally blessed you | Гз на посадке, Рнг наконец-то благословил тебя | Поздравляю с доставкой, RNG наконец-то … | ✗ Поздравляю с доставкой, и, наконец, Господь благословил тебя. |
| the weather is nice today, let's go for a walk | Сегодня хорошая погода, пойдем на прогулку. | Погода сегодня хорошая, … | Сегодня хорошая погода, пойдем на прогулку. |

## 7. Known limitations / next steps

- **Unseen variants are expanded wrongly**: `lf2m` (only `lf1m` is in the lexicon) → «Я хочу
  вернуться»; same failure mode as v1's held-out experiment. Add numbered variants (`lf2m`, `lf3m`).
- **Keep term lost in some contexts**: `rng` → «Господь» (ru), `relog` left in English.
- **Ordinary words** (criterion 6): more plain negatives in context (`kick him`, `cover me`),
  not as isolated words; replace self-distilled plain references with human-checked ones.
- Self-distilled targets still carry NLLB's errors (`tank` → «резервуар», `clutch` → «сцепление»).

## Reproducing

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

Requires `wordfreq` in the app venv (`.venv`) for the curation step. Evaluation outputs:
`checkpoints/eval_v2/` (test_v2) and `checkpoints/eval_v2_t1/` (test_v1).
