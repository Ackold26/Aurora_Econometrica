# Security Audit: aurora-model format — v2.1.0 (Партия 2)

**Дата:** 2026-05-16  
**Аудитор:** Red-team (automated security review)  
**Ветка:** `feat/v2.0.0-explicit-mode-wizard`  
**Baseline:** 59 тестов, все проходят  

---

## Итоги

| ID | Severity | Статус |
|---|---|---|
| SH-AM-01 | Medium | Атомарная запись — без корrupции, но без read-lock |
| SH-AM-02 | Low | Path traversal через symlink при чтении |
| SH-AM-03 | Low | Zip-bomb: size=0 в central dir + CRC защищает |
| SH-AM-04 | Medium | Numpy object arrays: silent data loss при save→load |
| SH-AM-05 | High | sha256_data в manifest НЕ верифицируется при load |
| SH-AM-06 | Low | datetime.fromisoformat — нет уязвимостей |
| SH-AM-07 | High | Recursion bomb: depth≥998 → RecursionError (DoS) |
| SH-AM-08 | Low | Memory exhaustion: защита работает корректно |
| SH-AM-09 | Low | TOCTOU: не является вектором RCE |
| SH-AM-10 | Low | Lazy migration backup race: stale backup при повторной миграции |
| SH-AM-11 | Medium | Concurrent save без lock в modeler.py / ols_modeler.py |
| SH-AM-12 | Medium | SHA-256 sidecar verify gap для aurora-model |

---

## SH-AM-01 — Atomic Write Race

**Severity:** Medium  
**Vector:** Два процесса одновременно пишут в `latest.pkl`.

**Анализ:**  
`save_model_safe` использует `tempfile.mkstemp(dir=target.parent)` + `os.replace(tmp, target)`. `mkstemp` гарантирует уникальное имя для каждого процесса через OS. Конкурентная запись: оба процесса создают разные tmp-файлы, оба делают `os.replace`. На Windows `MoveFileExW` и POSIX `rename(2)` — атомарны в рамках одного тома. **Последний `os.replace` выигрывает, данные не корruptятся**.

Однако нет гарантии **read-your-writes** — процесс A сохранил, процесс B сохранил поверх через 5ms, процесс A читает данные B. Для desktop single-user приложения это приемлемо, но `save_v20_diagnostics` имеет `project_lock`, а прямой `save_model_safe` в `modeler.py` — нет (см. SH-AM-11).

**PoC:** Два потока вызывают `save_model_safe` на один путь — no corruption confirmed, last-writer-wins.

**Recommendation:** Документировать как known behavior. Для критических читателей (диагностика) использовать `project_lock`.

---

## SH-AM-02 — Path Traversal через Symlink

**Severity:** Low  
**Vector:** Атакующий создаёт символическую ссылку `latest.pkl -> /shared/malicious.zip`.

**Анализ:**  
`load_model_safe` следует symlinks через `Path.exists()` и `open()`. Если symlink указывает на произвольный ZIP-файл, он будет прочитан и разобран. Однако:
1. Для **write**: `os.replace(tmp, target)` на POSIX заменяет **саму symlink запись**, не файл-цель — запись через symlink невозможна.
2. Для **read**: атакующий, способный создать symlink в папке проекта, уже имеет write-доступ к FS — это более широкий security boundary violation.
3. Worst-case при read через symlink: загрузка произвольного aurora-model ZIP → подмена `model_data` dict без RCE (нет `pickle.load`).

**PoC:** `os.symlink('/shared/evil.zip', 'project/models/latest.pkl')` → `load_model_with_compat` загрузит evil.zip как aurora-model.

**Recommendation:** Добавить `Path.resolve()` + проверку что resolved path находится в разрешённых корнях проекта (`APPDATA/aurora-econometrica-gui/`). Низкий приоритет для single-user desktop.

---

## SH-AM-03 — Zip-Bomb: Central Directory Size=0 Bypass

**Severity:** Low  
**Vector:** Атакующий патчит `file_size=0` в central directory entries чтобы обойти `sum(info.file_size) > MAX_TOTAL_UNCOMPRESSED`.

**Анализ (PoC проверен):**  
При патче `file_size=0` В central dir И `CRC=0` в обоих заголовках: Python читает 0 байт из member, CRC совпадает (CRC пустой строки = 0). Обход суммы возможен, но **реальные данные не извлекаются** (Python использует `file_size` в local header для определения количества байт для декомпрессии).

