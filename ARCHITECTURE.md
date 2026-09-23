# ARCHITECTURE.md — карта проекта Overlay Translator

> Служебный документ для быстрой ориентации в репозитории.
> Читать вместо повторного сканирования всех файлов.

---

## 1. Обзор

**Overlay Translator** — десктопное Windows-приложение (PyQt5), которое по
глобальному хоткею позволяет выделить произвольную область экрана, распознать
в ней текст (OCR) и показать перевод во всплывающем окне поверх всех окон.

**Основной сценарий**: `Ctrl+Shift+R` → рамка выделения → скриншот области →
EasyOCR → перевод (облачный API **или** локальная модель NLLB) → popup с переводом.

**Стек**:

| Слой | Технология |
|---|---|
| GUI | PyQt5 5.15 (QMainWindow + sidebar, QSystemTrayIcon, frameless popups) |
| Захват экрана | `mss` |
| OCR | EasyOCR (CRAFT + CRNN) поверх torch/torchvision, CPU или CUDA |
| Перевод (API) | OpenRouter (OpenAI-совместимый SDK) и/или Anthropic SDK |
| Перевод (офлайн) | NLLB-200-distilled-600M, CTranslate2 int8 + sentencepiece, CPU |
| Определение языка | `langid` + эвристика по script'у, либо LLM |
| Хранилище | SQLite (кэш + история), JSON (настройки, пресеты, профили) |
| Секреты | OS keyring (Windows Credential Manager) + `.env` |
| Хоткеи | `keyboard` (глобальные, фоновый поток) |
| Сборка | PyInstaller (`build.py`, `*.spec`) |

Язык интерфейса и логов — русский; язык кода/докстрингов — английский.

---

## 2. Структура директорий

```
Overlay-Translator/
├── main.py                 # Точка входа: логирование, splash, TranslatorApp, хоткеи
├── config.py               # Глобальный конфиг-фасад (подменяет себя в sys.modules!)
├── build.py / build.bat    # Сборочные скрипты PyInstaller
├── build*.spec             # Spec-файлы (слоёная сборка: app + deps)
├── hooks/hook-optree.py    # PyInstaller hook
├── pyi_rth_torch_dll.py    # Runtime-hook: пути к torch DLL во frozen-сборке
├── _deps_stub.py           # Заглушка для слоёной сборки зависимостей
│
├── capture/                # Захват экрана
│   ├── screenshot.py       #   capture_region() через mss
│   └── live_monitor.py     #   LiveMonitor(QThread) — периодический ре-скан области
│
├── ocr/                    # Распознавание текста
│   ├── engine.py           #   EasyOCR singleton, препроцессинг, сортировка строк
│   └── hsv_filter.py       #   Опциональный HSV-фильтр для цветного текста
│
├── overlay/
│   └── selector.py         #   RegionSelector — полноэкранная рамка выделения
│
├── translate/              # Перевод и языковая логика
│   ├── backend.py          #   * Диспетчер: выбирает API или локальную модель
│   ├── llm_client.py       #   * Бэкенд перевода через облачный API
│   ├── nllb_backend.py     #   * Офлайн-бэкенд: NLLB-200 (CTranslate2 int8)
│   ├── cuda_support.py     #   Locates cuBLAS for optional GPU inference
│   ├── domain_manager.py   #   Доменные профили (промпты + few-shot)
│   ├── lang_detect.py      #   Детекция языка, fast-path «тот же язык»
│   ├── error_classification.py  # Ретраибельность ошибок провайдера
│   └── domain_profiles/    #   general.json, chat.json, game.json, documentation.json
│
├── cache/                  # SQLite-кэш и история (L1 LRU + L2 SQLite)
│   └── store.py            #   * Схема таблицы translations
│
├── settings/               # Персистентность настроек
│   ├── __init__.py         #   * API-ключи через keyring + провайдер/fallback
│   ├── config_manager.py   #   * settings.json: DEFAULTS / get / set_value
│   └── region_presets.py   #   Пресеты областей экрана + их хоткеи
│
├── ui/                     # Виджеты PyQt5
│   ├── main_window.py      #   MainWindow с sidebar (Home/History/Settings)
│   ├── settings_dialog.py  #   * SettingsWidget — все настройки; ProfileEditorDialog
│   ├── result_popup.py     #   ResultPopup — окно результата (TTS, копирование, resize)
│   ├── first_run_dialog.py #   Мастер первого запуска (ввод API-ключа)
│   ├── ocr_preview_popup.py#   Предпросмотр/правка OCR до перевода
│   └── region_presets_dialog.py # Управление пресетами и их хоткеями
│
├── history/
│   └── history_window.py   #   HistoryWidget/HistoryWindow — просмотр и экспорт истории
│
├── tray/                   # Иконка в системном трее + контекстное меню
├── tts/engine.py           # Озвучка перевода (SAPI, в отдельном потоке)
├── updater/check_update.py # Проверка релизов на GitHub
├── scripts/                # Оффлайн-утилиты (не входят в сборку приложения)
│   ├── test_nllb_translation.py    # Smoke-тест локальной модели + замер CPU-latency
│   ├── export_history_dataset.py   # История SQLite → JSONL для fine-tune
│   └── baseline_eval_nllb.py       # chrF-baseline NLLB на реальных парах
├── tests/                  # unittest/pytest-тесты
├── docs/
│   └── baseline_eval.md    #   Точка отсчёта качества NLLB до fine-tune
├── data/                   # Экспортированные датасеты (gitignored — данные пользователя)
└── assets/icon.ico         # Иконка приложения
```

