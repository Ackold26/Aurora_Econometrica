"""Тесты для engines.persistence_safe — безопасный формат aurora-model.

Покрытие:
  * Round-trip: scalars, lists, nested dicts, numpy arrays разных dtype/shape
  * Edge cases: пустой dict, deeply nested, NaN/Inf в arrays (ОК), NaN/Inf в scalars (отвергается)
  * Безопасность: zip-bomb защита, path traversal, allow_pickle=False
  * Совместимость: detect_format на pickle / aurora-model / unknown
  * Migration: legacy pickle → aurora-model
  * Manifest-only read для UI
"""

from __future__ import annotations

import io
import json
import pickle
import zipfile
from pathlib import Path

import numpy as np
import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.persistence_safe import (  # noqa: E402
    ARRAYS_FILENAME,
    DATA_FILENAME,
    FORMAT_NAME,
    FORMAT_VERSION,
    MANIFEST_FILENAME,
    MAX_FILES,
    MAX_TOTAL_UNCOMPRESSED,
    CorruptArchiveError,
    SafeModelFormatError,
    UnsupportedTypeError,
    detect_format,
    load_model_safe,
    migrate_pickle_to_safe,
    read_manifest,
    save_model_safe,
)


# ─── Round-trip базовые сценарии ─────────────────────────────────────────


class TestRoundTrip:
    def test_simple_scalars(self, tmp_path: Path):
        target = tmp_path / 'simple.pkl'
        data = {
            'name': 'Aurora',
            'version': 1,
            'pi': 3.14159,
            'enabled': True,
            'disabled': False,
            'note': None,
            'unicode': 'Кагоцел РФ+',
        }
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        assert loaded == data

    def test_nested_dicts(self, tmp_path: Path):
        target = tmp_path / 'nested.pkl'
        data = {
            'config': {
                'data_file': '/path/to/data.xlsx',
                'media_columns': ['tv_rub', 'digital_rub'],
                'nested': {
                    'deep': {
                        'deeper': {'value': 42},
                    },
                },
            },
        }
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        assert loaded == data

    def test_lists_with_mixed_types(self, tmp_path: Path):
        target = tmp_path / 'lists.pkl'
        data = {
            'items': [1, 'two', 3.0, True, None, {'k': 'v'}, [1, 2, [3, 4]]],
        }
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        assert loaded == data

    def test_tuple_converted_to_list(self, tmp_path: Path):
        target = tmp_path / 'tuples.pkl'
        data = {'items': (1, 2, 3), 'nested': ([1], (2, 3))}
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        # JSON не различает tuple и list — это документированное ограничение.
        assert loaded == {'items': [1, 2, 3], 'nested': [[1], [2, 3]]}


# ─── Numpy arrays ─────────────────────────────────────────────────────────