При патче `file_size=0` но оставлении **реального CRC**: Python извлекает 0 байт, CRC не совпадает с CRC реального контента → `BadZipFile: Bad CRC-32`. Декомпрессия реального payload блокируется.

Вывод: атака «патч size=0 + реальный payload» **невозможна** из-за CRC enforcement в Python's zipfile. Защита через `sum(info.file_size)` устойчива.

**Recommendation:** Дыр нет. Для defence-in-depth можно добавить проверку compressed_size на разумность (compressed > uncompressed = подозрительно для ненулевых файлов), но не критично.

---

## SH-AM-04 — Numpy Object Arrays: Silent Data Loss

**Severity:** Medium  
**Vector:** Модель содержит `numpy.ndarray` с `dtype=object` (строки, dict и др.). `save_model_safe` сохраняет без ошибки, но `load_model_safe` падает с `CorruptArchiveError`.

**PoC (воспроизведён):**
```python
arr = np.array(['tv', 'digital', 'ooh'], dtype=object)  # или structured с object subfield
save_model_safe({'channels': arr}, path)  # SUCCEED — file written
load_model_safe(path)  # FAIL: CorruptArchiveError (allow_pickle=False)
```

**Корень:** `np.savez(buffer, **arrays)` сохраняет object arrays через pickle (встроенный механизм numpy). `np.load(allow_pickle=False)` затем отвергает такие arrays. `save_model_safe` не проверяет dtype перед записью.

Это **data integrity bug**, не security RCE. Калькулятор сохраняет успешно, но созданная модель неработоспособна.

**Recommendation:** В `_split_arrays`, ветка `isinstance(value, np.ndarray)`, добавить:
```python
if value.dtype == object or (value.dtype.names and any(
    value.dtype[n] == object for n in value.dtype.names
)):
    raise UnsupportedTypeError(
        f'numpy object arrays не поддерживаются: путь {path}. '
        'Конвертируйте строки в список Python (list).'
    )
```

---

## SH-AM-05 — sha256_data Не Верифицируется при Load

**Severity:** High  
**Vector:** Атакующий с доступом к shared папке подменяет `data.json` внутри `latest.pkl` и обновляет `manifest.json::sha256_data` в соответствии с новым контентом. `load_model_safe` принимает подменённые данные без детектирования.

**PoC (воспроизведён):**
```python
# Атакующий:
# 1. Открывает latest.pkl как ZIP
# 2. Заменяет data.json: {"budget": 1_000_000} -> {"budget": 9_999_999}
# 3. Пересчитывает sha256_data для нового data.json
# 4. Записывает новый manifest.json с обновлённой sha256_data
# 5. Записывает новый ZIP

# load_model_safe:
loaded = load_model_safe(tampered_path)
loaded['budget']  # -> 9_999_999 (успешно!)
```

**Важно:** SHA-256 sidecar (`.sha256` файл) для aurora-model **не используется** при load (только для legacy pickle). `manifest.sha256_data` вычисляется при save, но **никогда не проверяется** при load.

Атакующий вынужден пересчитать sha256_data (тривиально: `hashlib.sha256(new_data_bytes).hexdigest()`), поэтому даже если бы sidecar проверялся — он тоже нужно обновить.

**Истинная защита** требует: либо (a) внешний доверенный хеш (sidecar, подписанный приватным ключом), либо (b) проверка sha256_data при load + **без возможности переписать manifest** (например, HMAC с ключом, хранящимся вне файла).

**Recommendation (краткосрочное):** Добавить верификацию `sha256_data` при загрузке в `load_model_safe`:
```python
if 'sha256_data' in manifest:
    actual_sha = hashlib.sha256(data_raw).hexdigest()
    if actual_sha != manifest['sha256_data']:
        raise CorruptArchiveError(
            f'data.json SHA-256 mismatch: manifest={manifest["sha256_data"][:16]}.., '
            f'actual={actual_sha[:16]}.. — возможна подмена данных.'
        )
```
Это **не защищает** от атакующего, который модифицирует и manifest, и data.json, но **детектирует** случайное повреждение и простые подмены без пересчёта хеша. Полная защита (HMAC) — в backlog v2.2.0.

---