**Не редактируемое / не версионируемое** (см. `.gitignore`):
`__pycache__/`, `.venv/`, `dist/`, `build/`, `_build_cache/`, `.pytest_cache/`,
`.claude/`, `.rtk/`, `*.exe`, `.env`, `settings.json`, `logs/`,
`cache/*` (кроме `__init__.py` и `store.py`), `screenshots/`,
`models/`, `*.ct2/`, `data/`.

**Артефакты вне репозитория**:
- Пользовательские данные: `%APPDATA%\translator-overlay\`
  (`settings.json`, `region_presets.json`, `cache/translations.db`,
  `logs/translator.log`, `app.log`, кастомные доменные профили).
- Модели NLLB: `D:\projects\overlay-translator\models\`
  (`nllb-200-distilled-600M` — исходный HF-чекпоинт 2.31 GiB, нужен для fine-tune;
  `nllb-200-ct2-int8` — CTranslate2 int8, 621 MiB, используется приложением).
  Вне репозитория, не коммитится.

---

## 3. Модули и ответственность

### `main.py` — оркестратор
- `_init_logging() -> str` — DEBUG-лог в `%APPDATA%/translator-overlay/app.log`, до всех импортов.
- `_global_excepthook` / `_thread_excepthook` — логирование необработанных исключений.
- `_preload_torch_dlls()` — предзагрузка DLL torch (нужно для frozen-сборки).
- `class HotkeyBridge(QObject)` — `triggered = pyqtSignal()`; мост из потока `keyboard` в Qt-поток.
- `class TranslationWorker(QThread)` — весь пайплайн в фоне.
  Сигналы: `translation_done(str src, str translated, str error)`,
  `partial_result(str)` (стриминг), `ocr_done(str, QRect)`.
  Конструктор: `(x1, y1, x2, y2, text_override: str|None = None, ocr_only: bool = False)`.
- `class OcrWarmupWorker(QThread)` — прогрев EasyOCR через 3 с после старта.
- `class TranslatorApp` — владеет `QApplication`, `MainWindow`, `TrayIcon`, хоткеями,
  селектором, popup'ами, live-мониторингом и пресет-хоткеями.
  Ключевые методы: `_show_selector`, `_on_region_selected`,
  `_start_translation_pipeline(x1, y1, x2, y2, anchor, text_override=None)`,
  `_on_ocr_preview_requested`, `_toggle_live_monitoring`, `_register_preset_hotkeys`,
  `_on_partial_translation`, `_on_translation_finished`, `_show_result`, `_show_error`,
  `_quit`, `run`.
- `main()` — splash → мастер первого запуска (если нет ключей) → `TranslatorApp(app).run()`.

### `config.py` — конфиг-фасад
Нестандартный приём: в конце модуля `sys.modules[__name__] = _LiveConfig()`,
поэтому `import config; config.TARGET_LANG` читает **свойство**, которое каждый
раз обращается к `settings.config_manager.get(...)`. Присваивание
`config.TARGET_LANG = "en"` сразу пишет в `settings.json`.

- Динамические (settings.json): `HOTKEY`, `TARGET_LANG`, `SOURCE_LANG`,
  `TRANSLATION_ENGINE`, `TRANSLATION_BACKEND`, `NLLB_MODEL_PATH`, `LLM_MODEL`,
  `POPUP_TIMEOUT_SEC`, `NOTIFICATION_TYPE`,
  `OCR_LANGUAGES`, `ACTIVE_DOMAIN`, `PRIMARY_PROVIDER`, `ENABLE_FALLBACK`,
  `ENABLE_STREAMING`, `ENABLE_OCR_PREVIEW`, `COMPACT_PROMPT`, `LLM_MAX_TOKENS`.
- Статические (env/константы): `MAX_RETRIES_PER_PROVIDER`, `RETRY_BACKOFF_BASE_SEC`,
  `OPENROUTER_MODEL`, `ANTHROPIC_DETECT_MODEL`, `APP_VERSION`, `GITHUB_REPO`,
  `SETTINGS_HOTKEY`, `EASYOCR_*`, `OVERLAY_*`, `USER_DATA_DIR`, `CACHE_DIR`,
  `CACHE_MAX_ITEMS`, `LOG_DIR`, `LOG_FILE`.

### `translate/backend.py` — диспетчер бэкендов ★
Единственная точка входа для перевода пользовательского текста. Повторяет
сигнатуры `llm_client`, поэтому вызывающие просто меняют импорт:

```python
translate(text, target_lang=None, source_lang=None, domain_id=None, on_chunk=None) -> str
detect_and_translate(text, target_lang=None, domain_id=None, on_chunk=None) -> tuple[str, str]