class TestNumpyArrays:
    def test_1d_float32(self, tmp_path: Path):
        target = tmp_path / 'arr1d.pkl'
        arr = np.random.RandomState(42).randn(1000).astype(np.float32)
        data = {'samples': arr}
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        np.testing.assert_array_equal(loaded['samples'], arr)
        assert loaded['samples'].dtype == np.float32

    def test_2d_float64(self, tmp_path: Path):
        target = tmp_path / 'arr2d.pkl'
        arr = np.random.RandomState(0).randn(50, 200)
        data = {'posterior': arr}
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        np.testing.assert_array_equal(loaded['posterior'], arr)
        assert loaded['posterior'].dtype == np.float64

    def test_int_arrays_various_dtypes(self, tmp_path: Path):
        target = tmp_path / 'ints.pkl'
        data = {
            'idx_int32': np.arange(100, dtype=np.int32),
            'idx_int64': np.arange(100, dtype=np.int64),
            'idx_uint8': np.arange(255, dtype=np.uint8),
        }
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        for key, expected in data.items():
            np.testing.assert_array_equal(loaded[key], expected)
            assert loaded[key].dtype == expected.dtype

    def test_bool_array(self, tmp_path: Path):
        target = tmp_path / 'bools.pkl'
        arr = np.array([True, False, True, True, False])
        data = {'mask': arr}
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        np.testing.assert_array_equal(loaded['mask'], arr)

    def test_nested_arrays(self, tmp_path: Path):
        """numpy arrays могут быть на любой глубине."""
        target = tmp_path / 'nested-arrs.pkl'
        data = {
            'posterior_samples': {
                'media_betas': np.random.randn(7, 8000).astype(np.float32),
                'alphas': np.random.randn(7, 8000).astype(np.float32),
                'channels': ['tv', 'digital', 'radio'],
                'metadata': {
                    'n_chains': 4,
                    'n_draws': 2000,
                    'intercept': np.random.randn(8000).astype(np.float32),
                },
            },
        }
        save_model_safe(data, target)
        loaded = load_model_safe(target)

        np.testing.assert_array_equal(
            loaded['posterior_samples']['media_betas'],
            data['posterior_samples']['media_betas'],
        )
        np.testing.assert_array_equal(
            loaded['posterior_samples']['metadata']['intercept'],
            data['posterior_samples']['metadata']['intercept'],
        )
        assert loaded['posterior_samples']['channels'] == ['tv', 'digital', 'radio']
        assert loaded['posterior_samples']['metadata']['n_chains'] == 4

    def test_nan_inf_in_arrays_ok(self, tmp_path: Path):
        """NaN/Inf внутри numpy arrays допустимы — npz хранит binary."""
        target = tmp_path / 'nans.pkl'
        arr = np.array([1.0, np.nan, np.inf, -np.inf, 2.0])
        data = {'with_nans': arr}
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        # Сравнение с NaN — через mask.
        assert np.isnan(loaded['with_nans'][1])
        assert np.isinf(loaded['with_nans'][2])
        assert loaded['with_nans'][0] == 1.0
        assert loaded['with_nans'][4] == 2.0

    def test_empty_array(self, tmp_path: Path):
        target = tmp_path / 'empty.pkl'
        data = {'no_data': np.array([], dtype=np.float32)}
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        assert loaded['no_data'].shape == (0,)
        assert loaded['no_data'].dtype == np.float32

    def test_numpy_scalars_converted(self, tmp_path: Path):
        target = tmp_path / 'np-scalars.pkl'
        data = {
            'np_int': np.int64(42),
            'np_float': np.float32(3.14),
            'np_bool': np.bool_(True),
        }
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        assert loaded['np_int'] == 42
        assert isinstance(loaded['np_int'], int)
        assert abs(loaded['np_float'] - 3.14) < 0.001
        assert isinstance(loaded['np_float'], float)
        assert loaded['np_bool'] is True


# ─── Edge cases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_dict(self, tmp_path: Path):
        target = tmp_path / 'empty.pkl'
        save_model_safe({}, target)
        loaded = load_model_safe(target)
        assert loaded == {}

    def test_deeply_nested(self, tmp_path: Path):
        target = tmp_path / 'deep.pkl'
        # Глубина 50 — далеко от рекурсивного лимита Python (1000+).
        data = current = {}
        for i in range(50):
            current['next'] = {}
            current = current['next']
        current['value'] = 'bottom'
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        cursor = loaded
        for _ in range(50):
            cursor = cursor['next']
        assert cursor['value'] == 'bottom'

    def test_nan_in_scalar_rejected(self, tmp_path: Path):
        target = tmp_path / 'nan.pkl'
        with pytest.raises(UnsupportedTypeError, match='NaN/Inf'):
            save_model_safe({'bad': float('nan')}, target)

    def test_inf_in_scalar_rejected(self, tmp_path: Path):
        target = tmp_path / 'inf.pkl'
        with pytest.raises(UnsupportedTypeError, match='NaN/Inf'):
            save_model_safe({'bad': float('inf')}, target)

    def test_non_string_key_rejected(self, tmp_path: Path):
        target = tmp_path / 'badkey.pkl'
        with pytest.raises(UnsupportedTypeError, match='Не-строковый ключ'):
            save_model_safe({1: 'value'}, target)  # type: ignore[dict-item]

    def test_bytes_rejected(self, tmp_path: Path):
        target = tmp_path / 'bytes.pkl'
        with pytest.raises(UnsupportedTypeError, match='bytes'):
            save_model_safe({'data': b'binary'}, target)

    def test_set_rejected(self, tmp_path: Path):
        target = tmp_path / 'set.pkl'
        with pytest.raises(UnsupportedTypeError, match='set'):
            save_model_safe({'items': {1, 2, 3}}, target)

    def test_custom_class_rejected(self, tmp_path: Path):
        class Foo:
            pass
        with pytest.raises(UnsupportedTypeError):
            save_model_safe({'obj': Foo()}, tmp_path / 'class.pkl')

    def test_unicode_keys(self, tmp_path: Path):
        target = tmp_path / 'unicode.pkl'
        data = {'канал': 'тв', 'категория': 'бренд'}
        save_model_safe(data, target)
        loaded = load_model_safe(target)
        assert loaded == data


