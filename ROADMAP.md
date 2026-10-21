**Русский** · [English](#overlay-translator--roadmap-to-a-product-and-an-mlops-portfolio)

# Overlay-Translator — план развития до продукта и MLOps-портфолио

Цель: превратить проект в (1) приложение, которым хотят пользоваться, и (2) сильный MLOps-кейс для резюме и диплома.

Условные обозначения: `[ ]` — не сделано, `[x]` — сделано. Оценка в рабочих днях при ~3–4 часах в день.

---

## Этап 0. Гигиена репозитория

**Срок:** 1–2 дня

**Зачем:** без этого проект выглядит заброшенным, а вклад участников размазан по разным именам.

- [ ] Добавить `.mailmap`: объединить `Kyrylo Bankovskyi`, `Kyrylo Bankvoskyi`, `Kyrylo` в одну личность; `Alhite`, `Gdx177303`,`Oleksandr` — в другую
- [x] Добавить `LICENSE` (MIT или Apache-2.0; для модели — отдельно указать лицензию NLLB, CC-BY-NC 4.0)
- [x] Добавить `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, шаблоны issue и PR
- [ ] Убрать устаревшее из README: структура `translator-overlay/`, `settings.py`, описание popup «original + translation», `your-username` в clone-команде
- [x] Убрать из `requirements-train.txt` привязку к китайскому зеркалу и локальные пути; вынести в комментарий «как установить CUDA torch»
- [x] Убрать хардкод `D:\projects\overlay-translator\...` из `training/finetune_lora.py` и docs (заменить на аргумент или переменную окружения)
- [x] Включить защиту ветки `main` (PR + зелёный CI)

**Критерий готовности:** в `git shortlog -sn` два человека; в репозитории нет путей `D:\`; README не противоречит коду.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 1. CI и качество кода

**Срок:** 2–3 дня

- [ ] `pyproject.toml` с метаданными, зависимостями и настройками ruff/pytest/mypy
- [ ] Pre-commit: ruff (lint + format), trailing whitespace, проверка больших файлов
- [ ] GitHub Actions `ci.yml`: ruff, pytest на Windows и Linux (Qt-тесты через `QT_QPA_PLATFORM=offscreen`)
- [ ] Отметить в тестах те, что требуют GPU/модель, маркером `@pytest.mark.slow` и не гонять их в обычном CI
- [ ] Добавить недостающие тесты: `translate/backend.py` (выбор бэкенда и fallback), `nllb_backend` с подменой модели, `cache/store.py`, `training/build_dataset*.py` (сплиты без утечки), метрики в `training/evaluate.py`
- [ ] Бейджи CI и покрытия в README
- [ ] Coverage отчёт (pytest-cov), цель — не ниже 60% для `translate/`, `cache/`, `settings/`

**Критерий готовности:** PR нельзя смержить с красным CI; покрытие видно в README.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 2. Воспроизводимое обучение

**Срок:** 4–6 дней

**Зачем:** сейчас эксперименты воспроизводятся по командам в markdown. Нужно превратить их в конфиги и один пайплайн.

- [ ] Конфиги обучения в YAML (`configs/train/v1.yaml`, `v2.yaml`): модель, LoRA r/alpha, lr, эпохи, сид, пути данных
- [ ] `finetune_lora.py` читает конфиг, пишет в `run_config.json` git sha, версию библиотек и хэш датасета
- [ ] Dockerfile для обучения (CUDA-образ, зафиксированные версии transformers/peft/ctranslate2)
- [ ] Makefile или `justfile`: `make data`, `make train`, `make merge`, `make convert`, `make eval`
- [ ] Версионирование данных: DVC (remote — Google Drive, S3-совместимое хранилище или HF Datasets) для `data/processed_*`, `interim/`, глоссария
- [ ] DVC pipeline (`dvc.yaml`): `glossary → phrases → translate → repair_keep → build_dataset → train → merge → convert → eval`
- [ ] Воспроизвести v1 и v2 одной командой и сравнить метрики с документацией; расхождения описать в `docs/`

**Критерий готовности:** на чистой машине `make all CONFIG=configs/train/v2.yaml` выдаёт модель и таблицу метрик в пределах шума относительно опубликованных чисел.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 3. Трекинг экспериментов

**Срок:** 2–3 дня

- [ ] Подключить MLflow (локальный `mlruns/` + опционально DagsHub) или W&B в `finetune_lora.py` и `evaluate.py`
- [ ] Логировать: параметры, loss/eval_loss/lr/VRAM, chrF по группам и языкам, keep-rate, размеры сплитов, git sha, хэш данных
- [ ] Залить задним числом прогоны v0-base, v1-lora, v1-abbr, v2-game, v2b-game
- [ ] Скриншот или публичная ссылка на дашборд сравнения прогонов в README/docs
- [ ] Таблица «run → модель → метрики → решение» в `docs/experiments.md`

**Критерий готовности:** любую цифру из `docs/finetune_v*_eval.md` можно найти в трекере по run id.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 4. Честная оценка качества

**Срок:** 4–7 дней

**Зачем:** сейчас эталоны для аббревиатур — вывод самой NLLB, поэтому chrF завышен и ошибки базовой модели считаются правильными.

- [ ] Собрать ручной тестовый набор: 300–500 реальных строк игрового чата (en → ru/uk/pl как минимум), анонимизированных, с проверенными вручную переводами
- [ ] Разметить в наборе категории: аббревиатуры, keep-термины, обычные слова, смешанные строки, шум OCR
- [ ] Добавить метрики: COMET (или BLEURT) вместе с chrF; keep-rate; доля «неверных раскрытий» на размеченном наборе
- [ ] Прогнать OCR-шум: тот же набор, но с искажениями (ошибки EasyOCR) — оценить устойчивость сквозного пайплайна
- [ ] Доверительные интервалы по нескольким сидам обучения (минимум 3), а не только bootstrap
- [ ] Зафиксировать «золотой» набор в DVC и больше его не использовать для обучения
- [ ] Пересчитать v0-base, v1-abbr, v2-game на новом наборе и пересмотреть выводы (особенно критерий 6)

**Критерий готовности:** решения «какая модель шипится» принимаются по ручному набору, а не по self-distilled эталонам.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 5. Модель v3 (улучшение качества)

**Срок:** 5–8 дней

- [ ] Добавить в обучение обычные слова в контексте (`kick him`, `cover me`), а не только изолированные слова
- [ ] Добавить числовые и вариативные формы (`lf2m`, `lf3m`, `2kk`, `+10`)
- [ ] Заменить самодистиллированные таргеты на проверенные вручную или полученные из сильного LLM с последующей фильтрацией
- [ ] Сравнить варианты: LoRA r=16/32, разные доли FLORES, с глоссарием в препроцессоре и без него (ablation-таблица)
- [ ] Эксперимент: препроцессор-глоссарий + модель против одной модели — вклад каждого компонента
- [ ] Экспорт в CTranslate2 int8, сравнение с fp16 и CPU/GPU по качеству и латентности
- [ ] Решение «промоутить / не промоутить» по заранее зафиксированным критериям (quality gate из этапа 7)

**Критерий готовности:** v3 лучше v0-base и v2-game на ручном наборе при допустимой регрессии обычных слов.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 6. Реестр моделей и манифест

**Срок:** 2–3 дня

- [ ] Model card на HF для каждой версии: данные, метод, метрики, ограничения, лицензия, как воспроизвести
- [ ] `manifest.json` в репозитории модели: версия, sha256 `model.bin`, метрики, минимальная версия приложения, рекомендуемый канал (stable / beta)
- [ ] Приложение читает manifest, проверяет sha256 после загрузки и предлагает обновление модели
- [x] Теги в HF: `v0-base`, `v1-abbr`, `v2-game`, `v3-…`; в `config.py` — выбор версии через настройки, а не правка кода
- [ ] В `scripts/download_model.py` — проверка целостности и возобновление загрузки

**Критерий готовности:** пользователь выбирает версию модели в настройках, приложение проверяет и скачивает её без `.bat`-скриптов.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 7. CI/CD для модели и quality gate

**Срок:** 3–4 дня

- [ ] Workflow `model-eval.yml` (ручной запуск и nightly): скачать кандидата с HF, прогнать на фиксированном мини-наборе (CPU, int8)
- [ ] Quality gate: порог chrF/COMET на общем и ручном наборе, keep-rate ≥ 90%, регрессия обычных слов не больше N пунктов, латентность p95 не выше порога
- [ ] Отчёт сравнения кандидата с текущим stable как комментарий к PR или artifact
- [ ] Автоматическое обновление `manifest.json` и тега только при прохождении gate
- [ ] Защита от случайной публикации: промоция только через PR + ручное подтверждение

**Критерий готовности:** модель, не прошедшая gate, технически не может попасть в канал `stable`.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 8. Релиз приложения

**Срок:** 4–6 дней

- [x] GitHub Actions `release.yml`: сборка PyInstaller на `windows-latest` по тегу `v*`, загрузка артефактов в GitHub Release
- [x] Установщик (Inno Setup или MSIX), ярлык, деинсталлятор; рассмотреть подпись кода
- [ ] Две сборки: CPU (лёгкая) и GPU (с cuBLAS), либо скачивание GPU-компонентов при первом запуске
- [x] Мастер первого запуска: выбор режима (API / офлайн), кнопка «Скачать офлайн-модель» с прогрессом и проверкой sha256
- [x] Проверка работы апдейтера на реальном релизе (сейчас релизов нет)
- [x] Changelog (`CHANGELOG.md`, Keep a Changelog) и SemVer-теги
- [x] Тестирование на чистой Windows (виртуалка): установка → первый запуск → перевод → удаление
- [x] Выпустить `v1.0.0`

**Критерий готовности:** незнакомый человек скачивает установщик со страницы релиза и переводит текст за пять минут без терминала.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 9. Продукт и документация

**Срок:** 3–5 дней

- [x] Интерфейс на английском и русском (i18n через `QTranslator` или простой словарь), выбор языка в настройках
- [ ] Демо-GIF (до 10 МБ) и скриншоты в README: офлайн-перевод `lf2m`, `wts … pm me`, live-режим
- [ ] README: первым экраном — ценность и установка в 3 шага; ниже — режимы, приватность, FAQ, ограничения
- [ ] Раздел «Как это работает» с диаграммой пайплайна (OCR → glossary → NLLB → popup) и MLOps-диаграммой (data → train → eval → registry → app)
- [ ] `docs/` как сайт (GitHub Pages / MkDocs): установка, настройка, обучение, воспроизведение экспериментов
- [ ] Страница «Приватность»: что уходит в API, что остаётся локально, как работает логирование
- [ ] Обработка типовых проблем в FAQ: нет GPU, антивирус, нет прав на хоткеи

**Критерий готовности:** новый пользователь и новый разработчик находят всё нужное в README и docs без вопросов вам.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 10. Обратная связь и мониторинг

**Срок:** 4–6 дней

- [ ] Кнопка 👎/👍 в popup результата; негативные примеры сохраняются локально в SQLite
- [ ] Экспорт отзывов в `jsonl` (кнопка «Поделиться данными для улучшения модели», с предпросмотром и согласием)
- [ ] Опциональная анонимная телеметрия (по умолчанию выключена): версия приложения и модели, backend, латентность, cache-hit, тип ошибки; без текста с экрана
- [ ] Скрипт отчёта по накопленным данным: доля строк с неизвестными токенами вне глоссария, топ-N потерянных keep-терминов, распределение латентности
- [ ] Детектор дрейфа: сигнал «пора обновить глоссарий / переобучить», когда доля неизвестных токенов растёт
- [ ] Процесс: отзывы → ручная проверка → датасет v4 → новый цикл этапов 2–7

**Критерий готовности:** замкнутый цикл «пользователь отметил плохой перевод → пример попал в датасет следующей версии» работает и описан в docs.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 11. Локальный сервис инференса

**Срок:** 3–5 дней

- [ ] Вынести NLLB-бэкенд в отдельный процесс: FastAPI, `/translate`, `/health`, `/version`
- [ ] Метрики Prometheus (`/metrics`): латентность, размер батча, ошибки, cache-hit
- [ ] Приложение обращается к сервису через локальный HTTP; при его отсутствии — прежнее встроенное поведение
- [ ] Бенчмарк латентности и пропускной способности (p50/p95, CPU vs GPU, int8 vs fp16, длина строки), результаты в `docs/benchmarks.md`
- [ ] Dockerfile и `docker-compose` для запуска сервиса отдельно от приложения (для демонстрации и серверного сценария)

**Критерий готовности:** сервис запускается одной командой, отдаёт метрики и проходит нагрузочный тест с зафиксированными числами.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Этап 12. Резюме, диплом и публикация

**Срок:** 3–4 дня

- [ ] Раздел «MLOps» в README: диаграмма жизненного цикла, ссылки на трекер, DVC, HF-модели, CI
- [ ] Технический отчёт или статья (Medium/dev.to/Habr): задача, данные, обучение, оценка, провалы, выводы
- [ ] Структура диплома: проблема → данные и глоссарий → метод (LoRA + препроцессор) → оценка → инженерная часть (CI/CD, реестр, мониторинг) → результаты и ограничения
- [ ] Формулировки для резюме (3–4 пункта с цифрами: прирост chrF, keep-rate, латентность, покрытие тестами)
- [ ] Закреплённый репозиторий на GitHub-профиле, актуальный профильный README
- [ ] Короткое видео-демо (1–2 минуты)
- [ ] Чёткое описание вклада: что сделано лично вами (обучение, оценка, глоссарий, интеграция NLLB), что — командой

**Критерий готовности:** по ссылке на репозиторий рекрутер за две минуты видит задачу, результат и инженерную зрелость.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

## Сводка

| Этап | Название | Срок, дней | Исполнитель |
|---|---|---|---|
| 0 | Гигиена репозитория | 1–2 | |
| 1 | CI и качество кода | 2–3 | |
| 2 | Воспроизводимое обучение | 4–6 | |
| 3 | Трекинг экспериментов | 2–3 | |
| 4 | Честная оценка качества | 4–7 | |
| 5 | Модель v3 | 5–8 | |
| 6 | Реестр моделей и манифест | 2–3 | |
| 7 | CI/CD для модели | 3–4 | |
| 8 | Релиз приложения | 4–6 | |
| 9 | Продукт и документация | 3–5 | |
| 10 | Обратная связь и мониторинг | 4–6 | |
| 11 | Сервис инференса | 3–5 | |
| 12 | Резюме, диплом, публикация | 3–4 | |

**Рекомендуемый порядок:** 0 → 1 → 2 → 3 → 4 → 6 → 7 → 8 → 9 → 5 → 10 → 11 → 12.
Минимальный набор для сильного резюме: этапы 0–4, 6–8 и 12. Этапы 5, 10, 11 усиливают проект, но их можно отложить.

**Зависимости:** этап 4 нужен до 5 и 7; этап 6 нужен до 7 и 8; этап 2 нужен до 3 и 5.

---
---

[Русский](#overlay-translator--план-развития-до-продукта-и-mlops-портфолио) · **English**

# Overlay-Translator — roadmap to a product and an MLOps portfolio

Goal: turn the project into (1) an app people want to use and (2) a strong MLOps case for a CV and a thesis.

Legend: `[ ]` — not done, `[x]` — done. Estimates are in working days at ~3–4 hours a day.

---

## Stage 0. Repository hygiene

**Time:** 1–2 days

**Why:** without it the project looks abandoned, and contributors' work is spread over different names.

- [ ] Add `.mailmap`: merge `Kyrylo Bankovskyi`, `Kyrylo Bankvoskyi`, `Kyrylo` into one identity; `Alhite`, `Gdx177303`, `Oleksandr` into another
- [x] Add `LICENSE` (MIT or Apache-2.0; state the NLLB licence for the model separately, CC-BY-NC 4.0)
- [x] Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue and PR templates
- [ ] Remove outdated parts of the README: the `translator-overlay/` tree, `settings.py`, the "original + translation" popup description, `your-username` in the clone command
- [x] Drop the Chinese mirror and local paths from `requirements-train.txt`; move "how to install CUDA torch" into a comment
- [x] Remove the hardcoded `D:\projects\overlay-translator\...` from `training/finetune_lora.py` and the docs (replace with an argument or an environment variable)
- [x] Protect the `main` branch (PR + green CI)

**Done when:** `git shortlog -sn` shows two people; the repository has no `D:\` paths; the README does not contradict the code.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 1. CI and code quality

**Time:** 2–3 days

- [ ] `pyproject.toml` with metadata, dependencies and ruff/pytest/mypy settings
- [ ] Pre-commit: ruff (lint + format), trailing whitespace, large-file check
- [ ] GitHub Actions `ci.yml`: ruff, pytest on Windows and Linux (Qt tests with `QT_QPA_PLATFORM=offscreen`)
- [ ] Mark tests that need a GPU or a model with `@pytest.mark.slow` and skip them in regular CI
- [ ] Add missing tests: `translate/backend.py` (backend choice and fallback), `nllb_backend` with a stubbed model, `cache/store.py`, `training/build_dataset*.py` (splits without leakage), metrics in `training/evaluate.py`
- [ ] CI and coverage badges in the README
- [ ] Coverage report (pytest-cov), target at least 60% for `translate/`, `cache/`, `settings/`

**Done when:** a PR cannot be merged with red CI; coverage is visible in the README.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 2. Reproducible training

**Time:** 4–6 days

**Why:** experiments are currently reproduced from commands in markdown. They should become configs and a single pipeline.

- [ ] Training configs in YAML (`configs/train/v1.yaml`, `v2.yaml`): model, LoRA r/alpha, lr, epochs, seed, data paths
- [ ] `finetune_lora.py` reads the config and writes the git sha, library versions and dataset hash to `run_config.json`
- [ ] Training Dockerfile (CUDA image, pinned transformers/peft/ctranslate2 versions)
- [ ] Makefile or `justfile`: `make data`, `make train`, `make merge`, `make convert`, `make eval`
- [ ] Data versioning: DVC (remote — Google Drive, S3-compatible storage or HF Datasets) for `data/processed_*`, `interim/`, the glossary
- [ ] DVC pipeline (`dvc.yaml`): `glossary → phrases → translate → repair_keep → build_dataset → train → merge → convert → eval`
- [ ] Reproduce v1 and v2 with one command and compare metrics with the docs; describe differences in `docs/`

**Done when:** on a clean machine `make all CONFIG=configs/train/v2.yaml` produces a model and a metrics table within noise of the published numbers.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 3. Experiment tracking

**Time:** 2–3 days

- [ ] Add MLflow (local `mlruns/` + optionally DagsHub) or W&B to `finetune_lora.py` and `evaluate.py`
- [ ] Log: parameters, loss/eval_loss/lr/VRAM, chrF by group and language, keep-rate, split sizes, git sha, data hash
- [ ] Backfill the v0-base, v1-lora, v1-abbr, v2-game, v2b-game runs
- [ ] A screenshot or public link to the run comparison dashboard in the README/docs
- [ ] A "run → model → metrics → decision" table in `docs/experiments.md`

**Done when:** any number from `docs/finetune_v*_eval.md` can be found in the tracker by run id.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 4. Honest quality evaluation

**Time:** 4–7 days

**Why:** the references for abbreviations are currently NLLB's own output, so chrF is inflated and the base model's mistakes count as correct.

- [ ] Build a manual test set: 300–500 real game chat lines (en → ru/uk/pl at least), anonymised, with hand-checked translations
- [ ] Label categories in the set: abbreviations, keep terms, ordinary words, mixed lines, OCR noise
- [ ] Add metrics: COMET (or BLEURT) alongside chrF; keep-rate; the share of "wrong expansions" on the labelled set
- [ ] Run with OCR noise: the same set with distortions (EasyOCR errors) to measure end-to-end robustness
- [ ] Confidence intervals over several training seeds (at least 3), not only bootstrap
- [ ] Freeze the "gold" set in DVC and never use it for training again
- [ ] Re-score v0-base, v1-abbr, v2-game on the new set and revisit the conclusions (especially criterion 6)

**Done when:** "which model ships" is decided on the manual set, not on self-distilled references.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 5. Model v3 (quality improvements)

**Time:** 5–8 days

- [ ] Train on ordinary words in context (`kick him`, `cover me`), not only on isolated words
- [ ] Add numeric and variant forms (`lf2m`, `lf3m`, `2kk`, `+10`)
- [ ] Replace self-distilled targets with hand-checked ones or ones from a strong LLM with filtering
- [ ] Compare variants: LoRA r=16/32, different FLORES shares, with and without the glossary preprocessor (ablation table)
- [ ] Experiment: glossary preprocessor + model vs the model alone — the contribution of each part
- [ ] Export to CTranslate2 int8, compare with fp16 and CPU/GPU on quality and latency
- [ ] "Promote / do not promote" decision against criteria fixed in advance (the quality gate from stage 7)

**Done when:** v3 beats v0-base and v2-game on the manual set with an acceptable regression on ordinary words.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 6. Model registry and manifest

**Time:** 2–3 days

- [ ] A model card on HF for each version: data, method, metrics, limitations, licence, how to reproduce
- [ ] `manifest.json` in the model repository: version, sha256 of `model.bin`, metrics, minimum app version, recommended channel (stable / beta)
- [ ] The app reads the manifest, checks sha256 after download and offers model updates
- [x] Tags on HF: `v0-base`, `v1-abbr`, `v2-game`, `v3-…`; in `config.py` — version choice through settings instead of code edits
- [ ] Integrity check and resumable download in `scripts/download_model.py`

**Done when:** the user picks a model version in settings and the app checks and downloads it without `.bat` scripts.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 7. Model CI/CD and quality gate

**Time:** 3–4 days

- [ ] `model-eval.yml` workflow (manual and nightly): download the candidate from HF, run it on a fixed mini set (CPU, int8)
- [ ] Quality gate: chrF/COMET threshold on the general and manual sets, keep-rate ≥ 90%, ordinary-word regression of at most N points, p95 latency under a threshold
- [ ] A candidate vs current stable comparison report as a PR comment or an artifact
- [ ] Update `manifest.json` and the tag automatically only when the gate passes
- [ ] Guard against accidental publishing: promotion only through a PR + manual approval

**Done when:** a model that fails the gate technically cannot reach the `stable` channel.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 8. App release

**Time:** 4–6 days

- [x] GitHub Actions `release.yml`: PyInstaller build on `windows-latest` for `v*` tags, artifacts uploaded to a GitHub Release
- [x] Installer (Inno Setup or MSIX), shortcut, uninstaller; consider code signing
- [ ] Two builds: CPU (light) and GPU (with cuBLAS), or download GPU components on first launch
- [x] First-run wizard: mode choice (API / offline), a "Download offline model" button with progress and a sha256 check
- [x] Check the updater against a real release (there are no releases yet)
- [x] Changelog (`CHANGELOG.md`, Keep a Changelog) and SemVer tags
- [x] Test on a clean Windows (VM): install → first launch → translation → uninstall
- [x] Release `v1.0.0`

**Done when:** a stranger downloads the installer from the release page and translates text within five minutes without a terminal.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 9. Product and documentation

**Time:** 3–5 days

- [x] English and Russian interface (i18n via `QTranslator` or a simple dictionary), language choice in settings
- [ ] Demo GIF (up to 10 MB) and screenshots in the README: offline translation of `lf2m`, `wts … pm me`, live mode
- [ ] README: the first screen shows the value and a 3-step install; below — modes, privacy, FAQ, limitations
- [ ] A "How it works" section with a pipeline diagram (OCR → glossary → NLLB → popup) and an MLOps diagram (data → train → eval → registry → app)
- [ ] `docs/` as a site (GitHub Pages / MkDocs): installation, configuration, training, reproducing experiments
- [ ] A "Privacy" page: what goes to the API, what stays local, how logging works
- [ ] Common problems in the FAQ: no GPU, antivirus, no rights for hotkeys

**Done when:** a new user and a new developer find everything they need in the README and docs without asking you.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 10. Feedback and monitoring

**Time:** 4–6 days

- [ ] A 👎/👍 button in the result popup; negative examples are stored locally in SQLite
- [ ] Export feedback to `jsonl` (a "Share data to improve the model" button, with a preview and consent)
- [ ] Optional anonymous telemetry (off by default): app and model version, backend, latency, cache hit, error type; no screen text
- [ ] A report script over the collected data: the share of lines with unknown tokens outside the glossary, top-N lost keep terms, latency distribution
- [ ] A drift detector: a "time to update the glossary / retrain" signal when the share of unknown tokens grows
- [ ] Process: feedback → manual review → dataset v4 → a new cycle of stages 2–7

**Done when:** the closed loop "a user flagged a bad translation → the example reached the next version's dataset" works and is described in the docs.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 11. Local inference service

**Time:** 3–5 days

- [ ] Move the NLLB backend into a separate process: FastAPI, `/translate`, `/health`, `/version`
- [ ] Prometheus metrics (`/metrics`): latency, batch size, errors, cache hit
- [ ] The app talks to the service over local HTTP; without it, the current built-in behaviour
- [ ] Latency and throughput benchmark (p50/p95, CPU vs GPU, int8 vs fp16, line length), results in `docs/benchmarks.md`
- [ ] Dockerfile and `docker-compose` to run the service apart from the app (for demos and a server scenario)

**Done when:** the service starts with one command, exposes metrics and passes a load test with recorded numbers.

**Owner:** ______________________________

**Due:** ______________________________

---

## Stage 12. CV, thesis and publication

**Time:** 3–4 days

- [ ] An "MLOps" section in the README: lifecycle diagram, links to the tracker, DVC, HF models, CI
- [ ] A technical report or article (Medium/dev.to/Habr): task, data, training, evaluation, failures, conclusions
- [ ] Thesis outline: problem → data and glossary → method (LoRA + preprocessor) → evaluation → engineering (CI/CD, registry, monitoring) → results and limitations
- [ ] CV bullet points (3–4 with numbers: chrF gain, keep-rate, latency, test coverage)
- [ ] The repository pinned on the GitHub profile, an up-to-date profile README
- [ ] A short video demo (1–2 minutes)
- [ ] A clear statement of contribution: what you did personally (training, evaluation, glossary, NLLB integration) and what the team did

**Done when:** from the repository link a recruiter sees the task, the result and the engineering maturity within two minutes.

**Owner:** ______________________________

**Due:** ______________________________

---

## Summary

| Stage | Name | Days | Owner |
|---|---|---|---|
| 0 | Repository hygiene | 1–2 | |
| 1 | CI and code quality | 2–3 | |
| 2 | Reproducible training | 4–6 | |
| 3 | Experiment tracking | 2–3 | |
| 4 | Honest quality evaluation | 4–7 | |
| 5 | Model v3 | 5–8 | |
| 6 | Model registry and manifest | 2–3 | |
| 7 | Model CI/CD | 3–4 | |
| 8 | App release | 4–6 | |
| 9 | Product and documentation | 3–5 | |
| 10 | Feedback and monitoring | 4–6 | |
| 11 | Inference service | 3–5 | |
| 12 | CV, thesis, publication | 3–4 | |

**Recommended order:** 0 → 1 → 2 → 3 → 4 → 6 → 7 → 8 → 9 → 5 → 10 → 11 → 12.
The minimum for a strong CV: stages 0–4, 6–8 and 12. Stages 5, 10, 11 strengthen the project but can wait.

**Dependencies:** stage 4 is needed before 5 and 7; stage 6 before 7 and 8; stage 2 before 3 and 5.
