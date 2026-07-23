# Промпт для Antigravity: исправление автоопределения языка для кириллицы

## Контекст

Автоопределение исходного языка через `langid` (см. предыдущую доработку `translate/lang_detect.py`) плохо работает на кириллице, особенно на коротких/зашумлённых игровых репликах с OCR-артефактами (опечатки, смешение похожих латинских и кириллических глифов, сленг). Статистическая модель путает русский/украинский/болгарский между собой, а иногда и вовсе принимает кириллический текст за язык на латинице с диакритикой. Нужно это исправить, не выкидывая `langid` целиком, а добавив перед ним более надёжный слой.

## Решение: двухступенчатая схема детекта

### Шаг 1 — определение алфавита по Unicode-диапазону (не ML)

Добавить в `translate/lang_detect.py` функцию, которая считает кодовые точки символов напрямую — это не статистика и не подвержено ошибкам, в отличие от `langid`:

```python
import re

CYRILLIC_RE = re.compile(r'[\u0400-\u04FF]')
LATIN_RE = re.compile(r'[a-zA-Z]')

def detect_script(text: str) -> str:
    """Определяет алфавит текста по Unicode-диапазону символов.
    Возвращает 'cyrillic', 'latin' или 'unknown' (если нет ни того, ни другого — 
    например, чисто цифры/пунктуация)."""
    cyrillic_count = len(CYRILLIC_RE.findall(text))
    latin_count = len(LATIN_RE.findall(text))
    total = cyrillic_count + latin_count
    if total == 0:
        return "unknown"
    return "cyrillic" if cyrillic_count / total > 0.5 else "latin"
```

### Шаг 2 — детект внутри уже определённого алфавита

Если `detect_script(text) == "cyrillic"` — не прогонять текст через полный список языков `langid` (там и происходит путаница), а сразу считать это дефолтным кириллическим языком из конфига. Для игрового чата Gloria Victis это практически всегда `ru`.

Добавить в `DEFAULT_CONFIG` в `settings.py`:
```python
"cyrillic_default_lang": "ru",   # какой язык считать по умолчанию при cyrillic-скрипте
```

Обновить логику определения языка (там, где сейчас вызывается `LangDetector.detect()`):

```python
def detect_source_lang(text: str, config: dict, detector: LangDetector) -> str:
    script = detect_script(text)
    if script == "cyrillic":
        return config["cyrillic_default_lang"]
    # для latin/unknown — прежнее поведение через langid/LLM
    return detector.detect(text)
```

Для латиницы поведение не меняется — там `langid`/LLM-детектор работает надёжно, проблема специфична именно для кириллицы.

### Опционально (не обязательно для этой доработки)

Если в будущем понадобится различать `ru`/`uk`/`bg` между собой внутри кириллицы (например, если в чате реально появятся украинские или болгарские игроки) — можно вызывать `langid`/`LLMDetector` не на весь список языков, а с ограниченным подмножеством кириллических кодов. Сейчас это избыточно — начать с простого дефолта `ru`.

## Тесты

Добавить в `tests/test_lang_detect.py`:
- `detect_script()` на чисто кириллической строке → `"cyrillic"`.
- `detect_script()` на чисто латинской строке → `"latin"`.
- `detect_script()` на смешанной строке с преобладанием кириллицы и единичными "похожими" латинскими символами (типичная OCR-ошибка, например кириллическая "о" распознана как латинская) → всё равно `"cyrillic"`.
- `detect_source_lang()` с моком `LangDetector`: при `script == "cyrillic"` метод `detector.detect()` не должен вызываться вообще (проверить через мок, что дефолт возвращается раньше, без обращения к `langid`).

## Порядок коммитов

1. `detect_script()` в `translate/lang_detect.py`
2. `cyrillic_default_lang` в `settings.py`
3. `detect_source_lang()` — обёртка, объединяющая script-check и существующий `LangDetector`
4. Правка вызова в пайплайне (`main.py`/`_on_region_selected()`) — заменить прямой вызов `detector.detect()` на `detect_source_lang()`
5. Тесты + пометка в README про известное ограничение `langid` на кириллице и как оно обходится