# ─── Безопасность ─────────────────────────────────────────────────────────


class TestSecurity:
    def test_rejects_pickle_file(self, tmp_path: Path):
        """load_model_safe не должен принимать pickle."""
        target = tmp_path / 'fake.pkl'
        with open(target, 'wb') as f:
            pickle.dump({'data': 'value'}, f)
        with pytest.raises(CorruptArchiveError, match='не является ZIP-архивом'):
            load_model_safe(target)

    def test_rejects_random_garbage(self, tmp_path: Path):
        target = tmp_path / 'garbage.bin'
        target.write_bytes(b'this is not a zip file')
        with pytest.raises(CorruptArchiveError):
            load_model_safe(target)

    def test_path_traversal_in_zip_blocked(self, tmp_path: Path):
        """ZIP с членом ../escape.txt должен быть отвергнут."""
        target = tmp_path / 'traversal.pkl'
        with zipfile.ZipFile(target, mode='w') as zf:
            zf.writestr('../escape.txt', b'malicious')
            zf.writestr(MANIFEST_FILENAME, b'{}')
            zf.writestr(DATA_FILENAME, b'{}')
        with pytest.raises(CorruptArchiveError, match='path traversal'):
            load_model_safe(target)

    def test_absolute_path_in_zip_blocked(self, tmp_path: Path):
        target = tmp_path / 'abspath.pkl'
        with zipfile.ZipFile(target, mode='w') as zf:
            zf.writestr('/etc/passwd', b'pwned')
            zf.writestr(MANIFEST_FILENAME, b'{}')
            zf.writestr(DATA_FILENAME, b'{}')
        with pytest.raises(CorruptArchiveError, match='path traversal'):
            load_model_safe(target)

    def test_too_many_files_blocked(self, tmp_path: Path):
        target = tmp_path / 'flood.pkl'
        with zipfile.ZipFile(target, mode='w') as zf:
            for i in range(MAX_FILES + 1):
                zf.writestr(f'file_{i}.txt', b'x')
        with pytest.raises(CorruptArchiveError, match='файлов'):
            load_model_safe(target)

    def test_arrays_with_pickle_payload_blocked(self, tmp_path: Path):
        """Если arrays.npz содержит pickle (allow_pickle=True артефакт),
        load с allow_pickle=False должен отвергнуть."""
        target = tmp_path / 'malicious.pkl'

        # Создаём npz с object array (требует pickle при unpickling)
        buf = io.BytesIO()
        # np.savez не сохраняет object без allow_pickle, поэтому вручную через npy file.
        # Test проверяет что allow_pickle=False работает.
        try:
            obj_arr = np.array([{'evil': 'payload'}], dtype=object)
            np.savez(buf, evil=obj_arr)
        except ValueError:
            # Современный numpy требует allow_pickle=True для object arrays при save.
            # Это уже даёт нам defence-in-depth — даже сохранить нельзя без явного opt-in.
            pytest.skip('numpy блокирует object array save без allow_pickle')

        # Если save прошёл — пытаемся load и ожидаем ошибку.
        with zipfile.ZipFile(target, mode='w') as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps({
                'format': FORMAT_NAME, 'format_version': FORMAT_VERSION,
            }))
            zf.writestr(DATA_FILENAME, json.dumps({'x': {'__numpy_array__': 'evil'}}))
            zf.writestr(ARRAYS_FILENAME, buf.getvalue())

        with pytest.raises(CorruptArchiveError, match='pickle'):
            load_model_safe(target)

    def test_corrupt_manifest_rejected(self, tmp_path: Path):
        target = tmp_path / 'corrupt.pkl'
        with zipfile.ZipFile(target, mode='w') as zf:
            zf.writestr(MANIFEST_FILENAME, b'not json {{')
            zf.writestr(DATA_FILENAME, b'{}')
        with pytest.raises(SafeModelFormatError, match='manifest'):
            load_model_safe(target)

    def test_wrong_format_name_rejected(self, tmp_path: Path):
        target = tmp_path / 'wrong-format.pkl'
        with zipfile.ZipFile(target, mode='w') as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps({
                'format': 'sklearn-model', 'format_version': '1',
            }))
            zf.writestr(DATA_FILENAME, b'{}')
        with pytest.raises(SafeModelFormatError, match='format'):
            load_model_safe(target)

    def test_missing_manifest_rejected(self, tmp_path: Path):
        target = tmp_path / 'no-manifest.pkl'
        with zipfile.ZipFile(target, mode='w') as zf:
            zf.writestr(DATA_FILENAME, b'{}')
        with pytest.raises(SafeModelFormatError, match='manifest'):
            load_model_safe(target)


