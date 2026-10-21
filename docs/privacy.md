# Privacy

Text you translate can be anything on your screen: private chats, names, passwords. This page
lists exactly what leaves your computer, what stays on it and what is written to disk.
There is no telemetry and no account.

## What goes over the network

| When | Where it goes | What is sent |
|---|---|---|
| A translation with **Google Translate** (default) | `translate.googleapis.com` (keyless) or the Cloud Translation API (with `GOOGLE_API_KEY`) | The recognised text and the target language |
| A translation with **DeepL** | `api-free.deepl.com` or `api.deepl.com` | The text, the languages, your DeepL key |
| A translation with **Azure Translator** | `api.cognitive.microsofttranslator.com` | The text, the languages, your Azure key |
| A translation with the **LLM** backend | `openrouter.ai` or the Anthropic API | The text, a system prompt (domain profile), your key |
| Every app start | `api.github.com` (latest release of this repository) | A plain request for the release list; no data about you or your texts |
| **Update** in the new-version banner | GitHub release download | Nothing; the installer is downloaded and checked against its SHA-256 |
| First launch, OCR | ModelScope (by `rapidocr`) | Nothing; the recognition model (~8 MB) is downloaded once |
| Downloading a local model build | `huggingface.co` | Nothing; the files are downloaded and checked against their SHA-256 |

Each provider handles the text under its own terms. **Free OpenRouter models may log prompts and
use them for training.** Do not send passwords or personal data through a cloud backend.

**The local NLLB backend never touches the network.** With it, a translation is fully offline:
screen capture, OCR and translation all run on your machine. Each backend checks the local cache
first, so a line it has already translated is not sent again.

If the local model is selected but cannot be loaded, the request goes through the API backend
instead, and the popup says so. Keep a working model (Settings shows its status) if the text must
stay on your machine.

## What stays on your computer

Everything below is under `%APPDATA%\translator-overlay\` (kept when you uninstall; delete the
folder to remove it).

| Data | File | Contains your text? |
|---|---|---|
| Settings | `settings.json` | No |
| Translation cache and history | `cache\translations.db` | **Yes**: source lines and translations, the newest `CACHE_MAX_ITEMS` (500) of them. Clear it on the History page |
| Region presets | `region_presets.json` | No (coordinates and hotkeys) |
| API keys | Windows Credential Manager, service `OverlayTranslator` | No. Keys entered in the app are not stored in files; a `.env` file is read too if you create one |
| Logs | `app.log`, `logs\translator.log`, `crash.log` | No, see below |
| Downloaded models | `models\`, `ocr_models\` | No |

Screenshots are kept in memory only and are never written to disk. The popup is excluded from
screen capture (Windows 10 2004 and later): it is visible on your screen but not in screenshots,
recordings, streams or screen sharing.

## Logging

- `app.log` — app events, errors and Qt messages; `logs\translator.log` — one line per
  translation request (backend, timing, cache hit or miss); `crash.log` — thread stacks if the
  process crashes. The logs rotate at 2 MB and keep two old files.
- **The text itself is never logged.** Log lines show only its length, for example
  `text=<11 chars>`.
- For a debugging session you can set `OVERLAY_LOG_TEXT=1` (environment variable or `.env`);
  then the first 80 characters of each text are logged. Turn it off afterwards and delete the logs
  if they went to someone else.

When you attach logs to a bug report, check them first: they contain file paths with your Windows
user name.
