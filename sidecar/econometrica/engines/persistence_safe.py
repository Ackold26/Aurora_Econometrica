"""Безопасный формат сохранения моделей Aurora MMM Optimizer.

Заменяет устаревший pickle на закрытый формат `aurora-model-v1` —
ZIP-архив с тремя записями:

  manifest.json — версия формата, timestamp, контрольные суммы
  data.json     — все JSON-сериализуемые поля model_data
                  (numpy arrays заменены placeholder'ами)
  arrays.npz    — все numpy arrays (npz, allow_pickle=False)

Безопасность:
  * `json.load` не выполняет произвольный код (в отличие от pickle.load)
  * `numpy.load(..., allow_pickle=False)` отклоняет pickle-payload даже
    если злоумышленник попытается подменить arrays.npz
  * При load проверяем magic bytes — отвергаем не-ZIP файлы
  * Защита от zip-bomb (MAX_TOTAL_UNCOMPRESSED + MAX_FILES)
  * Защита от path-traversal внутри ZIP (member names проверяются)

Совместимость:
  * Имя файла остаётся `latest.pkl` (40+ hardcoded references в Rust/Python/Svelte)
  * При load детектим первые 4 байта:
        b'PK\\x03\\x04' → новый формат (load_model_safe)
        b'\\x80\\x04'    → legacy pickle (load_model_with_compat fallback)
  * Lazy migration — старый .pkl продолжает читаться, но при следующем
    save переписывается в новый формат

Поддерживаемые типы в data.json:
  * dict с string keys (для не-string keys → ValueError при save)
  * list / tuple (tuple → list при load — JSON ограничение)
  * str / bool / int / float (без NaN/Inf)
  * None
  * numpy.ndarray (любой dtype/shape) — через placeholder + arrays.npz
  * numpy скаляры (int64/float32/etc) → конвертируются в Python primitives
  * datetime.datetime → ISO 8601 строка

Не поддерживается (вызывает ValueError при save):
  * bytes / bytearray (можно добавить позже через base64)
  * custom classes / callables / functools.partial
  * pandas DataFrame / Series (caller должен сам конвертировать)
  * sets / frozensets
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ─── Константы формата ────────────────────────────────────────────────────

FORMAT_NAME = 'aurora-model'
FORMAT_VERSION = '1'

ZIP_MAGIC = b'PK\x03\x04'
PICKLE_MAGIC_PREFIXES = (b'\x80\x02', b'\x80\x03', b'\x80\x04', b'\x80\x05')

MANIFEST_FILENAME = 'manifest.json'
DATA_FILENAME = 'data.json'
ARRAYS_FILENAME = 'arrays.npz'

# Защита от zip-bomb. Текущий размер pickle ~5MB на крупный проект,
# с posterior samples float32 ~ 1-3MB. Лимит 500MB даёт запас x100.
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024  # 500 MB
MAX_FILES = 16  # manifest + data + arrays + запас для будущих расширений
MAX_MEMBER_NAME_LEN = 200

# SH-AM-07: защита от recursion bomb. Глубина 64 уровней покрывает все реальные
# структуры model_data (~3-4 уровня вложенности), но блокирует deeply-nested
# атакующий payload, который вызвал бы RecursionError при `_split_arrays`/`_merge_arrays`.
MAX_NESTING_DEPTH = 64

# JSON ключ-маркер для placeholder'а numpy array
NUMPY_PLACEHOLDER_KEY = '__numpy_array__'


class SafeModelFormatError(Exception):
    """Базовое исключение для ошибок формата aurora-model."""


class UnsupportedTypeError(SafeModelFormatError):
    """Тип значения не поддерживается безопасным форматом."""


class CorruptArchiveError(SafeModelFormatError):
    """ZIP-архив повреждён, не соответствует ожидаемой структуре,
    или содержит подозрительные member names / превышает лимиты."""


# ─── Детектор формата ────────────────────────────────────────────────────


def detect_format(path: Path | str) -> str:
    """Определяет формат сохранения по первым байтам файла.

    Returns:
        'aurora-model' — новый безопасный формат (ZIP).
        'pickle'        — устаревший pickle (legacy).
        'unknown'       — файл не существует, пустой, или неопознанный формат.
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size < 4:
        return 'unknown'
    with open(p, 'rb') as f:
        head = f.read(4)
    if head.startswith(ZIP_MAGIC):
        return 'aurora-model'
    if any(head.startswith(prefix) for prefix in PICKLE_MAGIC_PREFIXES):
        return 'pickle'
    return 'unknown'


