# Промпт для IDE: восстановление cache/store.py и связанные фиксы

## Контекст

Репозиторий Overlay-Translator сейчас находится в сломанном состоянии: модуль `cache/store.py` отсутствует физически (есть только `cache/__init__.py` с однострочным комментарием), при этом на `cache.store` ссылаются 4 файла:

```
translate/llm_client.py   → from cache.store import get_cached, save_to_cache
history/history_window.py → import cache.store as store
tests/test_lang_detect.py → from cache import store
tests/test_domain_profiles.py → from cache import store
```

Любой импорт `translate/llm_client.py` прямо сейчас падает с `ModuleNotFoundError`. Задача — восстановить модуль, согласовать сигнатуры между двумя тестовыми файлами (которые сейчас противоречат друг другу), и попутно поправить связанный баг в `history/history_window.py`.

## Задача 1 — создать `cache/store.py`

Требуемые сигнатуры выведены из фактических вызовов в коде, реализовать точно под них:

```python
# translate/llm_client.py вызывает:
get_cached(text, source_lang, target_lang, domain_id)          # -> str | None
save_to_cache(text, source_lang, target_lang, domain_id, translation)  # -> None

# history/history_window.py вызывает:
store.get_all_history()   # -> list[dict], каждый dict минимум с ключами:
                           #    "timestamp" (unix float/int), "source_text", "translated_text"
store.clear_history()     # -> None, удаляет все записи

# tests/test_lang_detect.py вызывает (БЕЗ domain_id):
store.save_to_cache(text, "en", "ru", "Привет мир")     # 4 позиционных аргумента
store.get_cached(text, "en", "ru")                       # 3 позиционных аргумента
store._DB_PATH                                           # модульный атрибут с путём к файлу БД,
                                                          # тест подменяет его на временный файл

# tests/test_domain_profiles.py вызывает (С domain_id):
store.save_to_cache(text, "en", "ru", "game", "Игровой перевод 123")   # 5 позиционных
store.get_cached(text, "en", "ru", "game")                              # 4 позиционных
```

**Конфликт сигнатур**: `test_lang_detect.py` ожидает 4-й позиционный аргумент как `translation`, а `test_domain_profiles.py` ожидает 4-й позиционный аргумент как `domain_id`. Одна и та же позиционная сигнатура не может удовлетворить оба теста одновременно. Решение:

1. Сделать `domain_id` именованным аргументом с дефолтом:
   ```python
   def save_to_cache(text: str, source_lang: str, target_lang: str,
                      translation: str, *, domain_id: str = "general") -> None: ...

   def get_cached(text: str, source_lang: str, target_lang: str,
                  *, domain_id: str = "general") -> str | None: ...
   ```
2. Поправить вызовы в `translate/llm_client.py` на именованный `domain_id=...` (сейчас там позиционный вызов — найти оба места, строки ~127 и ~183 и ~205/295 в файле).
3. Поправить вызовы в `tests/test_domain_profiles.py` на именованный `domain_id="game"`/`"documentation"` вместо позиционного 4-го аргумента.
4. `tests/test_lang_detect.py` менять не нужно — при позиционном вызове `save_to_cache(text, "en", "ru", "Привет мир")` четвёртый аргумент корректно ляжет в `translation`, а `domain_id` останется дефолтным `"general"`.

