**Русский** · [English](#overlay-translator--roadmap-to-a-product-and-an-mlops-portfolio)

# Overlay-Translator — план развития до продукта и MLOps-портфолио

Цель: превратить проект в (1) приложение, которым хотят пользоваться, и (2) сильный MLOps-кейс для резюме и диплома.

Условные обозначения: `[ ]` — не сделано, `[x]` — сделано. Оценка в рабочих днях при ~3–4 часах в день.

Предстоящие работы разделены на две части: **A — локальная модель (NLLB)** и **B — приложение и остальное**. Номера этапов сохранены, поэтому порядок и зависимости в сводке ссылаются на них; смешанный этап 8 разделён на 8a/8b.

---

## Сделано

Полностью закрытые этапы.

### Этап 0. Гигиена репозитория

**Срок:** 1–2 дня

**Зачем:** без этого проект выглядит заброшенным, а вклад участников размазан по разным именам.

- [x] Добавить `.mailmap`: объединить `Kyrylo Bankovskyi`, `Kyrylo Bankvoskyi`, `Kyrylo` в одну личность; `Alhite`, `Gdx177303`,`Oleksandr` — в другую
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

Подробный план вынесен в [ROADMAP-MODEL.md](ROADMAP-MODEL.md): этапы 2–8a, 10a и 11 (данные, обучение, оценка, реестр, GPU-сборка, мониторинг, сервис). Порядок и зависимости — в сводке ниже.

---

## Часть B. Приложение и остальное

Приложение, продукт и документация, публикация. От работ над моделью зависит только там, где это указано в «Зависимостях».

### Этап 8b. Релиз приложения

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

### Этап 9. Продукт и документация

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

### Этап 12. Резюме, диплом и публикация

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
| 8a | A | Сборка с GPU для локальной модели | 1–2 | |
| 8b | B | Релиз приложения (сделано) | 4–6 | |
| 9 | B | Продукт и документация (сделано) | 3–5 | |
| 10a | A | Мониторинг модели | 2–3 | |
| 11 | A | Сервис инференса | 3–5 | |
| 12 | B | Резюме, диплом, публикация | 3–4 | |

**Рекомендуемый порядок:** 0 → 1 → 2 → 3 → 4 → 6 → 7 → 8a → 5 → 10a → 11 → 12 (8b и 9 уже сделаны).
Части A и B можно вести параллельно. Минимальный набор для сильного резюме: этапы 0–4, 6–8 и 12. Этапы 5, 10a, 11 усиливают проект, но их можно отложить.

**Зависимости:** этап 4 нужен до 5 и 7; этап 6 нужен до 7 и 8a; этап 2 нужен до 3 и 5.

---
---

[Русский](#overlay-translator--план-развития-до-продукта-и-mlops-портфолио) · **English**

# Overlay-Translator — roadmap to a product and an MLOps portfolio

Goal: turn the project into (1) an app people want to use and (2) a strong MLOps case for a CV and a thesis.

Legend: `[ ]` — not done, `[x]` — done. Estimates are in working days at ~3–4 hours a day.

Upcoming work is split into two parts: **A — the local model (NLLB)** and **B — the app and the rest**. Stage numbers are kept, so the order and dependencies in the summary refer to them; the mixed stage 8 is split into 8a/8b.

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

The detailed plan is in [ROADMAP-MODEL.md](ROADMAP-MODEL.md): stages 2–8a, 10a and 11 (data, training, evaluation, registry, GPU build, monitoring, service). Order and dependencies are in the summary below.

---

## Part B. App and the rest

The app, product and documentation, publication. It depends on the model work only where the dependencies below say so.

### Stage 8b. App release

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

### Stage 9. Product and documentation

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

### Stage 12. CV, thesis and publication

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
| 8a | A | GPU build for the local model | 1–2 | |
| 8b | B | App release (done) | 4–6 | |
| 9 | B | Product and documentation (done) | 3–5 | |
| 10a | A | Model monitoring | 2–3 | |
| 11 | A | Inference service | 3–5 | |
| 12 | B | CV, thesis, publication | 3–4 | |

**Recommended order:** 0 → 1 → 2 → 3 → 4 → 6 → 7 → 8a → 5 → 10a → 11 → 12 (8b and 9 are done).
Parts A and B can run in parallel. The minimum for a strong CV: stages 0–4, 6–8 and 12. Stages 5, 10a, 11 strengthen the project but can wait.

**Dependencies:** stage 4 is needed before 5 and 7; stage 6 before 7 and 8a; stage 2 before 3 and 5.
