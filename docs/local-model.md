# Local offline model (NLLB)

Instead of a cloud service, the app can translate with
[NLLB-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M), converted to
an int8 [CTranslate2](https://github.com/OpenNMT/CTranslate2) model (~620 MB). It works offline,
needs no API key and covers the 29 languages mapped in `translate/nllb_backend.py`.

> **License:** the model and every build made from it are **CC-BY-NC-4.0**: non-commercial use
> only. See [MODEL_LICENSE.md](https://github.com/Vrihe/Overlay-Translator/blob/main/MODEL_LICENSE.md).

## Model versions

Builds are published on the Hugging Face Hub as
[Alhite/overlay-translator-nllb-int8](https://huggingface.co/Alhite/overlay-translator-nllb-int8),
one git tag per version:

| Tag | What it is |
|---|---|
| `v0-base` | Plain int8 conversion of the original model, no fine-tuning |
| `v1-abbr` | Fine-tuned on ~100 chat abbreviations (`brb`, `gg`, …): keeps or expands them correctly |
| `v2-game` | Fine-tuned on a larger game-chat glossary; best keep rate and abbreviation scores |

How each was trained and scored: [Training](training.md), [Reproducing experiments](experiments.md).

Before a line reaches the model, a game-chat glossary expands common terms (`wts` → "want to sell")
and masks names and terms that must stay as they are. `NLLB_GLOSSARY=0` turns it off.

## Getting the model

**In the app (easiest).** Settings → Translation → Translation backend → **Local (NLLB)** →
**Model version** lists every published build. Pick one and press **Download**: files are checked
against their SHA-256 and saved to `models\nllb-<tag>` (in the installed app, under
`%APPDATA%\translator-overlay\models\`). The first-run wizard offers the same in offline mode.

**With a script (from source).**

```powershell
python scripts/download_model.py              # the pinned build → models/nllb-200-ct2-int8
python scripts/download_model.py --revision v2-game --dest models/nllb-v2-game
```

The default build is pinned to the commit behind the `v0-base` tag by `NLLB_HF_REPO_ID` /
`NLLB_HF_REVISION` in `config.py`, so everyone gets identical weights. Re-running the script only
fetches files that changed.

**Convert it yourself.** Needs `transformers` and `torch` for this one step
(`pip install -r requirements-dev.txt`):

```powershell
ct2-transformers-converter --model facebook/nllb-200-distilled-600M `
    --output_dir models/nllb-200-ct2-int8 --quantization int8 `
    --copy_files sentencepiece.bpe.model tokenizer.json tokenizer_config.json special_tokens_map.json generation_config.json
```

The first run downloads the original checkpoint (~2.5 GB); set `HF_HOME=.hf-cache` to keep it in
the project (git-ignored). A usable model folder contains `model.bin`, `config.json`,
`shared_vocabulary.json` and `sentencepiece.bpe.model`. Check it with
`python scripts/test_nllb_translation.py --model models/nllb-200-ct2-int8`.

## Where the app looks for the model

1. The build chosen in **Model version**, or the folder set under **Custom path** (if set, it is the
   only place checked).
2. The `NLLB_MODEL_DIR` environment variable.
3. Auto-discovery: `<app>\models\`, then `%APPDATA%\translator-overlay\models\`; first
   `nllb-200-ct2-int8`, then any other complete build, newest first.

## Using it

Select **Local (NLLB)** as the translation backend; the choice is saved at once and the status line
shows whether the model was found. **Load model** loads it into memory right away (1–3 s);
otherwise it loads on the first translation.

- If the model cannot be loaded (missing files, a broken folder), the request goes through the API
  backend instead and the popup says why. An error *during* a translation is shown as an error and
  never falls back silently.
- Domain profiles (prompts, few-shot examples) do not apply: NLLB is a plain translation model.
- There is no streaming: the popup shows the whole translation at once.

## GPU acceleration

The model runs on the CPU out of the box; an NVIDIA GPU is an optional speed-up. Measured on a
Ryzen (Zen 3) + RTX 3060 Ti, one 18-token English sentence → Russian, beam size 4:

| Device | Time per sentence |
|---|---|
| CPU, int8, 4 threads | ~1050 ms |
| GPU, `int8_float16` | ~310 ms |

Requirements: an NVIDIA GPU with a driver that supports CUDA 12, and cuBLAS for **CUDA 12.x**
(`cublas64_12.dll`; CUDA 11 or 13 libraries do not work with CTranslate2 4.x). One of:

- **Easiest (installed app):** Settings → Translation backend → local model → **Download for the
  GPU**. It appears when an NVIDIA driver is found and cuBLAS is not; the app downloads the official
  `nvidia-cublas-cu12` wheel from PyPI (~530 MB, checked against PyPI's SHA-256) and keeps only its
  DLLs in `%APPDATA%\translator-overlay\cuda` (~740 MB), or
- `pip install -r requirements-gpu.txt` (the `nvidia-cublas-cu12` wheel, ~740 MB; from source:
  `install.bat --gpu`), or
- [CUDA Toolkit 12.x](https://developer.nvidia.com/cuda-12-9-0-download-archive), found through
  `CUDA_PATH` / `CUDA_PATH_V12_*` or the default install folder.

With `NLLB_DEVICE=auto` (the default) the app checks for an NVIDIA GPU when the model loads, looks
for cuBLAS and runs a short test translation on the GPU. If any step fails, the model loads on the
CPU; the reason goes to the log and is shown once in the popup and in Settings (for example
`CUDA unavailable, using CPU inference (cublas64_12.dll not found …)`). Without an NVIDIA GPU the
switch to the CPU is silent.

The installer does not bundle cuBLAS: download it from the settings as above, or install CUDA
Toolkit 12.x. **Device → CPU only** in the same settings keeps the model off the GPU (for example
while a game needs it); the `NLLB_DEVICE` environment variable overrides it.