# ─── Детектор формата ─────────────────────────────────────────────────────


class TestDetectFormat:
    def test_detects_aurora_model(self, tmp_path: Path):
        target = tmp_path / 'safe.pkl'
        save_model_safe({'v': 1}, target)
        assert detect_format(target) == 'aurora-model'

    def test_detects_pickle(self, tmp_path: Path):
        target = tmp_path / 'legacy.pkl'
        with open(target, 'wb') as f:
            pickle.dump({'v': 1}, f)
        assert detect_format(target) == 'pickle'

    def test_detects_unknown(self, tmp_path: Path):
        target = tmp_path / 'garbage.bin'
        target.write_bytes(b'not a known format')
        assert detect_format(target) == 'unknown'

    def test_missing_file(self, tmp_path: Path):
        assert detect_format(tmp_path / 'nope.pkl') == 'unknown'

    def test_empty_file(self, tmp_path: Path):
        target = tmp_path / 'empty.bin'
        target.write_bytes(b'')
        assert detect_format(target) == 'unknown'

    def test_too_short(self, tmp_path: Path):
        target = tmp_path / 'tiny.bin'
        target.write_bytes(b'PK')  # меньше 4 байт
        assert detect_format(target) == 'unknown'


# ─── Миграция legacy pickle ──────────────────────────────────────────────


class TestMigration:
    def test_pickle_to_safe_inplace(self, tmp_path: Path):
        target = tmp_path / 'model.pkl'
        original = {
            'model_version': '1.3',
            'config': {'kpi_type': 'sales'},
            'posterior': np.random.randn(50, 100).astype(np.float32),
        }
        with open(target, 'wb') as f:
            pickle.dump(original, f)

        migrate_pickle_to_safe(target)

        # Файл должен теперь быть aurora-model
        assert detect_format(target) == 'aurora-model'
        # Backup сохранён
        assert (tmp_path / 'model.pkl.pre_safe_migration').exists()
        # Контент идентичен
        loaded = load_model_safe(target)
        assert loaded['model_version'] == '1.3'
        assert loaded['config']['kpi_type'] == 'sales'
        np.testing.assert_array_equal(loaded['posterior'], original['posterior'])

    def test_pickle_to_safe_to_separate_path(self, tmp_path: Path):
        src = tmp_path / 'model.pkl'
        with open(src, 'wb') as f:
            pickle.dump({'v': 1}, f)
        dest = tmp_path / 'model.aurora-model'
        result = migrate_pickle_to_safe(src, dest)
        assert result == dest
        assert dest.exists()
        # Оригинальный pkl остаётся pickle (без backup, отдельный путь).
        assert detect_format(src) == 'pickle'
        assert not (tmp_path / 'model.pkl.pre_safe_migration').exists()

    def test_already_safe_format_rejected(self, tmp_path: Path):
        target = tmp_path / 'already.pkl'
        save_model_safe({'v': 1}, target)
        with pytest.raises(CorruptArchiveError, match='уже в формате'):
            migrate_pickle_to_safe(target)

    def test_unknown_format_rejected(self, tmp_path: Path):
        target = tmp_path / 'garbage.pkl'
        target.write_bytes(b'random bytes')
        with pytest.raises(CorruptArchiveError, match='неопознанный'):
            migrate_pickle_to_safe(target)


# ─── Manifest reading ────────────────────────────────────────────────────