**Схема таблицы SQLite** (создать при первом обращении, если файла БД нет):
```sql
CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_text TEXT NOT NULL,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    domain_id TEXT NOT NULL DEFAULT 'general',
    translated_text TEXT NOT NULL,
    timestamp REAL NOT NULL,
    UNIQUE(source_text, source_lang, target_lang, domain_id)
);
```
- `get_cached` — `SELECT translated_text FROM translations WHERE source_text=? AND source_lang=? AND target_lang=? AND domain_id=?`.
- `save_to_cache` — `INSERT OR REPLACE`, обновлять `timestamp` на текущее время при перезаписи.
- `get_all_history(limit=200)` — `SELECT * ORDER BY timestamp DESC LIMIT ?`, вернуть **все поля записи** как словарь (`timestamp`, `source_text`, `source_lang`, `target_lang`, `domain_id`, `translated_text`) — это важно для задачи 3 ниже, не только `source_text`/`translated_text`.
- `clear_history()` — `DELETE FROM translations`.
- Путь к БД — модульная переменная `_DB_PATH`, по умолчанию `config.CACHE_DIR / "translations.db"` (в `config.py` уже есть `CACHE_DIR`, строка ~150 — переиспользовать), но обязательно как перезаписываемый модульный атрибут (не константа внутри функций), потому что тесты подменяют `store._DB_PATH` напрямую.
- Использовать `sqlite3` из стандартной библиотеки, соединение открывать и закрывать в каждой функции (не держать глобальное соединение — из-за многопоточности PyQt-хоткеев это безопаснее).

## Задача 2 — фикс `history/history_window.py`

Сейчас языковая пара берётся из глобального конфига вместо реальной записи:
```python
lang_pair = f"{config.SOURCE_LANG.upper()} → {config.TARGET_LANG.upper()}"
...
item_lang = QTableWidgetItem(lang_pair)   # одинаково для всех строк
```
С учётом автоопределения языка это некорректно — у разных записей реальный `source_lang` может отличаться. Заменить на данные из самой записи:
```python
src = rec.get("source_lang", config.SOURCE_LANG).upper()
tgt = rec.get("target_lang", config.TARGET_LANG).upper()
item_lang = QTableWidgetItem(f"{src} → {tgt}")
```
Строку с вычислением общего `lang_pair` вне цикла — удалить, она больше не нужна.

## Задача 3 — уборка мусора в репозитории

Удалить закоммиченные по ошибке файлы с обрывками вывода PowerShell (не несут никакой ценности, это обрезки ошибки `python : Python`, а не реальный лог тестов):
```
tests/output.txt
tests/pyver.txt
tests/test_output.txt
```
Добавить в `.gitignore`: `tests/output.txt`, `tests/*.txt` (если в этой папке не планируются полезные текстовые фикстуры) — чтобы такое не попадало в репозиторий повторно.

Удалить дублирующий PyInstaller spec-файл: `build.spec` и `translator.spec` почти идентичны по содержимому и дате — оставить только тот, на который реально ссылается `build.py`/`build.bat` (проверить оба файла на `bat`/`py`-скрипты сборки перед удалением, чтобы не сломать актуальный пайплайн сборки), второй удалить.

## Задача 4 — рабочий прогон тестов

Судя по `tests/output.txt`, ранее была ошибка `python : Python` при попытке прогнать тесты через PowerShell (похоже, конфликт alias `python` в PowerShell на Windows или неверный PATH). Убедиться, что тесты реально запускаются:
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
Если используется PowerShell на Windows и команда `python` не резолвится — задокументировать в README рабочую команду (`py -m unittest discover ...` или полный путь к интерпретатору) и добавить `pytest` в `requirements-dev.txt` как более удобный раннер:
```
pytest>=7.0.0
```
с командой `pytest tests/ -v`.

## Порядок коммитов

1. `cache/store.py` (схема БД + все 4 функции) — самый весомый и самостоятельный коммит
2. Правки сигнатур в `translate/llm_client.py` (именованный `domain_id`) + `tests/test_domain_profiles.py` (именованный `domain_id`)
3. Прогнать полный набор тестов, убедиться что `test_lang_detect.py` и `test_domain_profiles.py` проходят на новом `store.py` без дальнейших правок
4. Фикс `history/history_window.py` (реальный `source_lang`/`target_lang` из записи вместо глобального конфига)
5. Уборка мусора: удалить `tests/output.txt`, `tests/pyver.txt`, `tests/test_output.txt`, дубль `.spec`-файла, обновить `.gitignore`
6. `requirements-dev.txt` с `pytest` + раздел в README с рабочей командой запуска тестов