get_active_backend() -> str          # "api" | "nllb", читается из config на каждом вызове
take_notice() -> str                 # одноразовое сообщение для UI (thread-local)
preload(backend=None) -> (bool, str) # прогрев модели для индикатора в настройках
reset() -> None                      # сбрасывает оба бэкенда
BACKENDS: list[tuple[str, str]]      # (id, подпись) для комбо в настройках
```

**Политика ошибок локального бэкенда** (согласована с пользователем):
- Модель не найдена / не загрузилась → тихий переход на API + пометка через
  `take_notice()`, которую popup показывает строкой «⚠ …».
- Модель загрузилась, но перевод упал → исключение пробрасывается, popup
  показывает явную ошибку. Никакого скрытого fallback.

Notice хранится в `threading.local()`, потому что переводы идут в QThread-воркерах
и два воркера не должны видеть сообщения друг друга.

### `translate/llm_client.py` — бэкенд перевода через API
Публичный интерфейс (его повторяют диспетчер и локальный бэкенд):

```python
translate(text: str, target_lang: str|None = None, source_lang: str|None = None,
          domain_id: str|None = None, on_chunk: Callable[[str], None]|None = None) -> str

detect_and_translate(text: str, target_lang: str|None = None,
                     domain_id: str|None = None,
                     on_chunk: Callable[[str], None]|None = None) -> tuple[str, str]
                     # -> (detected_lang, translation)

reset_client() -> None          # сброс клиентов и кэша системных промптов
get_provider_chain() -> list[str]
```

Внутри: `_get_client_for(provider)` (ленивый импорт `openai`/`anthropic`),
`_call_provider(...)` (стриминг и не-стриминг пути),
`_call_with_resilience(...)` (retry с экспоненциальным backoff + fallback по цепочке
провайдеров), `_build_system_prompt(domain_id, target_lang, source_lang)` с кэшем,
request coalescing через `_in_flight` (две одновременные одинаковые заявки → один вызов API).

### `translate/nllb_backend.py` — офлайн-бэкенд ★
`class NllbBackend` с тем же публичным интерфейсом, что у `llm_client`,
плюс модульные обёртки `translate()` / `detect_and_translate()` / `reset_client()`
поверх процессного синглтона `get_backend()`.

```python
NllbBackend(model_dir=None, *, device=None, compute_type="int8",
            gpu_compute_type="int8_float16", intra_threads=None, beam_size=4)
    .ensure_loaded()   # ленивая загрузка; поднимает NllbModelUnavailable
    .unload()          # сброс после смены пути в настройках
    .is_loaded / .model_dir / .load_seconds
    .active_device / .cuda_fallback_reason / .take_notice()
    .translate(...) / .detect_and_translate(...)