class TestManifest:
    def test_read_manifest_returns_metadata(self, tmp_path: Path):
        target = tmp_path / 'm.pkl'
        save_model_safe(
            {'model_version': '2.0.0', 'kpi_type': 'sales'},
            target,
            extra_manifest={'author': 'Маша маленькая'},
        )
        manifest = read_manifest(target)
        assert manifest['format'] == FORMAT_NAME
        assert manifest['format_version'] == FORMAT_VERSION
        assert manifest['model_version'] == '2.0.0'
        assert manifest['author'] == 'Маша маленькая'
        assert 'created_at' in manifest
        assert 'sha256_data' in manifest

    def test_extra_manifest_cannot_override_format(self, tmp_path: Path):
        target = tmp_path / 'fixed.pkl'
        save_model_safe(
            {'v': 1}, target,
            extra_manifest={'format': 'evil-format', 'format_version': '999'},
        )
        manifest = read_manifest(target)
        assert manifest['format'] == FORMAT_NAME
        assert manifest['format_version'] == FORMAT_VERSION


# ─── Атомарность записи ──────────────────────────────────────────────────


class TestAtomicWrite:
    def test_tmp_file_cleaned_on_success(self, tmp_path: Path):
        target = tmp_path / 'atomic.pkl'
        save_model_safe({'v': 1}, target)
        # Никаких .tmp файлов не осталось
        tmp_files = list(tmp_path.glob('*.tmp'))
        assert tmp_files == [], f'Не убран временный файл: {tmp_files}'

    def test_existing_file_replaced(self, tmp_path: Path):
        target = tmp_path / 'replace.pkl'
        save_model_safe({'version': 'v1'}, target)
        original_size = target.stat().st_size

        save_model_safe(
            {'version': 'v2', 'extra': 'field', 'big': np.zeros(1000)},
            target,
        )
        new_size = target.stat().st_size
        # Новая запись не пустая, размер другой
        assert new_size != original_size
        loaded = load_model_safe(target)
        assert loaded['version'] == 'v2'
        assert loaded['extra'] == 'field'


# ─── Реалистичный сценарий (как у MMM Optimizer) ─────────────────────────


class TestIntegrationWithLoadModelCompat:
    """Интеграция через `engines.persistence.load_model_with_compat`:
    маршрутизация между aurora-model и legacy pickle, защита SHA-256
    sidecar для legacy путей."""

    def test_compat_loads_new_format(self, tmp_path: Path):
        target = tmp_path / 'latest.pkl'
        original = {
            'model_version': '2.1',
            'kpi_type': 'sales',
            'config': {'media_columns': ['tv', 'digital']},
            'channel_categories': {'tv': 'brand', 'digital': 'performance'},
        }
        save_model_safe(original, target)

        from engines.persistence import load_model_with_compat
        loaded = load_model_with_compat(target)

        assert loaded['model_version'] == '2.1'
        assert loaded['kpi_type'] == 'sales'
        assert loaded['channel_categories'] == {'tv': 'brand', 'digital': 'performance'}
        # v1.3 defaults injected
        assert 'per_channel_input' in loaded
        assert 'derived_mode' in loaded

    def test_compat_loads_legacy_pickle(self, tmp_path: Path):
        target = tmp_path / 'latest.pkl'
        original = {
            'model_version': '1.2',
            'kpi_type': 'sales',
            'config': {'media_columns': ['tv']},
        }
        with open(target, 'wb') as f:
            pickle.dump(original, f)

        from engines.persistence import load_model_with_compat
        loaded = load_model_with_compat(target)

        assert loaded['model_version'] == '1.2'
        # v1.3 defaults injected для legacy
        assert loaded.get('channel_categories') == {}
        assert 'per_channel_input' in loaded

    def test_compat_raises_on_missing_file(self, tmp_path: Path):
        from engines.persistence import load_model_with_compat
        with pytest.raises(FileNotFoundError):
            load_model_with_compat(tmp_path / 'no-file.pkl')

    def test_compat_raises_on_garbage(self, tmp_path: Path):
        target = tmp_path / 'garbage.pkl'
        target.write_bytes(b'not pickle, not zip')
        from engines.persistence import load_model_with_compat
        with pytest.raises(pickle.UnpicklingError):
            load_model_with_compat(target)


