# Формат сохранения моделей Aurora — спецификация

> **Версия:** aurora-model v1
> **Введён:** 2026-05-16 (Aurora MMM Optimizer v2.1.0, Партия 2 п.4.1)
> **Заменяет:** устаревший pickle-формат (для обратной совместимости читается, но новые модели сохраняются только в безопасном формате)

---

## Зачем нужен

Старый формат (pickle) — это сериализация Python-объектов с произвольным выполнением кода при загрузке. Если злоумышленник подменит файл модели в общей папке, при следующем открытии проекта может выполниться вредоносный код. Это известная уязвимость pickle, не Aurora-специфичная.

Новый формат `aurora-model` хранит данные в безопасном виде:

- структурные поля — в JSON
- большие массивы (posterior samples, веса каналов) — в `numpy npz` с явным запретом pickle при загрузке
- общий контейнер — ZIP-архив с контрольными суммами

При загрузке нового формата невозможно исполнить произвольный код, даже если злоумышленник подменит файл — отсутствует attack-surface `pickle.load`.

---

## Структура файла

Файл с именем `latest.pkl` (имя сохранено для обратной совместимости с 40+ путями в Rust IPC, Python, фронтенде) — это ZIP-архив со следующими членами:

```
latest.pkl  (ZIP)
├── manifest.json    — метаданные формата
├── data.json        — все поля модели (numpy-массивы заменены ссылками)
└── arrays.npz       — все numpy-массивы (если есть)
```

### manifest.json

Обязательные поля:

```json
{
  "format": "aurora-model",
  "format_version": "1",
  "created_at": "2026-05-16T01:23:45+03:00",
  "array_count": 7,
  "model_version": "2.1",
  "sha256_data": "ab12...",
  "sha256_arrays": "cd34..."
}
```

Опциональные поля (через `extra_manifest` в `save_model_safe`):

- `migrated_from` — `"pickle"` если файл был мигрирован
- `migration_kind` — `"lazy_on_load"` или `"explicit"`
- `migrated_at` — ISO-8601 timestamp

При load значения полей `format` и `format_version` **не могут** быть переопределены через `extra_manifest` — это контракт безопасности.

### data.json

JSON с полями модели. Все numpy-массивы заменены на placeholder:

```json
{
  "model_version": "2.1",
  "kpi_type": "sales",
  "config": {
    "media_columns": ["tv_rub", "digital_rub"],
    "data_file": "D:/data/kagocel.xlsx"
  },
  "posterior_samples": {
    "media_betas": {
      "__numpy_array__": "posterior_samples__media_betas",
      "shape": [7, 8000],
      "dtype": "float32"
    },
    "n_chains": 4
  }
}
```

Поддерживаемые типы:

- `null`, `bool`, `int`, `str`
- `float` (но не `NaN` / `Infinity` — это нарушение RFC 8259, проверяется при save)
- `list` / `tuple` (tuple конвертируется в list — JSON-ограничение)
- `dict` со строковыми ключами
- `datetime.datetime` (сериализуется как `{"__datetime__": "2026-05-16T..."}`)
- `numpy.ndarray` (любого dtype и shape — через placeholder + npz)
- `numpy` скаляры (`int64`, `float32`, `bool_`) — конвертируются в Python-примитивы

**Отвергаются при save** (вызывают `UnsupportedTypeError`):

- `bytes` / `bytearray` (можно хранить как base64-строку, явно)
- `set` / `frozenset` (нужно конвертировать в sorted list)
- Произвольные классы, callables, `functools.partial`
- `pandas.DataFrame` / `Series` (caller должен извлечь нужные значения)
- Не-строковые ключи в dict

### arrays.npz

Стандартный numpy-архив, созданный через `np.savez`. При загрузке используется `np.load(file, allow_pickle=False)` — это гарантирует, что даже если кто-то подменит arrays.npz pickle-полезной нагрузкой, она будет отвергнута.

Имена массивов соответствуют пути доступа в data.json:

```
posterior_samples.media_betas → posterior_samples__media_betas
posterior_samples.alphas       → posterior_samples__alphas
channel_params.0.weights       → channel_params_0_weights
```

При коллизиях добавляется суффикс `__1`, `__2` и т.д.

---

## Защита

