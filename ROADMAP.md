**Русский** · [English](#overlay-translator--roadmap-to-a-product-and-an-mlops-portfolio)

# Overlay-Translator — план развития до продукта и MLOps-портфолио

Цель: превратить проект в (1) приложение, которым хотят пользоваться, и (2) сильный MLOps-кейс для резюме и диплома.

Условные обозначения: `[ ]` — не сделано, `[x]` — сделано. Оценка в рабочих днях при ~3–4 часах в день.

Предстоящие работы разделены на две части: **A — локальная модель (NLLB)** и **B — приложение и остальное**. Нумерация этапов сквозная: 0–1 — сделано, 2–10 — часть A, 11–14 — часть B; порядок и зависимости — в сводке.

---

## Сделано

Полностью закрытые этапы.

### Этап 0. Гигиена репозитория

**Срок:** 1–2 дня

**Зачем:** без этого проект выглядит заброшенным, а вклад участников размазан по разным именам.

- [x] Добавить `.mailmap`: объединить `Kyrylo Bankovskyi`, `Kyrylo Bankvoskyi`, `Kyrylo` в одну личность; `Alhite`, `Gdx177303`, `Oleksandr` — в другую
- [x] Добавить `LICENSE` (MIT или Apache-2.0; для модели — отдельно указать лицензию NLLB, CC-BY-NC 4.0)
- [x] Добавить `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, шаблоны issue и PR
- [x] Убрать устаревшее из README: структура `translator-overlay/`, `settings.py`, описание popup «original + translation», `your-username` в clone-команде
- [x] Убрать из `requirements-train.txt` привязку к китайскому зеркалу и локальные пути; вынести в комментарий «как установить CUDA torch»
- [x] Убрать хардкод `D:\projects\overlay-translator\...` из `training/finetune_lora.py` и docs (заменить на аргумент или переменную окружения)
- [x] Включить защиту ветки `main` (PR + зелёный CI)

**Критерий готовности:** в `git shortlog -sn` два человека; в репозитории нет путей `D:\`; README не противоречит коду.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 1. CI и качество кода

**Срок:** 2–3 дня

- [x] `pyproject.toml` с метаданными, зависимостями и настройками ruff/pytest/mypy
- [x] Pre-commit: ruff (lint + format), trailing whitespace, проверка больших файлов
- [x] GitHub Actions `ci.yml`: ruff, pytest на Windows и Linux (Qt-тесты через `QT_QPA_PLATFORM=offscreen`)
- [x] Отметить в тестах те, что требуют GPU/модель, маркером `@pytest.mark.slow` и не гонять их в обычном CI
- [x] Добавить недостающие тесты: `translate/backend.py` (выбор бэкенда и fallback), `nllb_backend` с подменой модели, `cache/store.py`, `training/build_dataset*.py` (сплиты без утечки), метрики в `training/evaluate.py`
- [x] Бейджи CI и покрытия в README
- [x] Coverage отчёт (pytest-cov), цель — не ниже 60% для `translate/`, `cache/`, `settings/`

**Критерий готовности:** PR нельзя смержить с красным CI; покрытие видно в README.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Часть A. Локальная модель (NLLB)

Подробный план вынесен в [ROADMAP-MODEL.md](ROADMAP-MODEL.md): этапы 2–10 (данные, обучение, оценка, реестр, GPU-сборка, мониторинг, сервис). Порядок и зависимости — в сводке ниже.

---

## Часть B. Приложение и остальное

Приложение, продукт и документация, публикация. От работ над моделью зависит только там, где это указано в «Зависимостях».

### Этап 11. Релиз приложения

**Срок:** 4–6 дней

- [x] GitHub Actions `release.yml`: сборка PyInstaller на `windows-latest` по тегу `v*`, загрузка артефактов в GitHub Release
- [x] Установщик (Inno Setup или MSIX), ярлык, деинсталлятор; рассмотреть подпись кода
- [x] Мастер первого запуска: выбор режима (API / офлайн), кнопка «Скачать офлайн-модель» с прогрессом и проверкой sha256
- [x] Проверка работы апдейтера на реальном релизе (сейчас релизов нет)
- [x] Changelog (`CHANGELOG.md`, Keep a Changelog) и SemVer-теги
- [x] Тестирование на чистой Windows (виртуалка): установка → первый запуск → перевод → удаление
- [x] Выпустить `v1.0.0`

**Критерий готовности:** незнакомый человек скачивает установщик со страницы релиза и переводит текст за пять минут без терминала.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 12. Продукт и документация

**Срок:** 3–5 дней

- [x] Интерфейс на английском и русском (i18n через `QTranslator` или простой словарь), выбор языка в настройках
- [x] Демо-GIF (до 10 МБ) и скриншоты в README: офлайн-перевод `lf2m`, `wts … pm me`, live-режим
- [x] README: первым экраном — ценность и установка в 3 шага; ниже — режимы, приватность, FAQ, ограничения
- [x] Раздел «Как это работает» с диаграммой пайплайна (OCR → glossary → NLLB → popup) и MLOps-диаграммой (data → train → eval → registry → app)
- [x] `docs/` как сайт (GitHub Pages / MkDocs): установка, настройка, обучение, воспроизведение экспериментов
- [x] Страница «Приватность»: что уходит в API, что остаётся локально, как работает логирование
- [x] Обработка типовых проблем в FAQ: нет GPU, антивирус, нет прав на хоткеи

**Критерий готовности:** новый пользователь и новый разработчик находят всё нужное в README и docs без вопросов вам.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 13. Голосовой перевод

**Срок:** 8–12 дней

**Зачем:** переводить не только текст на экране, но и речь (Discord, игры, видео) — живыми субтитрами, а при желании и озвучкой. Подробный план прототипа — [docs/VOICE_TRANSLATION_PROTOTYPE.md](docs/VOICE_TRANSLATION_PROTOTYPE.md).

- [ ] Прототип в `scratch/voice/` (вне приложения): тестовый набор из 20–30 фраз, синтезированных через SAPI, плюс тишина, музыка и шум для проверки галлюцинаций
- [ ] Офлайн-бенчмарк `bench_stt.py`: VAD (Silero) → `faster-whisper` → `translate.backend`; модели `tiny.en` / `base.en` / `small.en` / `small` × CPU / CUDA — real-time factor, WER, латентность от конца фразы до перевода
- [ ] Живой захват через WASAPI loopback и микрофон (`live.py`); проверка эха озвучки и нагрузки на CPU / GPU / RAM
- [ ] Решение go / no-go по результатам: модель и устройство по умолчанию, начинать ли только с субтитров
- [ ] Зависимости без конфликтов: `faster-whisper` ставится с `--no-deps` (иначе он тянет обычный `onnxruntime` поверх `onnxruntime-directml` и OCR теряет DirectML), `av` и `tokenizers` — явно в `requirements.txt`; для GPU `translate/cuda_download.py` докачивает cuDNN 9 вместе с cuBLAS
- [ ] Живые субтитры: пакет `audio/` (захват, VAD, STT-воркер на `QThread`, результаты через сигналы) и окно-полоса субтитров
- [ ] Настройки: источник, модель, устройство, язык (`DEFAULTS` + `_LiveConfig` + `SettingsWidget`); по умолчанию выключено; модель Whisper скачивается только по явному действию пользователя, как NLLB
- [ ] Опциональная озвучка перевода (TTS) с выбором устройства вывода и защитой от эха
- [ ] Приватность: аудио и транскрипты не логируются целиком, облачный STT — только по явному выбору; обновить `ARCHITECTURE.md`, `docs/privacy.md`, `requirements*.txt`

**Критерий готовности:** перевод фразы появляется в субтитрах не позже ~3 с после её окончания; функция выключена по умолчанию и не ходит в сеть без явного действия пользователя.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 14. Резюме, диплом и публикация

**Срок:** 3–4 дня

- [ ] Раздел «MLOps» в README: диаграмма жизненного цикла, ссылки на трекер, DVC, HF-модели, CI
- [ ] Технический отчёт или статья (Medium/dev.to/Habr): задача, данные, обучение, оценка, провалы, выводы
- [ ] (опционально) Структура диплома: проблема → данные и глоссарий → метод (LoRA + препроцессор) → оценка → инженерная часть (CI/CD, реестр, мониторинг) → результаты и ограничения
- [ ] Формулировки для резюме (3–4 пункта с цифрами: прирост chrF, keep-rate, латентность, покрытие тестами)
- [ ] Закреплённый репозиторий на GitHub-профиле, актуальный профильный README
- [ ] Короткое видео-демо (1–2 минуты)
- [ ] Чёткое описание вклада: что сделано лично вами (обучение, оценка, глоссарий, интеграция NLLB), что — командой

**Критерий готовности:** по ссылке на репозиторий рекрутер за две минуты видит задачу, результат и инженерную зрелость.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Сводка

| Этап | Часть | Название | Срок, дней | Исполнитель |
|---|---|---|---|---|
| 0 | сделано | Гигиена репозитория | 1–2 | |
| 1 | сделано | CI и качество кода | 2–3 | |
| 2 | A | Воспроизводимое обучение | 4–6 | |
| 3 | A | Трекинг экспериментов | 2–3 | |
| 4 | A | Честная оценка качества | 4–7 | |
| 5 | A | Модель v3 | 5–8 | |
| 6 | A | Реестр моделей и манифест | 2–3 | |
| 7 | A | CI/CD для модели | 3–4 | |
| 8 | A | Сборка с GPU для локальной модели | 1–2 | |
| 9 | A | Мониторинг модели | 2–3 | |
| 10 | A | Сервис инференса | 3–5 | |
| 11 | B | Релиз приложения (сделано) | 4–6 | |
| 12 | B | Продукт и документация (сделано) | 3–5 | |
| 13 | B | Голосовой перевод | 8–12 | |
| 14 | B | Резюме, диплом, публикация | 3–4 | |

**Рекомендуемый порядок:** 0 → 1 → 2 → 3 → 4 → 6 → 7 → 8 → 5 → 9 → 10 → 14 (11 и 12 уже сделаны).
Части A и B можно вести параллельно; этап 13 (голосовой перевод) не зависит от работ над моделью. Минимальный набор для сильного резюме: этапы 0–4, 6–8 и 14. Этапы 5, 9, 10 и 13 усиливают проект, но их можно отложить.

**Зависимости:** этап 4 нужен до 5 и 7; этап 6 нужен до 7 и 8; этап 2 нужен до 3 и 5; этап 8 (cuBLAS) желателен до 13 — Whisper на GPU использует cuBLAS, но дополнительно требует cuDNN 9.

---
---

[Русский](#overlay-translator--план-развития-до-продукта-и-mlops-портфолио) · **English**

# Overlay-Translator — roadmap to a product and an MLOps portfolio

Goal: turn the project into (1) an app people want to use and (2) a strong MLOps case for a CV and a thesis.

Legend: `[ ]` — not done, `[x]` — done. Estimates are in working days at ~3–4 hours a day.

Upcoming work is split into two parts: **A — the local model (NLLB)** and **B — the app and the rest**. Stages are numbered straight through: 0–1 — done, 2–10 — part A, 11–14 — part B; order and dependencies are in the summary.

---

## Done

Fully closed stages.

### Stage 0. Repository hygiene

**Time:** 1–2 days

**Why:** without it the project looks abandoned, and contributors' work is spread over different names.

- [x] Add `.mailmap`: merge `Kyrylo Bankovskyi`, `Kyrylo Bankvoskyi`, `Kyrylo` into one identity; `Alhite`, `Gdx177303`, `Oleksandr` into another
- [x] Add `LICENSE` (MIT or Apache-2.0; state the NLLB licence for the model separately, CC-BY-NC 4.0)
- [x] Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue and PR templates
- [x] Remove outdated parts of the README: the `translator-overlay/` tree, `settings.py`, the "original + translation" popup description, `your-username` in the clone command
- [x] Drop the Chinese mirror and local paths from `requirements-train.txt`; move "how to install CUDA torch" into a comment
- [x] Remove the hardcoded `D:\projects\overlay-translator\...` from `training/finetune_lora.py` and the docs (replace with an argument or an environment variable)
- [x] Protect the `main` branch (PR + green CI)

**Done when:** `git shortlog -sn` shows two people; the repository has no `D:\` paths; the README does not contradict the code.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 1. CI and code quality

**Time:** 2–3 days

- [x] `pyproject.toml` with metadata, dependencies and ruff/pytest/mypy settings
- [x] Pre-commit: ruff (lint + format), trailing whitespace, large-file check
- [x] GitHub Actions `ci.yml`: ruff, pytest on Windows and Linux (Qt tests with `QT_QPA_PLATFORM=offscreen`)
- [x] Mark tests that need a GPU or a model with `@pytest.mark.slow` and skip them in regular CI
- [x] Add missing tests: `translate/backend.py` (backend choice and fallback), `nllb_backend` with a stubbed model, `cache/store.py`, `training/build_dataset*.py` (splits without leakage), metrics in `training/evaluate.py`
- [x] CI and coverage badges in the README
- [x] Coverage report (pytest-cov), target at least 60% for `translate/`, `cache/`, `settings/`

**Done when:** a PR cannot be merged with red CI; coverage is visible in the README.

**Owner:** ______________________________

**Due:** ______________________________

---

## Part A. Local model (NLLB)

The detailed plan is in [ROADMAP-MODEL.md](ROADMAP-MODEL.md): stages 2–10 (data, training, evaluation, registry, GPU build, monitoring, service). Order and dependencies are in the summary below.

---

## Part B. App and the rest

The app, product and documentation, publication. It depends on the model work only where the dependencies below say so.

### Stage 11. App release

**Time:** 4–6 days

- [x] GitHub Actions `release.yml`: PyInstaller build on `windows-latest` for `v*` tags, artifacts uploaded to a GitHub Release
- [x] Installer (Inno Setup or MSIX), shortcut, uninstaller; consider code signing
- [x] First-run wizard: mode choice (API / offline), a "Download offline model" button with progress and a sha256 check
- [x] Check the updater against a real release (there are no releases yet)
- [x] Changelog (`CHANGELOG.md`, Keep a Changelog) and SemVer tags
- [x] Test on a clean Windows (VM): install → first launch → translation → uninstall
- [x] Release `v1.0.0`

**Done when:** a stranger downloads the installer from the release page and translates text within five minutes without a terminal.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 12. Product and documentation

**Time:** 3–5 days

- [x] English and Russian interface (i18n via `QTranslator` or a simple dictionary), language choice in settings
- [x] Demo GIF (up to 10 MB) and screenshots in the README: offline translation of `lf2m`, `wts … pm me`, live mode
- [x] README: the first screen shows the value and a 3-step install; below — modes, privacy, FAQ, limitations
- [x] A "How it works" section with a pipeline diagram (OCR → glossary → NLLB → popup) and an MLOps diagram (data → train → eval → registry → app)
- [x] `docs/` as a site (GitHub Pages / MkDocs): installation, configuration, training, reproducing experiments
- [x] A "Privacy" page: what goes to the API, what stays local, how logging works
- [x] Common problems in the FAQ: no GPU, antivirus, no rights for hotkeys

**Done when:** a new user and a new developer find everything they need in the README and docs without asking you.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 13. Voice translation

**Time:** 8–12 days

**Why:** translate speech too (Discord, games, videos), not only on-screen text — as live subtitles and optionally as voice-over. The detailed prototype plan is [docs/VOICE_TRANSLATION_PROTOTYPE.md](docs/VOICE_TRANSLATION_PROTOTYPE.md).

- [ ] Prototype in `scratch/voice/` (outside the app): a test set of 20–30 phrases synthesised with SAPI, plus silence, music and noise for the hallucination check
- [ ] Offline benchmark `bench_stt.py`: VAD (Silero) → `faster-whisper` → `translate.backend`; models `tiny.en` / `base.en` / `small.en` / `small` × CPU / CUDA — real-time factor, WER, end-of-phrase → translation latency
- [ ] Live capture via WASAPI loopback and the microphone (`live.py`); check the voice-over echo and the CPU / GPU / RAM load
- [ ] Go / no-go decision from the results: default model and device, whether to start with subtitles only
- [ ] Conflict-free dependencies: `faster-whisper` is installed with `--no-deps` (otherwise it pulls the plain `onnxruntime` over `onnxruntime-directml` and the OCR loses DirectML), `av` and `tokenizers` go into `requirements.txt` explicitly; for the GPU `translate/cuda_download.py` fetches cuDNN 9 next to cuBLAS
- [ ] Live subtitles: an `audio/` package (capture, VAD, an STT worker on a `QThread`, results via signals) and a subtitle strip window
- [ ] Settings: source, model, device, language (`DEFAULTS` + `_LiveConfig` + `SettingsWidget`); off by default; the Whisper model is downloaded only by an explicit user action, like NLLB
- [ ] Optional translation voice-over (TTS) with an output-device choice and echo protection
- [ ] Privacy: audio and transcripts are never logged in full, cloud STT only by explicit choice; update `ARCHITECTURE.md`, `docs/privacy.md`, `requirements*.txt`

**Done when:** a phrase's translation shows up in the subtitles within ~3 s of its end; the feature is off by default and never goes to the network without an explicit user action.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 14. CV, thesis and publication

**Time:** 3–4 days

- [ ] An "MLOps" section in the README: lifecycle diagram, links to the tracker, DVC, HF models, CI
- [ ] A technical report or article (Medium/dev.to/Habr): task, data, training, evaluation, failures, conclusions
- [ ] (optional) Thesis outline: problem → data and glossary → method (LoRA + preprocessor) → evaluation → engineering (CI/CD, registry, monitoring) → results and limitations
- [ ] CV bullet points (3–4 with numbers: chrF gain, keep-rate, latency, test coverage)
- [ ] The repository pinned on the GitHub profile, an up-to-date profile README
- [ ] A short video demo (1–2 minutes)
- [ ] A clear statement of contribution: what you did personally (training, evaluation, glossary, NLLB integration) and what the team did

**Done when:** from the repository link a recruiter sees the task, the result and the engineering maturity within two minutes.

**Owner:** ______________________________

**Due:** ______________________________

---

## Summary

| Stage | Part | Name | Days | Owner |
|---|---|---|---|---|
| 0 | done | Repository hygiene | 1–2 | |
| 1 | done | CI and code quality | 2–3 | |
| 2 | A | Reproducible training | 4–6 | |
| 3 | A | Experiment tracking | 2–3 | |
| 4 | A | Honest quality evaluation | 4–7 | |
| 5 | A | Model v3 | 5–8 | |
| 6 | A | Model registry and manifest | 2–3 | |
| 7 | A | Model CI/CD | 3–4 | |
| 8 | A | GPU build for the local model | 1–2 | |
| 9 | A | Model monitoring | 2–3 | |
| 10 | A | Inference service | 3–5 | |
| 11 | B | App release (done) | 4–6 | |
| 12 | B | Product and documentation (done) | 3–5 | |
| 13 | B | Voice translation | 8–12 | |
| 14 | B | CV, thesis, publication | 3–4 | |

**Recommended order:** 0 → 1 → 2 → 3 → 4 → 6 → 7 → 8 → 5 → 9 → 10 → 14 (11 and 12 are done).
Parts A and B can run in parallel; stage 13 (voice translation) does not depend on the model work. The minimum for a strong CV: stages 0–4, 6–8 and 14. Stages 5, 9, 10 and 13 strengthen the project but can wait.

**Dependencies:** stage 4 is needed before 5 and 7; stage 6 before 7 and 8; stage 2 before 3 and 5; stage 8 (cuBLAS) is useful before 13 — Whisper on the GPU uses cuBLAS but also needs cuDNN 9.