resolve_model_dir() -> Path | None    # какой каталог будет использован
explicit_model_dir() -> Path | None   # путь из настроек / NLLB_MODEL_DIR
describe_model_location() -> str      # текст для статуса в настройках
is_available() -> bool                # есть ли модель (без её загрузки)
NLLB_LANG_CODES: dict[str, str]       # ISO 639-1 → FLORES-200
```

Исключения: `NllbModelUnavailable` (инфраструктура → fallback на API) и
`NllbTranslationError` (ошибка конкретного перевода → явная ошибка пользователю).

Особенности, отличающие его от API-пути:
- **Ленивая загрузка**: ~620 МБ модели читаются при первом реальном переводе,
  не при импорте и не при старте приложения. Загрузка ~1.2 с, защищена `Lock`.
- **Доменные профили не применяются** — seq2seq-модель не принимает промпты;
  `domain_id` влияет только на ключ кэша.
- **Кэш пишется с суффиксом `"|nllb"`** в `domain_id`, чтобы вывод локальной
  модели не попадал в датасет для fine-tune вместе с API-переводами.
- **Стриминга нет** (CTranslate2 beam search его не даёт): `on_chunk`
  вызывается один раз с готовым текстом, чтобы UI вёл себя единообразно.
- Источник при `source_language=auto` определяется офлайн через `langid`.
- Зависимости только `ctranslate2` + `sentencepiece` — без torch и transformers.
- **GPU is optional** (`device=None` → `NLLB_DEVICE` env → `"auto"`). In auto/cuda mode
  `translate/cuda_support.py` locates `cublas64_12.dll` (pip wheel `nvidia-cublas-cu12`,
  then `CUDA_PATH*`, then the default toolkit dir) and prepends it to `PATH`, because
  CTranslate2 loads cuBLAS via plain `LoadLibrary` and ignores `os.add_dll_directory`.
  cuBLAS loads lazily, so a tiny warm-up translation verifies the GPU. Any failure → CPU
  plus a one-shot notice via `take_notice()` → `translate.backend.take_notice()` → result popup.

Порядок поиска модели: явный путь из настроек → `NLLB_MODEL_DIR` → 
`<проект>/models/nllb-200-ct2-int8` → `%APPDATA%/translator-overlay/models/…` →
`D:\projects\overlay-translator\models\…`. Явно заданный путь авторитетен:
если он неверен, backend сообщает об этом, а не подхватывает другую копию.

### `translate/cuda_support.py` — cuBLAS discovery for the GPU path
```python
candidate_dirs() -> list[Path]      # search order, deduplicated
find_cublas_dir() -> Path | None    # first dir containing cublas64_12.dll
prepare_cuda_libraries() -> Path | None  # prepend that dir to PATH once (Windows only)
cublas_missing_hint() -> str        # user-facing "not found, install …, searched: …"
```
Search order: `<sys.path entry or _MEIPASS>/nvidia/cublas/bin` (pip wheel
`nvidia-cublas-cu12`, see `requirements-gpu.txt`) → `%CUDA_PATH%\bin`,
`%CUDA_PATH_V12_*%\bin` → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.*\bin`.
Only cuBLAS is needed for NLLB; cuDNN/cudart are not. Called only from
`NllbBackend._create_cuda_translator`. The CPU fallback policy lives in
`NllbBackend._create_translator`: a missing GPU in `auto` mode is logged at INFO
with no user notice; every other CUDA failure logs a WARNING and leaves a notice.