| Класс атаки | Защита | Где в коде |
|---|---|---|
| RCE через pickle deserialization | `json.load` + `np.load(allow_pickle=False)` | `load_model_safe` |
| Zip-bomb | Лимит `MAX_TOTAL_UNCOMPRESSED = 500 MB` + проверка суммы uncompressed | `load_model_safe` |
| Path traversal в ZIP member name | Reject имён с `..`, `/` префикс, `\` | `load_model_safe` |
| Слишком длинные member names | Лимит `MAX_MEMBER_NAME_LEN = 200` | `load_model_safe` |
| Слишком много файлов | Лимит `MAX_FILES = 16` | `load_model_safe` |
| Подмена формата | Проверка `manifest.format == "aurora-model"` | `load_model_safe` |
| NaN/Infinity в JSON-скалярах | `allow_nan=False` при `json.dumps` | `_split_arrays` |
| Tamper-detection (опционально) | SHA-256 sidecar файл `.sha256` рядом | `write_pkl_sha256_sidecar` |

---

## Атомарность записи

При сохранении используется паттерн `temp file + os.replace`:

1. Серилизуем в bytes (manifest, data, arrays)
2. Записываем в `<target>.aurora-model.tmp` в той же директории
3. `fsync` для гарантии записи на диск
4. `os.replace(tmp, target)` — атомарный rename

Это гарантирует:

- При сбое питания / kill процесса целевой файл либо не изменён, либо полностью записан
- Никаких частично-записанных файлов
- На Windows `os.replace` использует `MoveFileExW` — атомарность в рамках того же тома
- На POSIX `os.replace` использует `rename(2)` — POSIX-атомарность

---

## Маршрутизация форматов

Функция `detect_format(path)` определяет формат по первым 4 байтам файла:

| Magic bytes | Формат |
|---|---|
| `PK\x03\x04` | `aurora-model` (ZIP) |
| `\x80\x02..\x80\x05` | `pickle` (legacy, protocol 2-5) |
| прочее | `unknown` |

`engines.persistence.load_model_with_compat(path)` маршрутизирует:

1. `aurora-model` → `load_model_safe` (безопасный путь)
2. `pickle` → `pickle.load` (legacy путь с warning + SHA-256 sidecar verify)
3. После legacy load — автоматическая lazy-миграция (см. ниже)
4. `unknown` → `pickle.UnpicklingError` или `FileNotFoundError`

---

## Lazy migration

При загрузке legacy pickle через `load_model_with_compat` происходит автоматическая миграция:

1. Pickle загружается обычным образом (с warning о потенциальной RCE)
2. Сразу после load — backup в `<file>.pre_safe_migration`
3. Перезапись `latest.pkl` в формате aurora-model
4. Обновление SHA-256 sidecar

Это закрывает окно атаки между текущим load и следующим save. Следующий load этого файла уже идёт через безопасный путь без `pickle.load`.

Если миграция падает (read-only FS, EACCES, disk full) — логируется warning, но load возвращает данные. Модель работает в режиме «прочитано, но не мигрировано» до следующего успешного save.

Backup файл `.pre_safe_migration` сохраняется бессрочно — даёт возможность отката, если миграция чем-то испортила данные.

---

## API

### save_model_safe

```python
from engines.persistence_safe import save_model_safe

save_model_safe(
    model_data: dict[str, Any],
    path: Path | str,
    *,
    extra_manifest: dict[str, Any] | None = None,
) -> str  # SHA-256 hex итогового файла
```

Атомарная запись. Raises `UnsupportedTypeError` если в `model_data` есть неподдерживаемые типы.

### load_model_safe

```python
from engines.persistence_safe import load_model_safe

model_data = load_model_safe(path: Path | str) -> dict[str, Any]
```

Возвращает восстановленный dict. Raises `FileNotFoundError`, `CorruptArchiveError`, `SafeModelFormatError`.

### detect_format

```python
from engines.persistence_safe import detect_format

fmt = detect_format(path: Path | str) -> str
# 'aurora-model' | 'pickle' | 'unknown'
```

### migrate_pickle_to_safe

```python
from engines.persistence_safe import migrate_pickle_to_safe

new_path = migrate_pickle_to_safe(
    source_pickle: Path | str,
    target_path: Path | str | None = None,  # None = in-place
) -> Path
```

Явная (не lazy) миграция legacy pickle в новый формат.

### read_manifest

```python
from engines.persistence_safe import read_manifest

manifest = read_manifest(path) -> dict[str, Any]
```

Возвращает только manifest.json без загрузки массивов — удобно для UI (показать model_version, дату создания).

---

## Совместимость

| Aurora версия | Может читать aurora-model | Может писать aurora-model |
|---|---|---|
| ≤ v2.0.x | НЕТ | НЕТ (только pickle) |
| v2.1.0+ | ДА | ДА (lazy migration legacy на чтении) |

**Откат на старую версию Aurora после миграции:** не поддерживается. Backup `.pre_safe_migration` позволяет вручную восстановить старый pickle, если он не был удалён.

---

## Дальнейшее развитие

В планах для v2.2.0 (см. `docs/v2_2_0_backlog.md`):

- Полное удаление pickle (даже legacy load path) — после уверенности что все клиенты мигрировали
- Хеш каждого члена в manifest (защита от модификации внутри ZIP без перерасчёта SHA-256)
- Дополнительные форматы для совместимости (например HDF5 экспорт для академических задач)
- Документация формата для аудита внешними рецензентами

---

## Связанные документы

- `docs/MASTER_PLAN_v2_1_0.md` — план цикла v2.1.0, см. Партию 2
- `docs/v2_2_0_backlog.md` — отложенные пункты, в т.ч. полное удаление pickle
- `sidecar/econometrica/engines/persistence_safe.py` — реализация
- `sidecar/econometrica/tests/test_persistence_safe.py` — 59 тестов (round-trip, security, lazy migration)