## SH-AM-06 — Datetime Injection

**Severity:** Low  
**Vector:** `{"__datetime__": "<malicious>"}` в data.json использует `datetime.fromisoformat()`.

**Анализ (проверен):**  
`datetime.fromisoformat()` в CPython 3.11+ расширен (принимает больше форматов), но:
- Null bytes → `ValueError: Invalid isoformat string` (rejected)
- Слишком длинные строки → `ValueError` (rejected)
- Неправильный формат → `ValueError` (rejected, преобразуется в `CorruptArchiveError`)
- Week notation (`2026-W01-1`) принимается — это легитимный ISO 8601
- Нет code execution surface (fromisoformat — pure parser, не eval)

**Дыр не нашёл.** `CorruptArchiveError` wrapping защищает.

---

## SH-AM-07 — Recursion Bomb (DoS)

**Severity:** High  
**Vector:** Атакующий создаёт aurora-model с `data.json` глубиной вложенности ≥998 уровней. Вызов `load_model_safe` приводит к `RecursionError` (crash sidecar процесса).

**PoC (воспроизведён):**
```python
depth = 998
s = '{"k":' * depth + '1' + '}' * depth  # 5989 байт JSON
# Упаковываем в aurora-model ZIP (300 байт после deflate)
# При load_model_safe -> json.loads OK (C impl) -> _merge_arrays рекурсирует -> RecursionError
```

**Механизм:** `json.loads` — C-реализация, не упирается в Python recursion limit. Но `_merge_arrays` и `_split_arrays` — чистый Python, рекурсируют по глубине dict. При depth=998 → `RecursionError` в `_merge_arrays` на строке `return {k: _merge_arrays(v, arrays) for k, v in data.items()}`.

Аналогично при save: `_split_arrays` падает при depth≥998.

**Recommendation:** Добавить проверку глубины перед рекурсией (или итеративный обход):
```python
MAX_NESTING_DEPTH = 64  # реальные модели не превышают ~10-15 уровней

def _split_arrays(value, arrays, path='$', _depth=0):
    if _depth > MAX_NESTING_DEPTH:
        raise UnsupportedTypeError(
            f'Превышена максимальная глубина вложенности ({MAX_NESTING_DEPTH}): путь {path}.'
        )
    # ... остальной код с _depth+1 в рекурсивных вызовах
```

---

## SH-AM-08 — Memory Exhaustion

**Severity:** Low  
**Vector:** Большие массивы проходят проверку `file_size`, но при unzip раздуваются.

**Анализ (проверен):**  
Два уровня защиты:
1. `p.stat().st_size > MAX_TOTAL_UNCOMPRESSED` — outer bound (файл на диске не может быть больше лимита, а lossless compression сжимает, не раздувает)
2. `sum(info.file_size for info in zf.infolist()) > MAX_TOTAL_UNCOMPRESSED` — inner bound (агрегированный uncompressed size всех members)

Попытка обхода через patched `file_size=0` в central dir блокируется CRC enforcement (см. SH-AM-03). Multi-member bomb (N × 300MB членов) блокируется суммой. **Дыр не найдено.**

---

## SH-AM-09 — TOCTOU (Time-of-Check-to-Time-of-Use)

**Severity:** Low  
**Vector:** Файл подменяется между `detect_format()` и `load_model_safe()` в `load_model_with_compat`.

**Анализ:**  
`load_model_safe` **независимо** проверяет формат через `zipfile.is_zipfile(p)` (magic bytes check). Если атакующий подменит aurora-model на pickle между `detect_format` и `load_model_safe`:
- `zipfile.is_zipfile` → `False` → `CorruptArchiveError` (не `pickle.load`)
- Нет RCE, нет кода из pickle

TOCTOU **не является вектором RCE** в данной архитектуре.

---

## SH-AM-10 — Lazy Migration Backup Race

**Severity:** Low  
**Vector:** `_lazy_migrate_to_safe` пропускает создание backup если `.pre_safe_migration` уже существует.

**Анализ:**
```python
if not backup.exists():
    shutil.copy2(legacy_path, backup)
```
Если backup существует (от предыдущей миграции), код **пропускает** копирование и продолжает перезапись оригинала. Сценарий: первая миграция создала backup, затем пользователь вручную восстановил старый pickle (из backup), затем повторная миграция — backup из первой миграции сохраняется (возможно устаревший).