### `translate/domain_manager.py`
`load_domain_profile(domain_id) -> dict`, `list_available_domains() -> list[dict]`,
`save_custom_profile(...)`, `delete_custom_profile(domain_id) -> bool`,
`generate_slug(display_name) -> str`.
Встроенные профили — `translate/domain_profiles/*.json`, пользовательские —
в `%APPDATA%\translator-overlay\`.
Формат: `{display_name, system_prompt, few_shot_examples: [{source, translation}]}`.

### `translate/lang_detect.py`
`detect_script(text) -> str`,
`is_same_language(text, target_lang, source_lang=...) -> (bool, str)`
(fast-path: если исходный язык совпадает с целевым, API не вызывается),
`LangDetector` (ABC) → `LangidDetector`, `LLMDetector`; `get_detector(engine)`.

### `cache/store.py` — SQLite-кэш и история
Двухуровневый: L1 `OrderedDict` LRU (128 записей) + L2 SQLite (WAL),
по одному соединению на поток.

```sql
CREATE TABLE translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_text     TEXT NOT NULL,
    source_lang     TEXT NOT NULL,      -- ISO-код или "_auto"
    target_lang     TEXT NOT NULL,
    domain_id       TEXT NOT NULL DEFAULT 'general',
    translated_text TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    UNIQUE(source_text, source_lang, target_lang, domain_id)
);
```

API: `get_cached(text, src, tgt, *, domain_id='general') -> str|None`,
`save_to_cache(text, src, tgt, translation, *, domain_id='general')`,
`warm_cache(limit=50) -> int`, `get_all_history(limit=200) -> list[dict]`,
`clear_history()`.
Размер ограничен `config.CACHE_MAX_ITEMS` (вытеснение старейших по `timestamp`).
Файл БД: `%APPDATA%\translator-overlay\cache\translations.db`.

### `settings/` — персистентность
- `config_manager`: `DEFAULTS` (канонический список ключей — **неизвестные ключи
  при сохранении отбрасываются**), `load_config()`, `save_config(cfg)`,
  `get(key)`, `set_value(key, value)`. Файл: `%APPDATA%\translator-overlay\settings.json`.
- `settings/__init__.py`: `get_api_key(provider)`, `set_api_key`, `delete_api_key`,
  `has_any_key()`, `get_primary_provider()`, `save_primary_provider()`,
  `is_fallback_enabled()`, `set_fallback_enabled()`.
- `region_presets.py`: `load_presets()`, `save_preset(...)`, `delete_preset(id)`,
  `rename_preset(id, name)`, `update_preset_hotkey(id, hotkey)`, `validate_hotkey(...)`.
  Файл: `%APPDATA%\translator-overlay\region_presets.json`.

### `ocr/engine.py`
`get_reader()` — ленивый singleton EasyOCR, `preprocess(img, scale=1) -> np.ndarray`,
`extract_text(image) -> str`, `recognise(img, lang=None) -> str` (публичная точка входа),
`_extract_strips` — разрезание высоких областей на полосы для точности.

### `ui/`
- `MainWindow` (sidebar: `PAGE_HOME` / `PAGE_HISTORY` / `PAGE_SETTINGS`),
  `show_and_switch(page)`, `set_tray_icon(tray)`; воркеры `_TextTranslateWorker`,
  `_ImageTranslateWorker`, `_UpdateCheckWorker`.
- `SettingsWidget` — все настройки; методы `_build_ui()`, `_load_current()`,
  `_on_save()`, `reload()`, `_css(extra)`; константы `_SOURCE_LANGUAGES`,
  `_TARGET_LANGUAGES`, `_ENGINES`, `_OPENROUTER_MODELS`, `_MODEL_HINTS`.
  Секции: «API-ключ и провайдеры», «Перевод», далее OCR / интерфейс / обновления.
  Стилизация — тёмная тема, `QGroupBox` + `self._INPUT_CSS` / `self._GROUP_CSS`.
- `ResultPopup(...)` — frameless-окно, стриминговое обновление через `update_content()`,
  авто-закрытие по `config.POPUP_TIMEOUT_SEC`, resize за края, TTS, копирование.

---

## 4. Поток данных

```
[keyboard hotkey, фоновый поток]
        │ HotkeyBridge.triggered (в Qt-поток)
        ▼
TranslatorApp._show_selector()
        ▼
overlay.selector.RegionSelector  ──region_selected(x1,y1,x2,y2)──►
        ▼
TranslatorApp._on_region_selected → _start_translation_pipeline(...)
        ▼
TranslationWorker(QThread).run():
   1. capture.screenshot.capture_region()       → PIL.Image
   2. ocr.engine.recognise()                    → str
      └─ если config.ENABLE_OCR_PREVIEW → ocr_done → OcrPreviewPopup →
         повторный запуск пайплайна с text_override
   3. translate.backend:
      SOURCE_LANG == "auto" ? detect_and_translate() : translate()
         │
         ├─ config.TRANSLATION_BACKEND == "api"  → translate.llm_client
         │     ├─ fast-path: lang_detect.is_same_language → возврат без API
         │     ├─ cache.store.get_cached()            → возврат при попадании
         │     ├─ coalescing по (text, src, tgt, domain)
         │     ├─ _call_with_resilience → провайдер #1 (retry) → провайдер #2
         │     └─ cache.store.save_to_cache()
         │
         └─ config.TRANSLATION_BACKEND == "nllb" → translate.nllb_backend
               ├─ ensure_loaded() — ленивая загрузка модели (~1.2 с)
               │     ├─ device auto/cuda: GPU + cuBLAS found + warm-up OK → CUDA
               │     │     └─ any CUDA failure → CPU + one-shot notice via take_notice()
               │     └─ NllbModelUnavailable → уходим на llm_client + take_notice()
               ├─ fast-path / cache (domain_id + "|nllb")
               ├─ langid при source=auto → FLORES-код
               └─ CTranslate2 translate_batch (beam=4; GPU int8_float16 or CPU int8)
        ▼ сигналы
