# Configuration

Everyday options are set in the Settings window (`Ctrl+Shift+O`, or the tray icon) and saved at
once to `%APPDATA%\translator-overlay\settings.json`. `.env` in the app folder holds API keys and
a few advanced overrides.

## Settings window

The page names are shown in the interface language; the Russian names are given in brackets.

| Page | What you set there |
|---|---|
| Translation (Перевод) | Backend (Google, DeepL, Azure, LLM, local NLLB) and its keys, LLM provider and model, local model version, source and target language, context profiles |
| Hotkeys (Хоткеи) | The translate hotkey (`Ctrl+Shift+R`) and the settings hotkey (`Ctrl+Shift+O`); they apply at once |
| Regions (Регионы) | Saved screen regions with their own hotkeys, and live monitoring (how often a region is checked and how big a change must be to translate it again) |
| Recognition (Распознавание) | OCR GPU mode (DirectML or CPU), preview and edit the recognised text before translating |
| Popup (Попап) | Show the result in the popup or as a Windows notification, auto-hide timeout, reset the remembered popup size |
| Interface (Интерфейс) | Language (English or Russian) and colour theme, both applied after a restart; app version and the "check for updates" button |

The interface language is picked from the Windows language on first start.

## Hotkeys

| Hotkey | Action |
|---|---|
| `Ctrl+Shift+R` | Select a region and translate it |
| `Ctrl+Shift+O` | Open Settings |
| Per region preset | Translate that saved region without selecting it |

## API keys

The default backend, Google Translate, and the local model need no key. DeepL, Azure and the LLM
backend do: enter the key in Settings (the app also asks for one on start if the LLM backend is
selected without a key). Keys entered in the app are stored in Windows Credential Manager, not in
files.

| Provider | Where to get a key |
|---|---|
| OpenRouter (free models, no card) | [openrouter.ai/keys](https://openrouter.ai/keys) → Create Key; the default model is `poolside/laguna-s-2.1:free` |
| Anthropic (paid) | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys), billing required |
| DeepL | [deepl.com/your-account/keys](https://www.deepl.com/your-account/keys) (Free or Pro) |
| Azure Translator | A Translator resource in the Azure portal → Keys and Endpoint |

For development, keys can also go into `.env` (`copy .env.example .env`).

## `.env` variables

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `GOOGLE_API_KEY` | — | Google Cloud Translation key (optional; without it the keyless endpoint is used) |
| `DEEPL_API_KEY` | — | DeepL API key |
| `AZURE_API_KEY` | — | Microsoft Azure Translator key |
| `SETTINGS_HOTKEY` | — | Overrides the settings hotkey set in Settings → Hotkeys |
| `EASYOCR_GPU` | `auto` | Legacy OCR GPU override: `auto` (DirectML if available), `true`, `false` |
| `EASYOCR_CONFIDENCE_THRESHOLD` | `0.25` | Minimum confidence for recognised text blocks (0.0–1.0) |
| `OCR_USE_HSV_FILTER` | off | `1` enables HSV preprocessing for coloured text on busy backgrounds |
| `NLLB_MODEL_DIR` | — | Path to a CTranslate2 NLLB model (a path set in Settings wins) |
| `NLLB_DEVICE` | `auto` | Local model device: `auto` (GPU if usable, else CPU), `cuda`, `cpu`; overrides Settings → Device |
| `NLLB_GLOSSARY` | `1` | `0` turns off the game-chat glossary that expands terms before NLLB |
| `NLLB_HF_REPO_ID` | `Alhite/overlay-translator-nllb-int8` | Hugging Face repo the model builds come from |
| `NLLB_HF_REVISION` | commit of tag `v0-base` | Build that `scripts/download_model.py` downloads |
| `CACHE_MAX_ITEMS` | `500` | Size of the translation cache and history |
| `LOG_DIR` | `%APPDATA%\translator-overlay\logs` | Directory of `translator.log` |
| `OVERLAY_LOG_TEXT` | `0` | `1` logs the first 80 characters of translated text (debugging only, see [Privacy](privacy.md)) |

## Where data is stored

Everything is under `%APPDATA%\translator-overlay\`, so it survives updates and works when the app
folder is read-only: `settings.json`, `cache\translations.db` (cache and history),
`region_presets.json`, `models\`, `ocr_models\` and the logs. See [Privacy](privacy.md) for what
each file contains.