# ─── Сериализация data.json (numpy → placeholder) ────────────────────────


def _is_numpy_scalar(v: Any) -> bool:
    return isinstance(v, (np.integer, np.floating, np.bool_, np.complexfloating))


def _convert_numpy_scalar(v: Any) -> Any:
    """numpy скаляры → Python primitives. NaN/Inf → ValueError (JSON-illegal)."""
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        f = float(v)
        if f != f or f in (float('inf'), float('-inf')):
            raise UnsupportedTypeError(
                f'NaN/Inf в скалярном поле недопустимо в data.json: {v!r}. '
                'Используйте None или сохраните как numpy array.'
            )
        return f
    if isinstance(v, np.complexfloating):
        raise UnsupportedTypeError(
            f'Комплексные числа не поддерживаются: {v!r}.'
        )
    return v


def _split_arrays(
    value: Any,
    arrays: dict[str, np.ndarray],
    path: str = '$',
    depth: int = 0,
) -> Any:
    """Рекурсивно обходит value, выделяет numpy arrays в arrays dict.

    Возвращает «очищенную» структуру: numpy arrays заменены на placeholder
    `{NUMPY_PLACEHOLDER_KEY: <unique_name>}`. Имена в arrays формируются
    по пути доступа: `posterior_samples.media_betas`, `params.0.weights`.

    SH-AM-07: depth ограничен `MAX_NESTING_DEPTH` для защиты от recursion bomb.

    Raises:
        UnsupportedTypeError: если встречен неподдерживаемый тип или превышен лимит глубины.
    """
    if depth > MAX_NESTING_DEPTH:
        raise UnsupportedTypeError(
            f'Глубина вложенности > {MAX_NESTING_DEPTH} (защита от recursion bomb): путь {path}.'
        )
    if value is None or isinstance(value, (bool, int, str)):
        # int обрабатывается до проверки на bool — потому что bool это subclass int,
        # но мы хотим сохранить тип. JSON не различает int/bool явно, но Python да.
        return value

    if isinstance(value, float):
        if value != value or value in (float('inf'), float('-inf')):
            raise UnsupportedTypeError(
                f'NaN/Inf в скалярном поле недопустимо: путь {path}, значение {value!r}.'
            )
        return value

    if _is_numpy_scalar(value):
        return _convert_numpy_scalar(value)

    if isinstance(value, datetime):
        # ISO 8601 c timezone. Если naive — assume UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return {'__datetime__': value.isoformat()}

    if isinstance(value, np.ndarray):
        # SH-AM-04: object arrays несут pickle-payload даже при np.savez —
        # отвергаем при save чтобы избежать silent data loss при load с
        # allow_pickle=False.
        if value.dtype == object or value.dtype.kind in ('O', 'V'):
            raise UnsupportedTypeError(
                f'numpy.ndarray с dtype={value.dtype} (object/structured) не '
                f'поддерживается — pickle-payload блокируется allow_pickle=False. '
                f'Путь {path}. Сконвертируйте в numeric array или list/dict.'
            )
        # Уникальное имя на основе пути. Двоеточия / точки / индексы → подчёркивания.
        name = _path_to_array_name(path)
        # Если имя коллидирует — добавляем суффикс.
        base = name
        suffix = 1
        while name in arrays:
            name = f'{base}__{suffix}'
            suffix += 1
        arrays[name] = value
        return {
            NUMPY_PLACEHOLDER_KEY: name,
            'shape': list(value.shape),
            'dtype': str(value.dtype),
        }

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise UnsupportedTypeError(
                    f'Не-строковый ключ dict не поддерживается: путь {path}, '
                    f'ключ {k!r} тип {type(k).__name__}.'
                )
            out[k] = _split_arrays(v, arrays, f'{path}.{k}', depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        return [_split_arrays(v, arrays, f'{path}[{i}]', depth + 1) for i, v in enumerate(value)]

    if isinstance(value, (bytes, bytearray)):
        raise UnsupportedTypeError(
            f'bytes/bytearray не поддерживается в этом формате: путь {path}. '
            'Если нужно — кодируйте в base64 строку явно.'
        )

    if isinstance(value, (set, frozenset)):
        raise UnsupportedTypeError(
            f'set/frozenset не поддерживается: путь {path}. '
            'Конвертируйте в sorted list.'
        )

    raise UnsupportedTypeError(
        f'Тип {type(value).__name__} не поддерживается: путь {path}, значение {value!r}.'
    )


def _path_to_array_name(path: str) -> str:
    """`$.posterior_samples.media_betas` → `posterior_samples__media_betas`.

    Имя должно быть валидным npz member name и достаточно уникальным,
    чтобы при коллизии добавление суффикса было редким.
    """
    # Удаляем root `$.` или `$`
    if path.startswith('$.'):
        path = path[2:]
    elif path.startswith('$'):
        path = path[1:]
    name = path.replace('.', '__').replace('[', '_').replace(']', '')
    if not name:
        name = 'root'
    return name[:MAX_MEMBER_NAME_LEN - len('arrays_'):]  # запас на префикс


def _merge_arrays(data: Any, arrays: dict[str, np.ndarray], depth: int = 0) -> Any:
    """Обратное преобразование: placeholder → numpy array.

    Рекурсивно обходит десериализованный JSON, заменяет placeholder'ы
    реальными arrays из загруженного npz.

    SH-AM-07: depth ограничен `MAX_NESTING_DEPTH` для защиты от recursion bomb.

    Raises:
        CorruptArchiveError: если placeholder ссылается на отсутствующий array
            или превышена глубина вложенности.
    """
    if depth > MAX_NESTING_DEPTH:
        raise CorruptArchiveError(
            f'Глубина вложенности > {MAX_NESTING_DEPTH} в data.json '
            '(защита от recursion bomb).'
        )
    if isinstance(data, dict):
        if NUMPY_PLACEHOLDER_KEY in data:
            name = data[NUMPY_PLACEHOLDER_KEY]
            if name not in arrays:
                raise CorruptArchiveError(
                    f'data.json ссылается на numpy array {name!r}, '
                    f'но он отсутствует в arrays.npz.'
                )
            return arrays[name]
        if '__datetime__' in data:
            try:
                return datetime.fromisoformat(data['__datetime__'])
            except ValueError as exc:
                raise CorruptArchiveError(
                    f'Некорректный datetime в data.json: {exc}'
                ) from exc
        return {k: _merge_arrays(v, arrays, depth + 1) for k, v in data.items()}
    if isinstance(data, list):
        return [_merge_arrays(v, arrays, depth + 1) for v in data]
    return data


# ─── save_model_safe / load_model_safe ───────────────────────────────────


def save_model_safe(
    model_data: dict[str, Any],
    path: Path | str,
    *,
    extra_manifest: dict[str, Any] | None = None,
) -> str:
    """Атомарно сохраняет model_data в формате aurora-model.

    Args:
        model_data: dict с любыми сериализуемыми полями (см. модуль docstring).
        path: целевой путь (обычно models/latest.pkl).
        extra_manifest: дополнительные ключи в manifest.json (опционально).

    Returns:
        SHA-256 hex digest финального файла (для записи в sidecar).

    Raises:
        UnsupportedTypeError: если model_data содержит неподдерживаемый тип.
        OSError: при ошибках записи.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    arrays: dict[str, np.ndarray] = {}
    cleaned = _split_arrays(model_data, arrays, '$')

    manifest = {
        'format': FORMAT_NAME,
        'format_version': FORMAT_VERSION,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'array_count': len(arrays),
        'model_version': model_data.get('model_version', 'unknown'),
    }
    if extra_manifest:
        # extra_manifest имеет приоритет над defaults, но не может переопределить
        # `format` / `format_version` — это контракт.
        for k, v in extra_manifest.items():
            if k in ('format', 'format_version'):
                continue
            manifest[k] = v

    # Сериализуем bytes для каждого члена архива
    manifest_bytes = json.dumps(
        manifest, indent=2, ensure_ascii=False, allow_nan=False,
    ).encode('utf-8')
    data_bytes = json.dumps(
        cleaned, indent=None, ensure_ascii=False, allow_nan=False, separators=(',', ':'),
    ).encode('utf-8')

    arrays_buffer = io.BytesIO()
    if arrays:
        # allow_pickle=False по умолчанию в новых numpy. Явно `np.savez` без
        # `_pickle` варианта — безопасный путь.
        np.savez(arrays_buffer, **arrays)
    arrays_bytes = arrays_buffer.getvalue()

    # Контрольные суммы — для логов и опционального чтения при load.
    manifest['sha256_data'] = hashlib.sha256(data_bytes).hexdigest()
    if arrays_bytes:
        manifest['sha256_arrays'] = hashlib.sha256(arrays_bytes).hexdigest()
    # Перезаписываем manifest_bytes с обновлёнными контрольными суммами.
    manifest_bytes = json.dumps(
        manifest, indent=2, ensure_ascii=False, allow_nan=False,
    ).encode('utf-8')

    # Атомарная запись: temp file в том же каталоге + os.replace.
    fd, tmp_path_str = tempfile.mkstemp(
        dir=target.parent, suffix='.aurora-model.tmp', prefix=target.stem + '_',
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, 'wb') as raw:
            with zipfile.ZipFile(
                raw, mode='w', compression=zipfile.ZIP_DEFLATED, compresslevel=6,
            ) as zf:
                # Порядок важен — manifest сначала, чтобы при streaming read
                # можно было быстро проверить формат.
                zf.writestr(MANIFEST_FILENAME, manifest_bytes)
                zf.writestr(DATA_FILENAME, data_bytes)
                if arrays_bytes:
                    zf.writestr(ARRAYS_FILENAME, arrays_bytes)
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    # SHA-256 финального файла — caller может записать в sidecar для tamper-detect.
    final_sha = _compute_file_sha256(target)
    logger.info(
        'save_model_safe: записан %s (формат %s v%s, arrays=%d, sha256=%s)',
        target, FORMAT_NAME, FORMAT_VERSION, len(arrays), final_sha[:16],
    )
    return final_sha


def load_model_safe(path: Path | str) -> dict[str, Any]:
    """Загружает model_data из файла в формате aurora-model.

    Args:
        path: путь к файлу.

    Returns:
        dict — восстановленный model_data с numpy arrays.

    Raises:
        FileNotFoundError: файл не существует.
        CorruptArchiveError: ZIP повреждён, превышены лимиты, или подозрительные member.
        SafeModelFormatError: некорректная структура манифеста.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'Файл модели не найден: {p}')

    file_size = p.stat().st_size
    if file_size > MAX_TOTAL_UNCOMPRESSED:
        raise CorruptArchiveError(
            f'Файл превышает лимит {MAX_TOTAL_UNCOMPRESSED} байт ({file_size} получено). '
            'Возможно повреждение или подозрительное содержимое.'
        )

    if not zipfile.is_zipfile(p):
        raise CorruptArchiveError(
            f'{p} не является ZIP-архивом. Используйте detect_format() для '
            'роутинга legacy pickle через load_model_with_compat().'
        )

    with zipfile.ZipFile(p, mode='r') as zf:
        members = zf.namelist()
        if len(members) > MAX_FILES:
            raise CorruptArchiveError(
                f'ZIP содержит {len(members)} файлов (лимит {MAX_FILES}).'
            )
        for name in members:
            if len(name) > MAX_MEMBER_NAME_LEN:
                raise CorruptArchiveError(
                    f'Член ZIP с слишком длинным именем ({len(name)} > {MAX_MEMBER_NAME_LEN}): '
                    f'{name[:64]}...'
                )
            # Path traversal — отвергаем абсолютные пути и `..`.
            if name.startswith('/') or '..' in name.split('/') or '\\' in name:
                raise CorruptArchiveError(
                    f'Подозрительный member name (path traversal): {name!r}.'
                )

        # Сумма uncompressed sizes — protection from zip-bomb.
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        if total_uncompressed > MAX_TOTAL_UNCOMPRESSED:
            raise CorruptArchiveError(
                f'Распакованный размер {total_uncompressed} превышает лимит '
                f'{MAX_TOTAL_UNCOMPRESSED} (zip-bomb защита).'
            )

        if MANIFEST_FILENAME not in members:
            raise SafeModelFormatError(
                f'В ZIP отсутствует {MANIFEST_FILENAME}.'
            )
        if DATA_FILENAME not in members:
            raise SafeModelFormatError(
                f'В ZIP отсутствует {DATA_FILENAME}.'
            )

        manifest_raw = zf.read(MANIFEST_FILENAME)
        try:
            manifest = json.loads(manifest_raw.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SafeModelFormatError(f'Некорректный manifest.json: {exc}') from exc

        if manifest.get('format') != FORMAT_NAME:
            raise SafeModelFormatError(
                f'Неожиданный format={manifest.get("format")!r}, ожидалось {FORMAT_NAME!r}.'
            )
        fv = str(manifest.get('format_version', ''))
        if fv != FORMAT_VERSION:
            # Forward-compat: предупреждаем но пытаемся прочесть.
            logger.warning(
                'Файл сохранён в format_version=%s, текущий читает v%s. '
                'Попытка прочитать, но обновите Aurora до последней версии.',
                fv, FORMAT_VERSION,
            )

        data_raw = zf.read(DATA_FILENAME)

        # SH-AM-05: verify sha256_data перед парсингом — атакующий может
        # подменить data.json с валидным JSON но повреждённой структурой.
        # Манифест хранит digest, мы его проверяем; mismatch → CorruptArchiveError.
        expected_data_sha = manifest.get('sha256_data')
        if expected_data_sha and isinstance(expected_data_sha, str) and len(expected_data_sha) == 64:
            actual_data_sha = hashlib.sha256(data_raw).hexdigest()
            if actual_data_sha != expected_data_sha:
                raise CorruptArchiveError(
                    f'sha256_data mismatch: manifest={expected_data_sha[:8]}.., '
                    f'actual={actual_data_sha[:8]}.. — data.json подменён.'
                )

        try:
            data = json.loads(data_raw.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SafeModelFormatError(f'Некорректный data.json: {exc}') from exc

        arrays: dict[str, np.ndarray] = {}
        if ARRAYS_FILENAME in members:
            arrays_raw = zf.read(ARRAYS_FILENAME)

            # SH-AM-05: verify sha256_arrays аналогично.
            expected_arrays_sha = manifest.get('sha256_arrays')
            if expected_arrays_sha and isinstance(expected_arrays_sha, str) and len(expected_arrays_sha) == 64:
                actual_arrays_sha = hashlib.sha256(arrays_raw).hexdigest()
                if actual_arrays_sha != expected_arrays_sha:
                    raise CorruptArchiveError(
                        f'sha256_arrays mismatch: manifest={expected_arrays_sha[:8]}.., '
                        f'actual={actual_arrays_sha[:8]}.. — arrays.npz подменён.'
                    )

            try:
                with np.load(
                    io.BytesIO(arrays_raw), allow_pickle=False,
                ) as npz:
                    arrays = {name: npz[name].copy() for name in npz.files}
            except ValueError as exc:
                raise CorruptArchiveError(
                    f'Не удалось распаковать arrays.npz (возможно pickle payload, '
                    f'который заблокирован allow_pickle=False): {exc}'
                ) from exc

    model_data = _merge_arrays(data, arrays)
    if not isinstance(model_data, dict):
        raise SafeModelFormatError(
            f'Ожидался dict на верхнем уровне data.json, получен {type(model_data).__name__}.'
        )
    return model_data


# ─── Конверсия legacy pickle → aurora-model ──────────────────────────────


def migrate_pickle_to_safe(
    source_pickle: Path | str,
    target_path: Path | str | None = None,
) -> Path:
    """Загружает legacy pickle и пересохраняет в безопасном формате.

    По умолчанию target_path = source_pickle (in-place замена с backup).
    Создаёт `.pre_safe_migration` backup перед перезаписью.

    Args:
        source_pickle: путь к существующему legacy .pkl файлу.
        target_path: куда записать новый формат. None → in-place.

    Returns:
        Путь к новому файлу.

    Raises:
        FileNotFoundError: source не существует.
        CorruptArchiveError: source уже в новом формате (не нужна миграция).
    """
    src = Path(source_pickle)
    if not src.exists():
        raise FileNotFoundError(f'Источник миграции не найден: {src}')

    fmt = detect_format(src)
    if fmt == 'aurora-model':
        raise CorruptArchiveError(
            f'{src} уже в формате aurora-model — миграция не требуется.'
        )
    if fmt != 'pickle':
        raise CorruptArchiveError(
            f'{src} имеет неопознанный формат — миграция отменена.'
        )

    # Загружаем через legacy pickle — caller должен быть уверен что файл доверенный.
    import pickle
    with open(src, 'rb') as f:
        model_data = pickle.load(f)

    if not isinstance(model_data, dict):
        raise SafeModelFormatError(
            f'Legacy pickle содержит {type(model_data).__name__} на верхнем уровне, '
            f'ожидался dict.'
        )

    target = Path(target_path) if target_path else src
    # Backup только если перезаписываем in-place.
    if target == src:
        backup = src.with_suffix(src.suffix + '.pre_safe_migration')
        import shutil
        shutil.copy2(src, backup)
        logger.info('migrate_pickle_to_safe: создан backup %s', backup)

    save_model_safe(model_data, target, extra_manifest={
        'migrated_from': 'pickle',
        'migrated_at': datetime.now(timezone.utc).isoformat(),
    })
    logger.info('migrate_pickle_to_safe: %s → aurora-model', target)
    return target


# ─── Утилиты ─────────────────────────────────────────────────────────────


def _compute_file_sha256(path: Path) -> str:
    """Стриминговый SHA-256 файла."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(64 * 1024):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(path: Path | str) -> dict[str, Any]:
    """Возвращает только manifest.json (без загрузки arrays).

    Удобно для UI-диагностики (показать model_version, created_at)
    без полной десериализации тяжёлой модели.

    Raises:
        FileNotFoundError, CorruptArchiveError, SafeModelFormatError.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'Файл не найден: {p}')
    if not zipfile.is_zipfile(p):
        raise CorruptArchiveError(f'{p} не ZIP-архив.')
    with zipfile.ZipFile(p, mode='r') as zf:
        if MANIFEST_FILENAME not in zf.namelist():
            raise SafeModelFormatError(f'Отсутствует {MANIFEST_FILENAME}')
        try:
            return json.loads(zf.read(MANIFEST_FILENAME).decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SafeModelFormatError(f'Некорректный manifest: {exc}') from exc