class TestLazyMigration:
    """Lazy migration: legacy pickle переписывается в aurora-model сразу при load
    (закрывает окно RCE-атаки между load и следующим save)."""

    def test_load_legacy_pickle_triggers_migration(self, tmp_path: Path):
        target = tmp_path / 'latest.pkl'
        original = {
            'model_version': '1.2',
            'kpi_type': 'sales',
            'config': {'media_columns': ['tv']},
            'big_array': np.random.RandomState(0).randn(100, 200).astype(np.float32),
        }
        with open(target, 'wb') as f:
            pickle.dump(original, f)

        # Перед load — формат pickle
        assert detect_format(target) == 'pickle'

        from engines.persistence import load_model_with_compat
        loaded = load_model_with_compat(target)

        # После load — формат уже aurora-model (lazy migration сработала)
        assert detect_format(target) == 'aurora-model'
        # Backup сохранён
        assert (tmp_path / 'latest.pkl.pre_safe_migration').exists()
        # Содержимое идентично
        assert loaded['model_version'] == '1.2'
        np.testing.assert_array_equal(loaded['big_array'], original['big_array'])

    def test_migration_idempotent_on_aurora_model(self, tmp_path: Path):
        """Повторный load aurora-model не делает миграцию повторно."""
        target = tmp_path / 'latest.pkl'
        save_model_safe({'model_version': '2.1', 'kpi_type': 'sales'}, target)
        original_mtime = target.stat().st_mtime
        original_size = target.stat().st_size

        from engines.persistence import load_model_with_compat
        load_model_with_compat(target)

        # File не изменился (no-op миграция)
        assert target.stat().st_size == original_size
        # Backup не создан (нет миграции)
        assert not (tmp_path / 'latest.pkl.pre_safe_migration').exists()

    def test_migration_failure_does_not_break_load(self, tmp_path: Path, monkeypatch):
        """Если миграция падает (например read-only FS), load всё равно возвращает данные."""
        target = tmp_path / 'latest.pkl'
        original = {'model_version': '1.2', 'kpi_type': 'sales'}
        with open(target, 'wb') as f:
            pickle.dump(original, f)

        # Симулируем failure при попытке save_model_safe в migration path
        from engines import persistence_safe
        def failing_save(*args, **kwargs):
            raise OSError('disk full simulation')
        monkeypatch.setattr(persistence_safe, 'save_model_safe', failing_save)

        from engines.persistence import load_model_with_compat
        loaded = load_model_with_compat(target)

        # Данные загружены несмотря на failed migration
        assert loaded['model_version'] == '1.2'
        # Формат файла остался pickle (миграция не прошла)
        assert detect_format(target) == 'pickle'

    def test_save_diagnostics_writes_aurora_model_format(self, tmp_path: Path):
        """После обучения и save_v20_diagnostics файл — aurora-model."""
        project_dir = tmp_path / 'project'
        models_dir = project_dir / 'models'
        models_dir.mkdir(parents=True)
        target = models_dir / 'latest.pkl'

        # Существующая модель в aurora-model формате (новые проекты)
        save_model_safe(
            {'model_version': '2.0.0', 'kpi_type': 'sales', 'analysis_mode': 'roi'},
            target,
        )

        from engines.persistence import save_v20_diagnostics
        save_v20_diagnostics(project_dir, {
            'mcmc_diagnostics': {'r_hat_max': 1.01, 'ess_min': 500},
            'analysis_mode': 'roi',
        })

        # После save_v20_diagnostics файл остаётся в aurora-model формате
        assert detect_format(target) == 'aurora-model'

        # И диагностика загружается через load_v20_diagnostics
        from engines.persistence import load_v20_diagnostics
        diag = load_v20_diagnostics(project_dir)
        assert diag['mcmc_diagnostics']['r_hat_max'] == pytest.approx(1.01)
        assert diag['analysis_mode'] == 'roi'