partial_result   → ResultPopup.update_content()   (живой стриминг, только API)
translation_done → _on_translation_finished → _show_result(notice=…) / _show_error
                   notice = TranslationWorker.backend_notice (из backend.take_notice())
                   → ResultPopup показывает строку «⚠ …» под переводом
```

**Где живёт состояние**

| Состояние | Где |
|---|---|
| Пользовательские настройки | `%APPDATA%\translator-overlay\settings.json` (+ `config_manager._cache` в памяти) |
| API-ключи | OS keyring, сервис `OverlayTranslator`; fallback — `.env` |
| Кэш переводов и история | `%APPDATA%\translator-overlay\cache\translations.db` + L1 LRU в процессе |
| Пресеты областей | `%APPDATA%\translator-overlay\region_presets.json` |
| Кастомные доменные профили | `%APPDATA%\translator-overlay\` (JSON) |
| Логи | `%APPDATA%\translator-overlay\app.log`, `logs/translator.log` |
| Выбор бэкенда и путь к модели | `settings.json`: `translation_backend`, `nllb_model_path` |
| Клиенты LLM, кэш системных промптов | модульные глобалы `translate/llm_client.py` (сброс — `reset_client()`) |
| Загруженная модель NLLB | синглтон `translate/nllb_backend._backend` (сброс — `reset_client()`; оба сразу — `translate.backend.reset()`) |
| Разовое уведомление о fallback | `threading.local()` в `translate/backend.py` |
| Синглтон EasyOCR | модульный глобал `ocr/engine.py` |

---

## 5. Точки конфигурации

1. **`settings/config_manager.DEFAULTS`** — канонический список ключей.
   Новая настройка = запись в `DEFAULTS` (иначе `save_config()` её отбросит)
   + свойство в `config._LiveConfig` + контрол в `ui/settings_dialog.SettingsWidget`
   (`_build_ui` → `_load_current` → `_on_save`).
2. **Выбор бэкенда перевода** — `settings.json`:
   - `translation_backend`: `"api"` (по умолчанию) | `"nllb"`;
   - `nllb_model_path`: явный путь к каталогу CTranslate2 (`""` = автопоиск).
   Меняется в «Настройки → Бэкенд перевода»; там же кнопка «Загрузить модель»
   с индикатором и статусом наличия модели. Переменная окружения
   `NLLB_MODEL_DIR` переопределяет путь без правки настроек.
   `NLLB_DEVICE` (`auto` by default | `cuda` | `cpu`) picks the inference device; it is
   env-only and has no UI control.
3. **`.env`** (см. `.env.example`) — ключи API и статические оверрайды
   (`EASYOCR_*`, `OVERLAY_*`, `CACHE_DIR`, `LOG_DIR`, `SETTINGS_HOTKEY`, `GITHUB_REPO`).
4. **Keyring** — рабочее хранилище ключей API (`settings.set_api_key`).
5. **`translate/domain_profiles/*.json`** — системные промпты и few-shot по доменам.
6. **`region_presets.json`** — сохранённые области и их индивидуальные хоткеи.
7. **`build*.spec` / `build.py`** — параметры PyInstaller-сборки.

После сохранения настроек `SettingsWidget._on_save` вызывает
`translate.backend.reset()` — он сбрасывает и LLM-клиентов, и загруженную
модель NLLB, поэтому новый провайдер/модель/путь подхватываются со следующего
запроса.

---

## 6. Внешние зависимости и где они вызываются

| Сервис / библиотека | Где вызывается |
|---|---|
| **OpenRouter API** (`openai` SDK, `base_url=https://openrouter.ai/api/v1`) | `translate/llm_client.py::_get_client_for`, `_call_provider` |
| **Anthropic API** (`anthropic` SDK) | `translate/llm_client.py::_get_client_for`, `_call_provider` |
| **GitHub Releases API** | `updater/check_update.py::check_for_update` (репозиторий из `config.GITHUB_REPO`) |
| **EasyOCR / torch** (локально; веса качаются при первом запуске) | `ocr/engine.py::get_reader` |
| **CTranslate2 + sentencepiece** (локально, офлайн) | `translate/nllb_backend.py::NllbBackend.ensure_loaded` / `_raw_translate` |
| **cuBLAS 12** (optional; `nvidia-cublas-cu12` wheel or CUDA Toolkit 12.x) | `translate/cuda_support.py::prepare_cuda_libraries`, loaded lazily by CTranslate2 on the first GPU matmul |
| **langid** (локально) | `translate/lang_detect.py::LangidDetector`, `nllb_backend._detect_source` |
| **keyring** (Windows Credential Manager) | `settings/__init__.py::_get_keyring` |
| **mss** (захват экрана) | `capture/screenshot.py` |
| **TTS (SAPI)** | `tts/engine.py::speak` |

Все сетевые SDK и `ctranslate2` импортируются **лениво**, чтобы не замедлять
старт приложения. Локальный бэкенд не ходит в сеть вообще.

Только для оффлайн-утилит (в `requirements-dev.txt`, в приложение не входят):
`transformers` + `torch` — конвертация HF-чекпоинта в CTranslate2;
`sacrebleu` — метрика chrF в `scripts/baseline_eval_nllb.py`.

---

## 7. Известные ограничения и TODO

- **Фактически только Windows**: `keyboard`-хоткеи, keyring, скрытие консоли,
  пути `%APPDATA%`, `.ico`-иконка.
- `config.py` подменяет себя в `sys.modules` — нестандартно; статические анализаторы
  и IDE не видят атрибуты, `from config import X` ведёт себя не так, как ожидается.
- Движки `llm_vision` и `api` присутствуют в `_ENGINES` (UI), но пайплайн
  `TranslationWorker` фактически всегда идёт по пути OCR → LLM-текст.
- Локальный бэкенд NLLB **не использует доменные профили** (промпты и few-shot):
  seq2seq-модель их не принимает, поэтому контекст перевода на неё не влияет —
  это и есть задача предстоящего fine-tune.
- У локального бэкенда нет стриминга: popup показывает результат целиком.
- `langid` ошибается на коротких и зашумлённых OCR-строках (например, польское
  `idziemy na raid` определяется как `en`), а от этого напрямую зависит качество
  NLLB-перевода при `source_language=auto`.
- Качество NLLB без дообучения на игровом сленге низкое (`healer` → «врач»,
  `boss is enraged` → «начальник злится») — см. `docs/baseline_eval.md`.
- Кэш и история — одна и та же таблица; отдельной «истории» с метаданными
  (провайдер, модель, длительность) нет. Бэкенд различается только суффиксом
  `"|nllb"` в `domain_id` — по нему `scripts/export_history_dataset.py` отсеивает
  собственный вывод модели из обучающей выборки.
- Истории накоплено мало и она почти целиком состоит из тестовых строк, поэтому
  baseline в `docs/baseline_eval.md` посчитан на 6 парах и статистически незначим.
  Его надо пересчитать после реального использования приложения.
- Тестами не покрыты: UI-слой, `cache/store.py`, `main.py`, `capture/`, `tts/`,
  `updater/`, `translate/backend.py`, `translate/nllb_backend.py` (only its device
  selection / CPU fallback is covered, by `tests/test_cuda_support.py`).
- **The backend choice is saved only by "Сохранить".** "Загрузить модель" persists
  just `nllb_model_path` (and rewrites the file with the old `translation_backend`),
  while its status line suggests the local model is active. Leaving the page then
  makes `reload()` show "API" again. This is a UX bug and has not been fixed yet.
- **Open: the app crashed once after the second NLLB translation** (2026-09-23 21:32,
  WER: `Qt5Core.dll`, `0xc0000409` subcode 7 = `qFatal` → `abort()`), after
  `NLLB OK` had been logged. Not reproduced headless. Main suspect:
  `_HomePage._on_text_translated` drops the last reference to a `QThread` that is
  still running. Diagnostics added for the next occurrence: Qt messages go to
  `app.log` (`qInstallMessageHandler` in `main.py`); `faulthandler` writes all
  thread stacks to `%APPDATA%\translator-overlay\crash.log`; worker/inference
  DEBUG logs in `ui/main_window.py` and `nllb_backend._raw_translate`.
- `nllb_backend._auto_model_dirs()` still contains a developer-machine path
  (`D:\projects\overlay-translator\models`), harmless elsewhere but should go.
- Два теста в `tests/test_domain_profiles.py` падали ещё до работ по NLLB
  (проверяют старые тексты профиля `game`), ещё три файла не импортируются
  без `pytest`/`easyocr` в окружении.
- Жёстко зашитый `HTTP-Referer` в заголовках OpenRouter указывает на плейсхолдер-репозиторий.

---

## 8. Тесты

Расположение: `tests/`. Стиль — `unittest.TestCase`, запускаются и через pytest.

| Файл | Покрытие |
|---|---|
| `tests/test_ocr.py` | препроцессинг, сортировка боксов, `_resolve_gpu`, фильтр по confidence (мок Reader) |
| `tests/test_lang_detect.py` | детекция script/языка, fast-path «тот же язык» |
| `tests/test_llm_resilience.py` | классификация ошибок, retry/backoff, переход по цепочке провайдеров |
| `tests/test_domain_profiles.py` | загрузка/слияние доменных профилей |
| `tests/test_region_presets.py` | CRUD пресетов, валидация имён/координат/хоткеев |
| `tests/test_cuda_support.py` | cuBLAS search order, PATH preparation, NLLB CPU fallback for every CUDA failure mode (fake `ctranslate2`, no GPU needed) |

Запуск:

```bash
py -m unittest discover -s tests -p "test_*.py" -v
# или
pytest tests/ -v
```

Отдельного `pytest.ini` / `pyproject.toml` нет — запускать из корня проекта
(модули импортируются как top-level пакеты).

---

## 9. Локальная модель: утилиты и рабочий цикл

Всё в `scripts/`, в сборку приложения не входит. Запускать из корня проекта
интерпретатором venv.

### Конвертация HF-чекпоинта в CTranslate2 int8
Разовая операция; требует `transformers` + `torch` из `requirements-dev.txt`.

```bash
ct2-transformers-converter   --model  D:/projects/overlay-translator/models/nllb-200-distilled-600M   --output_dir D:/projects/overlay-translator/models/nllb-200-ct2-int8   --quantization int8   --copy_files tokenizer.json tokenizer_config.json special_tokens_map.json                sentencepiece.bpe.model generation_config.json
```

Результат: 2.31 GiB (fp32) → 621 MiB (int8), −73.8%.
Исходный чекпоинт **не удалять** — он нужен для fine-tune.

### `scripts/test_nllb_translation.py`
Smoke-тест модели: грузит её, переводит игровые фразы по парам из
en/de/fr/es/ru/uk/be/pl/cs/hu, печатает время инференса на CPU.
Зависит только от `ctranslate2` + `sentencepiece`.

```bash
python scripts/test_nllb_translation.py [--model DIR] [--threads N] [--beam N]
```

### `scripts/export_history_dataset.py`
История SQLite → JSONL для fine-tune: `{"source", "target", "src_lang", "tgt_lang"}`.
Отбрасывает строки локальной модели (`domain_id` с суффиксом `|nllb`), пары
«исходник == перевод», пустые и дубликаты; `source_lang` вида `_auto` / `auto`
доопределяет через `langid`.

```bash
python scripts/export_history_dataset.py   [--db PATH] [--out data/history_pairs.jsonl] [--domain game]   [--lang-format iso|flores] [--with-metadata] [--val-ratio 0.1] [--include-nllb]
```

### `scripts/baseline_eval_nllb.py`
Прогон необученной NLLB по экспортированным парам + chrF (sacrebleu) и
side-by-side примеры. Пишет отчёт в `docs/baseline_eval.md`.

```bash
python scripts/baseline_eval_nllb.py [--dataset ...] [--sample 30] [--seed 13]
```

Эталон в датасете — перевод API-бэкенда, а не человека, поэтому chrF измеряет
**совпадение с API**, а не абсолютное качество. Значение имеет только разница
между прогонами до и после fine-tune с одним и тем же `--seed`.

### Переключение бэкенда в приложении
«Настройки → Бэкенд перевода»: радиокнопки «API (Anthropic / OpenRouter)» и
«Локальная модель (NLLB)», поле пути к модели и кнопка «Загрузить модель»
с индикатором. Выбор сохраняется в `settings.json`
(`translation_backend`, `nllb_model_path`) и переживает перезапуск.
Only the "Сохранить" button writes `translation_backend`; see the known issue in section 7.
The status line shows the device the model actually runs on (`Device: CUDA/CPU`)
and, after a CPU fallback, the reason.

---

_Создано: 2026-09-23. Обновлено: 2026-09-23 (локальный NLLB-бэкенд, переключение
бэкендов, скрипты экспорта и baseline-оценки; optional CUDA with CPU fallback,
crash diagnostics)._
_Обновляй при значимых структурных изменениях._
