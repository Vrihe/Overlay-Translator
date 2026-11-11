**Русский** · [English](#overlay-translator--local-model-nllb-roadmap)

# Overlay-Translator — план развития локальной модели (NLLB)

Часть A общего плана [ROADMAP.md](ROADMAP.md) (условные обозначения и общая сводка — там же).

Всё, что касается офлайн-модели: данные, обучение, оценка, реестр, доставка модели в приложение и её инференс.

---

### Этап 2. Воспроизводимое обучение

**Срок:** 4–6 дней

**Зачем:** сейчас эксперименты воспроизводятся по командам в markdown. Нужно превратить их в конфиги и один пайплайн.

- [x] Конфиги обучения в YAML (`configs/train/v1.yaml`, `v2.yaml`): модель, LoRA r/alpha, lr, эпохи, сид, пути данных
- [x] `finetune_lora.py` читает конфиг, пишет в `run_config.json` git sha, версию библиотек и хэш датасета
- [ ] Dockerfile для обучения (CUDA-образ, зафиксированные версии transformers/peft/ctranslate2)
- [x] Makefile или `justfile`: `make data`, `make train`, `make merge`, `make convert`, `make eval`
- [ ] Версионирование данных: DVC (remote — Google Drive, S3-совместимое хранилище или HF Datasets) для `data/processed_*`, `interim/`, глоссария
- [x] DVC pipeline (`dvc.yaml`): `glossary → phrases → translate → repair_keep → build_dataset → train → merge → convert → eval`
- [x] Воспроизвести v1 и v2 одной командой и сравнить метрики с документацией; расхождения описать в `docs/`

**Критерий готовности:** на чистой машине `make all CONFIG=configs/train/v2.yaml` выдаёт модель и таблицу метрик в пределах шума относительно опубликованных чисел.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 3. Трекинг экспериментов

**Срок:** 2–3 дня

- [x] Подключить MLflow (локальный `mlruns/` + опционально DagsHub) или W&B в `finetune_lora.py` и `evaluate.py`
- [x] Логировать: параметры, loss/eval_loss/lr/VRAM, chrF по группам и языкам, keep-rate, размеры сплитов, git sha, хэш данных
- [ ] Залить задним числом прогоны v0-base, v1-lora, v1-abbr, v2-game, v2b-game
- [ ] Скриншот или публичная ссылка на дашборд сравнения прогонов в README/docs
- [ ] Таблица «run → модель → метрики → решение» в `docs/experiments.md`

**Критерий готовности:** любую цифру из `docs/finetune_v*_eval.md` можно найти в трекере по run id.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 4. Честная оценка качества

**Срок:** 4–7 дней

**Зачем:** сейчас эталоны для аббревиатур — вывод самой NLLB, поэтому chrF завышен и ошибки базовой модели считаются правильными.

- [ ] Собрать тестовый набор (gold): 300–500 строк игрового чата (en → ru/uk/pl как минимум), анонимизированных. Ручная проверка переводов вынесена в отдельный этап
- [ ] Разметить в наборе категории: аббревиатуры, keep-термины, обычные слова, смешанные строки, шум OCR
- [ ] Добавить метрики: COMET (или BLEURT) вместе с chrF; keep-rate; доля «неверных раскрытий» на размеченном наборе
- [ ] Прогнать OCR-шум: тот же набор, но с искажениями (ошибки EasyOCR) — оценить устойчивость сквозного пайплайна
- [ ] Доверительные интервалы по нескольким сидам обучения (минимум 3), а не только bootstrap
- [ ] Зафиксировать «золотой» набор в DVC и больше его не использовать для обучения
- [ ] Пересчитать v0-base, v1-abbr, v2-game на новом наборе и пересмотреть выводы (особенно критерий 6)

**Критерий готовности:** решения «какая модель шипится» принимаются по gold-набору, а не по self-distilled эталонам.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 5. Модель v3 (улучшение качества)

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

### Этап 6. Реестр моделей и манифест

**Срок:** 2–3 дня

- [ ] Model card на HF для каждой версии: данные, метод, метрики, ограничения, лицензия, как воспроизвести
- [ ] `manifest.json` в репозитории модели: версия, sha256 `model.bin`, метрики, минимальная версия приложения, рекомендуемый канал (stable / beta)
- [ ] Приложение читает manifest, проверяет sha256 после загрузки и предлагает обновление модели
- [x] Теги в HF: `v0-base`, `v1-abbr`, `v2-game`, `v3-…`; в `config.py` — выбор версии через настройки, а не правка кода
- [x] В `scripts/download_model.py` — проверка целостности и возобновление загрузки

**Критерий готовности:** пользователь выбирает версию модели в настройках, приложение проверяет и скачивает её без `.bat`-скриптов.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 7. CI/CD для модели и quality gate

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

### Этап 8a. Сборка с GPU для локальной модели

**Срок:** 1–2 дня

- [x] Две сборки: CPU (лёгкая) и GPU (с cuBLAS), либо скачивание GPU-компонентов при первом запуске

**Критерий готовности:** установщик или первый запуск даёт NLLB на GPU (cuBLAS), а лёгкая CPU-сборка не растёт в размере.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 10a. Мониторинг модели

**Срок:** 2–3 дня

- [ ] Скрипт отчёта по накопленным данным: доля строк с неизвестными токенами вне глоссария, топ-N потерянных keep-терминов, распределение латентности
- [ ] Детектор дрейфа: сигнал «пора обновить глоссарий / переобучить», когда доля неизвестных токенов растёт

**Критерий готовности:** отчёт запускается одной командой и сигнализирует о дрейфе; порог и ограничения описаны в docs.

**Исполнитель:** ______________________________

**Срок (дата):** ______________________________

---

### Этап 11. Локальный сервис инференса

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
---

[Русский](#overlay-translator--план-развития-локальной-модели-nllb) · **English**

# Overlay-Translator — local model (NLLB) roadmap

Part A of the main plan [ROADMAP.md](ROADMAP.md) (the legend and the overall summary are there).

Everything about the offline model: data, training, evaluation, registry, delivering the model to the app and running it.

---

### Stage 2. Reproducible training

**Time:** 4–6 days

**Why:** experiments are currently reproduced from commands in markdown. They should become configs and a single pipeline.

- [x] Training configs in YAML (`configs/train/v1.yaml`, `v2.yaml`): model, LoRA r/alpha, lr, epochs, seed, data paths
- [x] `finetune_lora.py` reads the config and writes the git sha, library versions and dataset hash to `run_config.json`
- [ ] Training Dockerfile (CUDA image, pinned transformers/peft/ctranslate2 versions)
- [x] Makefile or `justfile`: `make data`, `make train`, `make merge`, `make convert`, `make eval`
- [ ] Data versioning: DVC (remote — Google Drive, S3-compatible storage or HF Datasets) for `data/processed_*`, `interim/`, the glossary
- [x] DVC pipeline (`dvc.yaml`): `glossary → phrases → translate → repair_keep → build_dataset → train → merge → convert → eval`
- [x] Reproduce v1 and v2 with one command and compare metrics with the docs; describe differences in `docs/`

**Done when:** on a clean machine `make all CONFIG=configs/train/v2.yaml` produces a model and a metrics table within noise of the published numbers.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 3. Experiment tracking

**Time:** 2–3 days

- [x] Add MLflow (local `mlruns/` + optionally DagsHub) or W&B to `finetune_lora.py` and `evaluate.py`
- [x] Log: parameters, loss/eval_loss/lr/VRAM, chrF by group and language, keep-rate, split sizes, git sha, data hash
- [ ] Backfill the v0-base, v1-lora, v1-abbr, v2-game, v2b-game runs
- [ ] A screenshot or public link to the run comparison dashboard in the README/docs
- [ ] A "run → model → metrics → decision" table in `docs/experiments.md`

**Done when:** any number from `docs/finetune_v*_eval.md` can be found in the tracker by run id.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 4. Honest quality evaluation

**Time:** 4–7 days

**Why:** the references for abbreviations are currently NLLB's own output, so chrF is inflated and the base model's mistakes count as correct.

- [ ] Build a test set (gold): 300–500 game chat lines (en → ru/uk/pl at least), anonymised. Hand-checking the translations is moved to a separate stage
- [ ] Label categories in the set: abbreviations, keep terms, ordinary words, mixed lines, OCR noise
- [ ] Add metrics: COMET (or BLEURT) alongside chrF; keep-rate; the share of "wrong expansions" on the labelled set
- [ ] Run with OCR noise: the same set with distortions (EasyOCR errors) to measure end-to-end robustness
- [ ] Confidence intervals over several training seeds (at least 3), not only bootstrap
- [ ] Freeze the "gold" set in DVC and never use it for training again
- [ ] Re-score v0-base, v1-abbr, v2-game on the new set and revisit the conclusions (especially criterion 6)

**Done when:** "which model ships" is decided on the gold set, not on self-distilled references.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 5. Model v3 (quality improvements)

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

### Stage 6. Model registry and manifest

**Time:** 2–3 days

- [ ] A model card on HF for each version: data, method, metrics, limitations, licence, how to reproduce
- [ ] `manifest.json` in the model repository: version, sha256 of `model.bin`, metrics, minimum app version, recommended channel (stable / beta)
- [ ] The app reads the manifest, checks sha256 after download and offers model updates
- [x] Tags on HF: `v0-base`, `v1-abbr`, `v2-game`, `v3-…`; in `config.py` — version choice through settings instead of code edits
- [x] Integrity check and resumable download in `scripts/download_model.py`

**Done when:** the user picks a model version in settings and the app checks and downloads it without `.bat` scripts.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 7. Model CI/CD and quality gate

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

### Stage 8a. GPU build for the local model

**Time:** 1–2 days

- [ ] Two builds: CPU (light) and GPU (with cuBLAS), or download GPU components on first launch

**Done when:** the installer or the first launch gives NLLB on the GPU (cuBLAS), and the light CPU build does not grow.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 10a. Model monitoring

**Time:** 2–3 days

- [ ] A report script over the collected data: the share of lines with unknown tokens outside the glossary, top-N lost keep terms, latency distribution
- [ ] A drift detector: a "time to update the glossary / retrain" signal when the share of unknown tokens grows

**Done when:** the report runs with one command and signals drift; the threshold and the limits are described in the docs.

**Owner:** ______________________________

**Due:** ______________________________

---

### Stage 11. Local inference service

**Time:** 3–5 days

- [ ] Move the NLLB backend into a separate process: FastAPI, `/translate`, `/health`, `/version`
- [ ] Prometheus metrics (`/metrics`): latency, batch size, errors, cache hit
- [ ] The app talks to the service over local HTTP; without it, the current built-in behaviour
- [ ] Latency and throughput benchmark (p50/p95, CPU vs GPU, int8 vs fp16, line length), results in `docs/benchmarks.md`
- [ ] Dockerfile and `docker-compose` to run the service apart from the app (for demos and a server scenario)

**Done when:** the service starts with one command, exposes metrics and passes a load test with recorded numbers.

**Owner:** ______________________________

**Due:** ______________________________