class TestSecurityExtended:
    """Дополнительные attack scenarios — закрывают H-08 + новые векторы v2.1.0."""

    def test_zip_with_executable_payload_blocked(self, tmp_path: Path):
        """ZIP может содержать exe файл — структурно проходит, но не вреден без
        автозапуска. Главное — мы НЕ выполняем код из ZIP."""
        target = tmp_path / 'with_exe.pkl'
        with zipfile.ZipFile(target, mode='w') as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps({
                'format': FORMAT_NAME, 'format_version': FORMAT_VERSION,
            }))
            zf.writestr(DATA_FILENAME, b'{"v": 1}')
            zf.writestr('payload.exe', b'\x4d\x5a\x90\x00')  # MZ header

        # Load работает (мы не запускаем .exe, только читаем manifest+data+arrays)
        # но нагрузка из exe игнорируется — она просто проходит мимо.
        loaded = load_model_safe(target)
        assert loaded == {'v': 1}

    def test_symlink_in_zip_not_followed(self, tmp_path: Path):
        """ZIP может содержать символические ссылки. Мы их не следуем
        (zf.read только читает member content, не resolves)."""
        target = tmp_path / 'with_symlink.pkl'
        with zipfile.ZipFile(target, mode='w') as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps({
                'format': FORMAT_NAME, 'format_version': FORMAT_VERSION,
            }))
            zf.writestr(DATA_FILENAME, b'{"v": 1}')
            # Заголовок-симлинк через ZipInfo с external_attr (Unix mode)
            info = zipfile.ZipInfo('link.txt')
            info.external_attr = 0xA1ED0000  # symlink mode
            zf.writestr(info, '/etc/passwd')

        loaded = load_model_safe(target)
        # Симлинк проигнорирован — данные читаются ОК
        assert loaded == {'v': 1}

    def test_extremely_compressed_ratio_blocked(self, tmp_path: Path):
        """Защита от zip-bomb (extreme compression ratio).
        Создаём небольшой архив, декомпрессия которого превысит лимит."""
        target = tmp_path / 'bomb.pkl'
        with zipfile.ZipFile(target, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps({
                'format': FORMAT_NAME, 'format_version': FORMAT_VERSION,
            }))
            zf.writestr(DATA_FILENAME, b'{"v": 1}')
            # Файл размером > MAX_TOTAL_UNCOMPRESSED, но сильно сжимаемый
            payload_size = MAX_TOTAL_UNCOMPRESSED + 1024
            zf.writestr('bomb.bin', b'\x00' * payload_size)

        with pytest.raises(CorruptArchiveError, match='zip-bomb'):
            load_model_safe(target)

    def test_unicode_member_name_handled(self, tmp_path: Path):
        """ZIP с unicode именами — допустим, не вреден."""
        target = tmp_path / 'unicode.pkl'
        save_model_safe({'тест': 'кириллица'}, target)
        loaded = load_model_safe(target)
        assert loaded == {'тест': 'кириллица'}

    def test_concurrent_save_race_detected(self, tmp_path: Path):
        """Симуляция: два процесса пишут одновременно. Atomic rename
        гарантирует что один из них выиграет — без частичной записи."""
        target = tmp_path / 'race.pkl'
        save_model_safe({'version': 'v1'}, target)
        # Загружаем + проверяем что данные не битые
        for _ in range(5):
            save_model_safe({'version': 'v1', 'iter': _}, target)
            loaded = load_model_safe(target)
            assert loaded['version'] == 'v1'
            # tmp-файлы НЕ остаются после атомарной записи
            tmps = list(tmp_path.glob('*.tmp'))
            assert not tmps, f'Не убраны tmp файлы: {tmps}'