**Последствие:** Пользователь теряет возможность полного отката — backup хранит первую версию, не последнюю pre-migration версию.

**Recommendation:** Добавить timestamp suffix к backup или проверять размер/mtime перед пропуском.

---

## SH-AM-11 — Concurrent Multi-Tab Save без Lock

**Severity:** Medium  
**Vector:** `modeler.py::save_model_safe(model_data, model_path)` и `ols_modeler.py::save_model_safe(model_data, model_path)` вызываются **без `project_lock`**.

**Анализ:**  
`save_v20_diagnostics` защищён `project_lock`. Но основная тренировка (modeler.py, ols_modeler.py) вызывает `save_model_safe` напрямую без блокировки. Concurrent scenarios:

1. **Два обучения одновременно** (маловероятно в desktop) → last-writer-wins, no corruption (atomic rename)
2. **Обучение + save_v20_diagnostics одновременно** → одна запись перетрёт другую → диагностика потеряна или модель старая

Это **data race**, не security уязвимость. Для multi-tab desktop приложения реален только сценарий 2.

**Recommendation:** Обернуть `save_model_safe` в modeler.py и ols_modeler.py в `project_lock`, аналогично `save_v20_diagnostics`.

---

## SH-AM-12 — SHA-256 Sidecar Verify Gap для Aurora-Model

**Severity:** Medium  
**Vector:** При загрузке aurora-model через `load_model_with_compat` sidecar `.sha256` **не проверяется** (только для legacy pickle).

**Анализ:**  
Спецификация говорит: «aurora-model не нуждается в sidecar (zip CRC32 + structural validation)». Но:

1. ZIP CRC32 защищает от **битовых ошибок**, не от **преднамеренной подмены**
2. Атакующий может полностью перезаписать `latest.pkl` новым ZIP с другими данными
3. Старый sidecar `.sha256` будет несоответствовать — но он **не проверяется**

После `save_model_safe` + `write_pkl_sha256_sidecar` в `modeler.py` sidecar корректен. Но при следующем load `verify_pkl_sha256_sidecar` **не вызывается** для aurora-model пути.

Замечание: `manifest.sha256_data` мог бы служить tamper detection, но он тоже не проверяется при load (см. SH-AM-05). Итого: **aurora-model имеет нулевой tamper detection при load**, хуже чем legacy pickle (хотя бы sidecar verify).

**Recommendation:** Либо (a) вызывать `verify_pkl_sha256_sidecar` для aurora-model тоже, либо (b) реализовать `sha256_data` verification в `load_model_safe` (см. SH-AM-05). Одно из двух достаточно.

---

## Выводы

### Критические находки (требуют фикса до релиза)

| ID | Что делать |
|---|---|
| **SH-AM-07** | Добавить `MAX_NESTING_DEPTH=64` в `_split_arrays` / `_merge_arrays` |
| **SH-AM-05** | Добавить `sha256_data` verification в `load_model_safe` |
| **SH-AM-04** | Reject object dtype arrays в `_split_arrays` с внятным `UnsupportedTypeError` |

### Важные (фикс в v2.1.0 или hotfix)

| ID | Что делать |
|---|---|
| **SH-AM-12** | Добавить sidecar verify для aurora-model пути в `load_model_with_compat` |
| **SH-AM-11** | Добавить `project_lock` в modeler.py / ols_modeler.py save path |

### Низкий приоритет (backlog v2.2.0)

| ID | Примечание |
|---|---|
| SH-AM-01 | Документировать last-writer-wins семантику |
| SH-AM-02 | Path.resolve() + allowed roots check для сетевых папок |
| SH-AM-10 | Timestamp suffix в backup name |

### Что выдержало аудит

- ZIP-bomb защита (двойная: stat + uncompressed sum) — **устойчива**
- Path traversal внутри ZIP (абс. пути, `..`, `\`) — **заблокирован**
- Datetime injection через `fromisoformat` — **нет уязвимостей**
- Numpy pickle payload в arrays.npz — **заблокирован allow_pickle=False**
- TOCTOU detect_format → load_model_safe — **не вектор RCE**
- Атомарность записи (temp + os.replace) — **работает корректно**
- Memory exhaustion через multi-member bomb — **защита устойчива**
- `extra_manifest` override protect (`format`/`format_version`) — **работает**