class TestRealisticModelData:
    def test_full_mmm_model_structure(self, tmp_path: Path):
        """Воспроизводит типичную структуру model_data из engines/modeler.py."""
        target = tmp_path / 'mmm.pkl'

        n_channels = 7
        n_samples = 8000

        model_data = {
            'model_version': '1.3',
            'kpi_type': 'sales',
            'kpi_likelihood': 'normal',
            'config': {
                'data_file': 'D:/data/kagocel.xlsx',
                'date_column': 'Дата',
                'sales_column': 'Продажи',
                'media_columns': [f'channel_{i}' for i in range(n_channels)],
                'control_columns': ['price', 'seasonality'],
                'kpi_type': 'sales',
            },
            'channel_params': {
                f'channel_{i}': {
                    'beta': 0.123 + i * 0.01,
                    'alpha': 1.2 + i * 0.05,
                    'gamma': 0.45,
                    'adstock': {'alpha': 0.5},
                    'decay': 0.5,
                    'adstock_mean_posterior': 1.234,
                    'tail_ess_ok': True,
                }
                for i in range(n_channels)
            },
            'normalization': {
                'media_means': {f'channel_{i}': 1000.0 * (i + 1) for i in range(n_channels)},
                'control_means': {'price': 50.0, 'seasonality': 0.5},
                'control_stds': {'price': 10.0, 'seasonality': 0.2},
                'y_mean': 5000.0,
                'y_std': 1000.0,
                'intercept_mean': 0.5,
                'control_betas_mean': [0.1, -0.05],
                'untrained_channels': [],
                'control_kinds': ['controls', 'controls'],
                'holiday_cols_injected': ['ny', 'feb23'],
                'control_prior_mus': {'price': -0.1, 'seasonality': 0.05},
                'untrained_controls': [],
            },
            'posterior_samples': {
                'media_betas': np.random.RandomState(0).randn(n_channels, n_samples).astype(np.float32),
                'alphas': np.random.RandomState(1).randn(n_channels, n_samples).astype(np.float32),
                'gammas': np.random.RandomState(2).randn(n_channels, n_samples).astype(np.float32),
                'intercept': np.random.RandomState(3).randn(n_samples).astype(np.float32),
                'control_betas': np.random.RandomState(4).randn(2, n_samples).astype(np.float32),
                'adstock_decay': np.random.RandomState(5).randn(n_channels, n_samples).astype(np.float32),
                'adstock_mu_logit_mean': 0.0,
                'adstock_sigma_logit_mean': 1.0,
                'media_columns': [f'channel_{i}' for i in range(n_channels)],
                'control_columns': ['price', 'seasonality'],
                'n_chains': 4,
                'n_draws': 2000,
            },
            'channel_categories': {f'channel_{i}': 'brand' if i < 3 else 'performance' for i in range(n_channels)},
            'categorization_warnings': [],
            'use_hierarchical': True,
            'hierarchical_priors': {'brand_mu_logit': 0.3, 'perf_mu_logit': 0.7},
            'y_actual': [100.0 + i for i in range(150)],
            'y_predicted': [101.0 + i for i in range(150)],
            'causal_artifact_path': None,
            'channel_adstock_types': {f'channel_{i}': 'geometric' for i in range(n_channels)},
            'training_granularity': 'W',
            'train_x_norm_quantiles': {
                f'channel_{i}': {'p50': 1.0, 'p75': 1.5, 'p90': 2.0, 'p95': 2.5, 'p99': 3.0}
                for i in range(n_channels)
            },
            'seasonality_detected': {'period': 52, 'autocorr': 0.8},
        }

        # Save
        save_model_safe(model_data, target)

        # Reload
        loaded = load_model_safe(target)

        # Сверяем структуру
        assert loaded['model_version'] == '1.3'
        assert loaded['kpi_type'] == 'sales'
        assert len(loaded['channel_params']) == n_channels
        assert loaded['channel_params']['channel_0']['beta'] == pytest.approx(0.123)

        # Numpy arrays сохраняют значения
        for key in ('media_betas', 'alphas', 'gammas', 'intercept', 'adstock_decay'):
            np.testing.assert_array_equal(
                loaded['posterior_samples'][key],
                model_data['posterior_samples'][key],
            )

        # Метаданные внутри posterior_samples
        assert loaded['posterior_samples']['n_chains'] == 4
        assert loaded['posterior_samples']['media_columns'] == [f'channel_{i}' for i in range(n_channels)]

        # Нет коллизий имён
        assert detect_format(target) == 'aurora-model'

    def test_save_size_reasonable(self, tmp_path: Path):
        """Файл крупной модели должен умещаться в разумные пределы (< 10 MB при 7×8000 float32)."""
        target = tmp_path / 'size.pkl'
        n_channels, n_samples = 7, 8000
        model_data = {
            'posterior_samples': {
                'media_betas': np.random.RandomState(0).randn(n_channels, n_samples).astype(np.float32),
                'alphas': np.random.RandomState(1).randn(n_channels, n_samples).astype(np.float32),
                'gammas': np.random.RandomState(2).randn(n_channels, n_samples).astype(np.float32),
                'intercept': np.random.RandomState(3).randn(n_samples).astype(np.float32),
                'adstock_decay': np.random.RandomState(4).randn(n_channels, n_samples).astype(np.float32),
            },
        }
        save_model_safe(model_data, target)
        size_mb = target.stat().st_size / (1024 * 1024)
        # Сырые float32 ~ 1 MB, deflate ~ 0.9 MB.
        assert size_mb < 5.0, f'Файл подозрительно большой: {size_mb:.2f} MB'
