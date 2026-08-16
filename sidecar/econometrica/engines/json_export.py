"""
Aurora Econometrica – выгрузка параметров модели в JSON (схема 3.0).

Назначение: документ, по которому посторонний аналитик восстанавливает
спецификацию обученной модели – каналы с коэффициентами, перенос и насыщение,
нормировку, контрольные переменные, приоры, гранулярность, длину истории, тип
KPI. Документ отдаётся клиенту по явному действию «выгрузить параметры модели»,
поэтому он заверяемый: каждое поле либо прочитано из модели, либо посчитано
здесь и помечено расчётным, либо честно объявлено отсутствующим.

🔴 Правило модуля: НИКАКОЙ ПОДСТАНОВКИ УМОЛЧАНИЙ.
    Нет поля в модели → `null` + запись в `absent_fields` с пояснением, где эта
    величина живёт. Значение по умолчанию в заверяемом поле – тот класс дефекта,
    который в продукте выкорчёвывали дважды (Critical F-01, High Ф-01).
    Отдельно: тип переноса (`adstock_type`) НИКОГДА не подставляется. У моделей,
    обученных до 06.07.2026, там записана настройка `'auto'` – это «что просили»,
    а не «что применилось»; выводить фактический тип задним числом запрещено.

История схемы:
    3.1 (2026-08-16) – закрыты пробелы, найденные приёмкой опытом: посторонний
        аналитик, получив только этот документ, не смог восстановить модель.
        Добавлены: полная спецификация приоров с семействами распределений
        (порождается разбором `engines/modeler.py`, а не переписана руками),
        календарные определения праздничных окон и правило режима, правило ряда
        Фурье с проверкой по записанным статистикам, самоописание алгоритма
        отпечатка `aurora-frame-v1`, полные настройки сэмплера, диапазон дат
        обучающего ряда и единицы величин. Тогда же починена потеря отпечатка
        данных: вложенные словари паспорта воспроизводимости отбрасывались, и
        поле `data_fingerprint` выходило пустым объектом.
    3.0 (2026-08-16) – переписано чтение под настоящую схему модели. До этого
        модуль читал имена, которых в продукте никогда не было
        (`beta_mean`/`adstock_decay`/`adstock_type`/`hill_alpha`/`hill_gamma`/
        `roi`), был мёртвым (вызывающих ноль, тестов ноль) и отдавал пустышку:
        все коэффициенты каналов `null`, тип переноса подставлен `'geometric'`.
    2.0.0 – исходная версия по ADR-019 §6 (схема существовала только в докстринге).

Источник схемы записи: `engines/modeler.py` – `channel_params` (~строка 1639)
и сборка `model_data` (~строки 1685–1793). Проверено зондом на живых моделях
разных дат обучения (24.06.2026 с `'auto'` и 10.07.2026 с конкретными типами).

Использование:
    from engines.json_export import export_model_params_json
    from engines.persistence import load_model_with_compat

    model_data = load_model_with_compat(project_dir / 'models' / 'latest.pkl')
    diagnostics = json.loads((project_dir / 'results' / 'model-diagnostics.json').read_text('utf-8'))
    json_str = export_model_params_json(model_data, diagnostics=diagnostics)

`diagnostics` – необязательный: MCMC-диагностика, ретро-проверка и апостериорная
проверка соответствия в самой модели НЕ хранятся (в загруженной модели эти ключи
всегда `None`, их кладёт загрузчик как заглушки). Их единый источник для чтения –
`results/model-diagnostics.json` (см. `modeler.py`, комментарий у записи файла).
Не передали – блок диагностики честно объявлен отсутствующим.
"""
from __future__ import annotations

import ast
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

СХЕМА_ВЕРСИЯ = '3.1'

# Происхождение значения. Коды латиницей – их читает машина; расшифровка
# по-русски едет в самом документе (`schema.origins`), чтобы читатель-человек
# не гадал, что стоит за полем.
ЗАПИСАНО = 'recorded'          # прочитано из модели как есть
РАССЧИТАНО = 'computed'        # посчитано здесь, при выгрузке
НЕ_ЗАПИСАНО = 'not_recorded'   # в модели этого нет – значение null
СПРАВОЧНО = 'reference'        # взято из кода продукта на момент выгрузки, не из модели

_РАСШИФРОВКА_ИСТОЧНИКОВ = {
    ЗАПИСАНО: 'значение прочитано из файла модели как есть',
    РАССЧИТАНО: 'значение посчитано при выгрузке (из апостериорных выборок или других полей модели)',
    НЕ_ЗАПИСАНО: 'в модели такого поля нет – значение пустое; пояснение см. в absent_fields',
    СПРАВОЧНО: 'значение взято не из модели, а из кода продукта на момент выгрузки '
               '(описание метода, параметры по умолчанию) – при изменении кода может разойтись '
               'с тем, что применялось при обучении',
}

# Типы переноса, которые расчётные пути продукта считают фактическими.
# `'auto'` сюда НЕ входит намеренно: это настройка «выбери сам», а не факт.
_ФАКТИЧЕСКИЕ_ТИПЫ_ПЕРЕНОСА = ('geometric', 'weibull')


# ─────────────────────────────────────────────────────────────────────
# Мелкие помощники чтения
# ─────────────────────────────────────────────────────────────────────

def _как_число(значение: Any) -> Optional[float]:
    """float или None. Логические значения, NaN и бесконечности → None.

    NaN/inf отсекаются намеренно: голый json.dump пишет литерал `NaN`, который
    нарушает RFC 8259 и не парсится сторонними читателями (та же грабля, что
    чинили в `utils/safe_io.sanitize_nonfinite`).
    """
    if значение is None or isinstance(значение, bool):
        return None
    try:
        число = float(значение)
    except (TypeError, ValueError):
        return None
    if число != число or число in (float('inf'), float('-inf')):
        return None
    return число


def _как_целое(значение: Any) -> Optional[int]:
    """Целое или None. Счётные величины не должны выходить дробными."""
    число = _как_число(значение)
    if число is None:
        return None
    return int(round(число))


def _как_строку(значение: Any) -> Optional[str]:
    """Непустая строка или None. Пустая строка = отсутствие, не значение."""
    if значение is None:
        return None
    текст = str(значение).strip()
    return текст or None


def _как_список_строк(значение: Any) -> List[str]:
    if not значение:
        return []
    try:
        return [str(v) for v in значение]
    except TypeError:
        return []


def _числовой_словарь(значение: Any) -> Dict[str, Optional[float]]:
    """{ключ: число} с отбрасыванием непреобразуемого в None (не в 0)."""
    if not isinstance(значение, dict):
        return {}
    return {str(k): _как_число(v) for k, v in значение.items()}


def _статистика_по_выборкам(выборки: Any) -> Optional[Dict[str, float]]:
    """Среднее, разброс и правдоподобный диапазон 90% по апостериорным выборкам.

    Возвращает None, если выборок нет или пригодных значений меньше двух –
    пустой разброс честнее выдуманного.
    """
    if выборки is None:
        return None
    try:
        import numpy as np
    except ImportError:  # numpy обязателен для движка, но выгрузка не должна падать
        logger.warning('numpy недоступен – разброс коэффициентов не рассчитан')
        return None
    try:
        массив = np.asarray(выборки, dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    массив = массив[np.isfinite(массив)]
    if массив.size < 2:
        return None
    нижняя, верхняя = (float(v) for v in np.percentile(массив, [5, 95]))
    return {
        'mean': float(массив.mean()),
        'std': float(массив.std()),
        'range_90': [нижняя, верхняя],
        'n_samples': int(массив.size),
    }


def _значения_по_умолчанию(функция) -> Dict[str, Any]:
    """Значения по умолчанию из сигнатуры функции продукта.

    Читаем из кода, а не переписываем числа руками: переписанная копия молча
    разъедется с продуктом при первой же правке.
    """
    try:
        import inspect
        сигнатура = inspect.signature(функция)
    except (TypeError, ValueError):
        return {}
    результат: Dict[str, Any] = {}
    for имя, параметр in сигнатура.parameters.items():
        if параметр.default is inspect.Parameter.empty:
            continue
        значение = _как_число(параметр.default)
        if значение is not None:
            результат[имя] = значение
    return результат


# ─────────────────────────────────────────────────────────────────────
# Чтение спецификации прямо из кода сборки модели
# ─────────────────────────────────────────────────────────────────────
#
# Почему разбор исходника, а не таблица чисел в этом модуле: рукописная копия
# спецификации молча расходится с расчётом. Живой пример в этом же продукте –
# `utils/model_spec.py` с заголовком «keep priors here in sync with modeler.py»:
# там уже нет ни приоров отката, ни иерархической ветви, а нормировка описана
# как деление на максимум, хотя код делит на среднее. Такую копию нельзя класть
# в заверяемый документ. Разбор исходника даёт семейство распределения и
# написанные в коде аргументы буквально: правка модели меняет и документ.
#
# Статус у всего, что добыто отсюда, – СПРАВОЧНО: это код на момент выгрузки,
# а не запись обучения.

_ОГОВОРКА_КОДА = (
    'Значения прочитаны из кода продукта на момент выгрузки, а не из файла модели: '
    'спецификация приоров при обучении не сохраняется. Совпадение с версией программы, '
    'которой обучена эта модель, не гарантировано.'
)

# Вызовы pm.*, которые не заводят случайную величину.
_НЕ_СЛУЧАЙНЫЕ_ВЫЗОВЫ = ('Deterministic', 'Data', 'MutableData', 'ConstantData', 'Potential')

# Куда попадает параметр модели в этом документе. Карта рукописная и намеренно
# полная: тест `test_json_export_priors.py` требует, чтобы у каждой найденной в
# коде величины была строка здесь. Переименовали переменную в модели – тест
# краснеет, и карта обновляется вместе с ней, а не остаётся врать.
_ПАРАМЕТР_В_ДОКУМЕНТЕ = {
    'intercept': 'normalization.intercept_mean – свободный член',
    'media_betas': 'channels[*].beta – коэффициент канала',
    'media_betas_z': 'channels[*].beta – вспомогательная величина: beta = сигма группы × z',
    'brand_sigma': 'сигма коэффициентов каналов категории «бренд» (иерархическая ветвь)',
    'perf_sigma': 'сигма коэффициентов каналов категории «отклик» (иерархическая ветвь)',
    'mixed_sigma': 'сигма коэффициентов каналов категории «смешанный» (иерархическая ветвь)',
    'horseshoe_tau': 'общая сжимающая величина разреженного приора (ветвь «подкова»)',
    'horseshoe_lambda': 'сжимающая величина канала (ветвь «подкова»)',
    'control_betas': 'controls[*].beta и signed_factors[*].beta – коэффициенты контролей',
    'alphas': 'channels[*].hill_alpha – крутизна насыщения',
    'gammas': 'channels[*].hill_gamma – точка половинного насыщения',
    'adstock_sigma_logit': 'sampling.decay_hyper_sigma_logit_posterior_mean – разброс отката в логит-шкале',
    'adstock_mu_logit': 'sampling.decay_hyper_mu_logit_posterior_mean – центр отката в логит-шкале',
    'adstock_z': 'channels[*].adstock_decay – вспомогательная величина под сигмоидой',
    'adstock_decay': 'channels[*].adstock_decay – откат канала, сигмоида от логит-шкалы',
    'brand_mu_logit': 'центр отката категории «бренд» в логит-шкале (иерархическая ветвь)',
    'perf_mu_logit': 'центр отката категории «отклик» в логит-шкале (иерархическая ветвь)',
    'mixed_mu_logit': 'центр отката категории «смешанный» в логит-шкале (иерархическая ветвь)',
    'sigma': 'шум наблюдения; апостериорная оценка в модели не записана – в документе её нет',
    'obs': 'правдоподобие наблюдений KPI',
}

# Выражения кода, значение которых есть в самом документе. Без этой подсказки
# читатель видит «mu=_control_mu_array» и не знает, что числа у него уже есть.
_ГДЕ_ИСКАТЬ_ВЫРАЖЕНИЕ = {
    '_control_mu_array': (
        'priors.control_prior_means этого документа – приорное среднее по каждому контролю, '
        'записано в модели'
    ),
}

_ФАЙЛ_СБОРКИ_МОДЕЛИ = 'modeler.py'


@lru_cache(maxsize=1)
def _дерево_сборки_модели():
    """Разобранный исходник `engines/modeler.py` либо None.

    Кешируется: за одну выгрузку дерево нужно и приорам, и настройкам сэмплера.
    Ошибку чтения или разбора наружу не выпускаем – документ выйдет с честным
    отсутствием блока, а не упадёт.
    """
    путь = Path(__file__).with_name(_ФАЙЛ_СБОРКИ_МОДЕЛИ)
    try:
        return ast.parse(путь.read_text(encoding='utf-8')), путь.name
    except (OSError, SyntaxError, ValueError) as ошибка:
        logger.warning('Исходник сборки модели не разобран: %s', ошибка)
        return None, путь.name


def _вызовы_с_условиями(узел, условия: List[Tuple[str, bool]], собранное: List) -> None:
    """Обойти дерево, запоминая, под какими ветвлениями лежит каждый вызов.

    Ветвь – это и есть ответ на вопрос «какой приор применялся»: у модели три
    взаимоисключающих пути коэффициента канала, и без условия перечисление
    приоров вводит читателя в заблуждение.
    """
    # Ветвление разбирается у САМОГО узла, а не у его потомков: `elif` лежит в
    # дереве вложенным ветвлением, и разбор «по потомкам» терял бы его условие –
    # приор иерархической ветви выглядел бы применённым в неиерархической модели.
    if isinstance(узел, ast.If):
        текст = ast.unparse(узел.test)
        for ветка, истина in ((узел.body, True), (узел.orelse, False)):
            for следующий in ветка:
                _вызовы_с_условиями(следующий, условия + [(текст, истина)], собранное)
        return
    if isinstance(узел, ast.Call):
        собранное.append((узел, list(условия)))
    for потомок in ast.iter_child_nodes(узел):
        _вызовы_с_условиями(потомок, условия, собранное)


def _псевдонимы_реестра(дерево) -> Dict[str, Tuple[str, Optional[int]]]:
    """Локальные имена, за которыми стоит значение реестра KPI.

    В коде приоры отката распакованы в локальные имена
    (`_p_mu, _p_sg = kpi_config.perf_mu_logit_prior`), и без этой карты в
    документ уехало бы «Normal(mu=_sp_mu)» вместо числа.
    """
    карта: Dict[str, Tuple[str, Optional[int]]] = {}
    for узел in ast.walk(дерево):
        if not isinstance(узел, ast.Assign) or len(узел.targets) != 1:
            continue
        значение = узел.value
        if not (isinstance(значение, ast.Attribute)
                and isinstance(значение.value, ast.Name)
                and значение.value.id == 'kpi_config'):
            continue
        цель = узел.targets[0]
        if isinstance(цель, ast.Tuple):
            for позиция, элемент in enumerate(цель.elts):
                if isinstance(элемент, ast.Name):
                    карта[элемент.id] = (значение.attr, позиция)
        elif isinstance(цель, ast.Name):
            карта[цель.id] = (значение.attr, None)
    return карта


def _значение_из_кода(узел, псевдонимы, настройка_kpi) -> Tuple[Optional[Any], Optional[str]]:
    """Числовое значение выражения приора, если его можно назвать честно.

    Возвращает (значение, откуда). Неразрешимое выражение (произведение
    случайных величин в разреженном приоре, вызов max) → (None, None): в
    документе останется текст выражения, а не выдуманное число.
    """
    if isinstance(узел, ast.Constant) and isinstance(узел.value, (int, float)) and not isinstance(узел.value, bool):
        return float(узел.value), 'литерал кода'
    if isinstance(узел, ast.UnaryOp) and isinstance(узел.op, ast.USub):
        значение, откуда = _значение_из_кода(узел.operand, псевдонимы, настройка_kpi)
        return (-значение if значение is not None else None), откуда
    if настройка_kpi is None:
        return None, None
    if (isinstance(узел, ast.Attribute) and isinstance(узел.value, ast.Name)
            and узел.value.id == 'kpi_config'):
        значение = getattr(настройка_kpi, узел.attr, None)
        if isinstance(значение, (list, tuple)):
            return [_как_число(v) for v in значение], 'реестр KPI'
        return _как_число(значение), 'реестр KPI'
    if isinstance(узел, ast.Name) and узел.id in псевдонимы:
        поле, позиция = псевдонимы[узел.id]
        значение = getattr(настройка_kpi, поле, None)
        if позиция is not None and isinstance(значение, (list, tuple)) and позиция < len(значение):
            return _как_число(значение[позиция]), 'реестр KPI'
        return _как_число(значение), 'реестр KPI'
    return None, None


class _Неизвестно:
    """Метка «значение не определено» – отличается и от False, и от None."""

    def __repr__(self) -> str:  # pragma: no cover – только для отладки
        return '<неизвестно>'


_НЕИЗВЕСТНО = _Неизвестно()


def _проверить_условие(текст: str, контекст: Dict[str, Any]) -> Optional[bool]:
    """Выполняется ли условие ветвления при обстоятельствах этой модели.

    Разбор узкий и без `eval`: имена флагов, длина списка столбцов, сравнение,
    отрицание, «и»/«или». Всё, чего разбор не знает, даёт None – «неизвестно»,
    и приор помечается неопределённым по применимости, а не применённым.
    """
    try:
        дерево = ast.parse(текст, mode='eval').body
    except SyntaxError:
        return None

    def значение(узел):
        if isinstance(узел, ast.Constant):
            return узел.value
        if isinstance(узел, ast.Name):
            return контекст.get(узел.id, _НЕИЗВЕСТНО)
        if (isinstance(узел, ast.Call) and isinstance(узел.func, ast.Name)
                and узел.func.id == 'len' and len(узел.args) == 1):
            внутри = значение(узел.args[0])
            if внутри is _НЕИЗВЕСТНО or внутри is None:
                return _НЕИЗВЕСТНО
            try:
                return len(внутри)
            except TypeError:
                return _НЕИЗВЕСТНО
        if isinstance(узел, ast.UnaryOp) and isinstance(узел.op, ast.Not):
            внутри = значение(узел.operand)
            return _НЕИЗВЕСТНО if внутри is _НЕИЗВЕСТНО else (not внутри)
        if isinstance(узел, ast.BoolOp):
            части = [значение(v) for v in узел.values]
            if any(ч is _НЕИЗВЕСТНО for ч in части):
                return _НЕИЗВЕСТНО
            return all(части) if isinstance(узел.op, ast.And) else any(части)
        if isinstance(узел, ast.Compare) and len(узел.ops) == 1:
            левое, правое = значение(узел.left), значение(узел.comparators[0])
            if левое is _НЕИЗВЕСТНО or правое is _НЕИЗВЕСТНО:
                return _НЕИЗВЕСТНО
            операция = узел.ops[0]
            try:
                if isinstance(операция, ast.Gt):
                    return левое > правое
                if isinstance(операция, ast.GtE):
                    return левое >= правое
                if isinstance(операция, ast.Lt):
                    return левое < правое
                if isinstance(операция, ast.LtE):
                    return левое <= правое
                if isinstance(операция, ast.Eq):
                    return левое == правое
                if isinstance(операция, ast.NotEq):
                    return левое != правое
            except TypeError:
                return _НЕИЗВЕСТНО
        return _НЕИЗВЕСТНО

    итог = значение(дерево)
    if итог is _НЕИЗВЕСТНО:
        return None
    return bool(итог)


def _применимость(условия: List[Tuple[str, bool]], контекст: Dict[str, Any]) -> Tuple[Optional[bool], str]:
    """Применялась ли ветвь к этой модели + человеческая запись условия."""
    части: List[str] = []
    итог: Optional[bool] = True
    for текст, истина in условия:
        части.append(текст if истина else f'НЕ ({текст})')
        проверка = _проверить_условие(текст, контекст)
        if проверка is None:
            итог = None
        elif итог is not None:
            итог = итог and (проверка == истина)
    return итог, ' и '.join(части) if части else 'без условий'


def _флаги_модели(модель, конфиг) -> Dict[str, Any]:
    """Обстоятельства обучения, по которым выбиралась ветвь приоров."""
    иерархия = модель.get('use_hierarchical')
    контекст: Dict[str, Any] = {
        'use_hierarchical': bool(иерархия) if isinstance(иерархия, bool) else _НЕИЗВЕСТНО,
        'control_cols': _как_список_строк(конфиг.get('control_columns')),
        'media_cols': _как_список_строк(конфиг.get('media_columns')),
    }
    подкова = конфиг.get('use_horseshoe')
    if isinstance(подкова, bool):
        контекст['use_horseshoe'] = подкова
        контекст['_use_horseshoe_origin'] = ЗАПИСАНО
    else:
        умолчание = _умолчание_ключа_конфига('use_horseshoe')
        if isinstance(умолчание, bool):
            контекст['use_horseshoe'] = умолчание
            контекст['_use_horseshoe_origin'] = РАССЧИТАНО
        else:
            контекст['use_horseshoe'] = _НЕИЗВЕСТНО
            контекст['_use_horseshoe_origin'] = НЕ_ЗАПИСАНО
    return контекст


def _умолчание_ключа_конфига(ключ: str) -> Optional[Any]:
    """Как код обучения читает отсутствующий ключ конфигурации.

    Нужно ровно для одного вопроса: разреженный приор («подкова») включается
    ключом, которого у моделей ранних версий в конфигурации нет. Значение
    берётся не из головы, а из самого вызова `config.get(<ключ>, <умолчание>)`
    в коде обучения – и в документе помечается расчётным с указанием, откуда
    оно взялось.
    """
    дерево, _ = _дерево_сборки_модели()
    if дерево is None:
        return None
    for узел in ast.walk(дерево):
        if not isinstance(узел, ast.Call):
            continue
        функция = узел.func
        if not (isinstance(функция, ast.Attribute) and функция.attr == 'get'
                and isinstance(функция.value, ast.Name) and функция.value.id == 'config'):
            continue
        if not узел.args or not isinstance(узел.args[0], ast.Constant) or узел.args[0].value != ключ:
            continue
        if len(узел.args) >= 2 and isinstance(узел.args[1], ast.Constant):
            return узел.args[1].value
    return None


def _приоры_из_кода(модель, конфиг, настройка_kpi) -> Optional[Dict[str, Any]]:
    """Семейства и параметры всех приоров – разбором кода сборки модели.

    Возвращает None, если исходник недоступен: документ тогда честно скажет,
    что спецификация не прочитана, вместо того чтобы выдать неполный список.
    """
    дерево, имя_файла = _дерево_сборки_модели()
    if дерево is None:
        return None

    псевдонимы = _псевдонимы_реестра(дерево)
    контекст = _флаги_модели(модель, конфиг)

    собранное: List = []
    _вызовы_с_условиями(дерево, [], собранное)

    приоры: List[Dict[str, Any]] = []
    правдоподобия: List[Dict[str, Any]] = []
    преобразования: List[Dict[str, Any]] = []

    for вызов, условия in собранное:
        функция = вызов.func
        if not (isinstance(функция, ast.Attribute) and isinstance(функция.value, ast.Name)
                and функция.value.id == 'pm'):
            continue
        if not вызов.args or not isinstance(вызов.args[0], ast.Constant):
            continue
        имя = вызов.args[0].value
        if not isinstance(имя, str):
            continue
        применимо, запись_условия = _применимость(условия, контекст)

        if функция.attr == 'Deterministic':
            выражение = ast.unparse(вызов.args[1]) if len(вызов.args) > 1 else None
            преобразования.append({
                'variable': имя,
                'expression': выражение,
                'condition': запись_условия,
                'applies_to_this_model': применимо,
                'document_field': _ПАРАМЕТР_В_ДОКУМЕНТЕ.get(имя),
                'source_line': вызов.lineno,
            })
            continue
        if функция.attr in _НЕ_СЛУЧАЙНЫЕ_ВЫЗОВЫ:
            continue

        параметры: Dict[str, Any] = {}
        форма = None
        наблюдения = None
        for именованный in вызов.keywords:
            текст = ast.unparse(именованный.value)
            if именованный.arg == 'shape':
                форма = текст
                continue
            if именованный.arg == 'observed':
                наблюдения = текст
                continue
            значение, откуда = _значение_из_кода(именованный.value, псевдонимы, настройка_kpi)
            поле = {
                'expression': текст,
                'value': значение,
                'value_source': откуда,
            }
            если_искать = _ГДЕ_ИСКАТЬ_ВЫРАЖЕНИЕ.get(текст)
            if значение is None and если_искать:
                поле['value_where_to_find'] = если_искать
            параметры[именованный.arg] = поле

        запись = {
            'variable': имя,
            'family': функция.attr,
            'parameters': параметры,
            'notation': _запись_распределения(функция.attr, параметры),
            'shape_expression': форма,
            'condition': запись_условия,
            'applies_to_this_model': применимо,
            'document_field': _ПАРАМЕТР_В_ДОКУМЕНТЕ.get(имя),
            'source_line': вызов.lineno,
        }
        if наблюдения is not None:
            запись['observed'] = наблюдения
            правдоподобия.append(запись)
        else:
            приоры.append(запись)

    if not приоры:
        return None

    блок: Dict[str, Any] = {
        'origin': СПРАВОЧНО,
        'source': f'engines/{имя_файла} – сборка модели PyMC (разбор исходника при выгрузке)',
        'note': _ОГОВОРКА_КОДА,
        'how_read': (
            'Семейство распределения и его аргументы прочитаны из кода разбором синтаксического '
            'дерева, а не переписаны в этот модуль – рукописная копия расходится с расчётом при '
            'первой же правке модели. Числа, пришедшие из реестра KPI, помечены в value_source.'
        ),
        'branch_flags': {
            'use_hierarchical': (
                контекст['use_hierarchical'] if isinstance(контекст['use_hierarchical'], bool) else None
            ),
            'use_hierarchical_origin': (
                ЗАПИСАНО if isinstance(контекст['use_hierarchical'], bool) else НЕ_ЗАПИСАНО
            ),
            'use_horseshoe': (
                контекст['use_horseshoe'] if isinstance(контекст['use_horseshoe'], bool) else None
            ),
            'use_horseshoe_origin': контекст['_use_horseshoe_origin'],
            'use_horseshoe_note': (
                'ключа use_horseshoe в конфигурации модели нет; значение взято из того же вызова '
                'config.get, которым его читает код обучения'
                if контекст['_use_horseshoe_origin'] == РАССЧИТАНО else
                'значение прочитано из конфигурации модели'
                if контекст['_use_horseshoe_origin'] == ЗАПИСАНО else
                'значение не определено – применимость ветвей, зависящих от него, неизвестна'
            ),
        },
        'condition_note': (
            'condition – ветвление кода, при котором приор применяется; '
            'applies_to_this_model – выполнялось ли оно при обучении ЭТОЙ модели '
            '(вычислено по записанным флагам). null означает «определить нельзя».'
        ),
        'priors': приоры,
        'deterministic_transforms': преобразования,
        'likelihood': правдоподобия,
    }

    if контекст['use_hierarchical'] is False:
        блок['category_note'] = (
            'Иерархия по группам каналов при обучении была выключена: приоры, различающиеся по '
            'категории канала (бренд / отклик / смешанный), не применялись – см. condition у '
            'каждого приора. Пустое поле channels[*].category на спецификацию приоров этой '
            'модели не влияет.'
        )
    return блок


def _запись_распределения(семейство: str, параметры: Dict[str, Any]) -> str:
    """«HalfNormal(sigma=0.3)» – короткая запись для чтения человеком."""
    части = []
    for имя, поле in параметры.items():
        значение = поле.get('value')
        части.append(f'{имя}={значение if значение is not None else поле.get("expression")}')
    return f'{семейство}({", ".join(части)})'


def _настройки_сэмплера_из_кода(модель) -> Optional[Dict[str, Any]]:
    """Аргументы вызовов сэмплера – тем же разбором исходника.

    Отдельный смысл блока – честно назвать то, чего в вызове НЕТ. Зерно и
    полный список версий создают впечатление побитового повторения; без
    целевой доли принятия, предела глубины дерева и способа начальной точки
    это впечатление ложное, и умалчивать о них нельзя.
    """
    дерево, имя_файла = _дерево_сборки_модели()
    if дерево is None:
        return None

    try:
        from utils.seeding import TIER_NUMPYRO, TIER_PYTENSOR, TIER_PYTENSOR_NO_CALLBACK
    except ImportError:  # pragma: no cover – модуль есть везде, где есть движок
        TIER_NUMPYRO = TIER_PYTENSOR = TIER_PYTENSOR_NO_CALLBACK = None

    паспорт = модель.get('reproducibility') if isinstance(модель.get('reproducibility'), dict) else {}
    ярус_модели = _как_строку(паспорт.get('sampler_tier'))

    вызовы: List[Dict[str, Any]] = []
    for узел in ast.walk(дерево):
        if not isinstance(узел, ast.Call):
            continue
        функция = узел.func
        if not (isinstance(функция, ast.Attribute) and функция.attr == 'sample'
                and isinstance(функция.value, ast.Name) and функция.value.id == 'pm'):
            continue
        аргументы = {именованный.arg: ast.unparse(именованный.value) for именованный in узел.keywords}
        if 'nuts_sampler' in аргументы:
            ярус = TIER_NUMPYRO
        elif 'callback' in аргументы:
            ярус = TIER_PYTENSOR
        else:
            ярус = TIER_PYTENSOR_NO_CALLBACK
        вызовы.append({
            'sampler_tier': ярус,
            'arguments': аргументы,
            'applies_to_this_model': (ярус == ярус_модели) if ярус_модели else None,
            'source_line': узел.lineno,
        })

    if not вызовы:
        return None

    отслеживаемые = ('target_accept', 'max_treedepth', 'init', 'initvals', 'step', 'jitter')
    for вызов in вызовы:
        вызов['not_passed'] = [имя for имя in отслеживаемые if имя not in вызов['arguments']]

    применённый = next((в for в in вызовы if в['applies_to_this_model']), None)
    блок: Dict[str, Any] = {
        'origin': СПРАВОЧНО,
        'source': f'engines/{имя_файла} – вызовы pm.sample (разбор исходника при выгрузке)',
        'note': _ОГОВОРКА_КОДА,
        'calls': вызовы,
        'not_passed_note': (
            'not_passed – параметры, которые код обучения сэмплеру НЕ передаёт: действует '
            'значение по умолчанию той версии библиотеки, что указана в разделе воспроизводимости. '
            'Это и есть граница обещания повторяемости: одно зерно даёт одинаковые числа на той же '
            'среде, но не гарантирует побитового совпадения на другой.'
        ),
        'applied_tier': ярус_модели,
        'applied_tier_origin': ЗАПИСАНО if ярус_модели else НЕ_ЗАПИСАНО,
    }
    if применённый is not None:
        цель = применённый['arguments'].get('target_accept')
        блок['target_accept_in_code'] = _как_число(цель) if цель is not None else None
    return блок


# ─────────────────────────────────────────────────────────────────────
# Исходная таблица: читаем только с доказательством тождественности
# ─────────────────────────────────────────────────────────────────────
#
# Часть спецификации восстанавливается лишь из обучающего ряда дат: календарные
# границы праздничных окон и диапазон дат истории. В модели дат нет. Брать их
# из файла данных «просто так» нельзя – файл могли заменить, и документ
# заверил бы чужой ряд. Поэтому файл читается, его отпечаток пересчитывается
# нашим же алгоритмом и сверяется с записанным при обучении: совпал – читаем
# как обучающую таблицу, не совпал или файла нет – честное отсутствие.

_ДОПУСК_СВЕРКИ = 1e-9


def _таблица_исходных_данных(модель, конфиг) -> Dict[str, Any]:
    """Обучающая таблица, если её тождественность доказана отпечатком."""
    итог: Dict[str, Any] = {'status': 'unavailable', 'reason': None, 'frame': None}

    паспорт = модель.get('reproducibility') if isinstance(модель.get('reproducibility'), dict) else {}
    отпечаток = паспорт.get('data_fingerprint') if isinstance(паспорт.get('data_fingerprint'), dict) else {}
    содержимое = отпечаток.get('content') if isinstance(отпечаток.get('content'), dict) else {}
    записанный = _как_строку(содержимое.get('content_sha256'))
    if записанный is None:
        итог['reason'] = 'отпечаток обучающей таблицы в модели не записан – сверять файл не с чем'
        return итог

    путь = _как_строку(конфиг.get('data_file'))
    if путь is None:
        итог['reason'] = 'путь к файлу исходных данных в конфигурации модели не записан'
        return итог
    файл = Path(путь)
    if not файл.exists():
        итог['reason'] = 'файл исходных данных недоступен на этой машине'
        return итог

    try:
        import pandas as pd
        if файл.suffix.lower() in ('.csv', '.txt', '.tsv'):
            таблица = pd.read_csv(файл, sep=None, engine='python')
        else:
            таблица = pd.read_excel(файл)
    except Exception as ошибка:  # noqa: BLE001 – выгрузка не должна падать из-за файла
        итог['reason'] = f'файл исходных данных не прочитан: {type(ошибка).__name__}'
        logger.warning('Файл исходных данных при выгрузке не прочитан: %s', ошибка)
        return итог

    try:
        from utils.data_fingerprint import compute_frame_fingerprint
        живой = compute_frame_fingerprint(таблица)
    except Exception as ошибка:  # noqa: BLE001
        итог['reason'] = f'отпечаток прочитанной таблицы не снят: {type(ошибка).__name__}'
        return итог

    итог['recorded_content_sha256'] = записанный
    итог['live_content_sha256'] = живой.get('content_sha256')
    if живой.get('status') != 'ok' or живой.get('content_sha256') != записанный:
        итог['status'] = 'mismatch'
        итог['reason'] = (
            'отпечаток таблицы, прочитанной из файла сейчас, не совпал с записанным при обучении – '
            'файл изменился, и его содержимое обучающим рядом считаться не может'
        )
        return итог

    итог['status'] = 'verified'
    итог['frame'] = таблица
    итог['reason'] = None
    return итог


def _сверка_ряда(построенный, имя: str, нормировка) -> Dict[str, Any]:
    """Сошлись ли статистики заново построенного признака с записанными.

    Средний и разброс признака модель хранит (они нужны нормировке). Значит
    правило построения регрессора не нужно принимать на слово: строим ряд по
    описанному правилу и сверяем. Совпало – описание проверено на этой самой
    модели; не совпало – так и сказано, без сглаживания.
    """
    записанные_средние = _числовой_словарь(нормировка.get('control_means'))
    записанные_разбросы = _числовой_словарь(нормировка.get('control_stds'))
    среднее_записано = записанные_средние.get(имя)
    разброс_записан = записанные_разбросы.get(имя)
    if среднее_записано is None or разброс_записан is None:
        return {'name': имя, 'status': 'no_reference',
                'note': 'среднее и разброс этого признака в модели не записаны – сверять не с чем'}

    среднее_заново = float(построенный.mean())
    # Разброс в модели записан правилом pandas (деление на n−1); сверка это
    # подтверждает численно, а не постулирует.
    разброс_заново = float(построенный.std())
    отклонение = max(
        abs(среднее_заново - среднее_записано),
        abs(разброс_заново - разброс_записан),
    )
    порог = _ДОПУСК_СВЕРКИ * max(1.0, abs(среднее_записано), abs(разброс_записан))
    return {
        'name': имя,
        'status': 'match' if отклонение <= порог else 'mismatch',
        'mean_recorded': среднее_записано,
        'mean_rebuilt': среднее_заново,
        'std_recorded': разброс_записан,
        'std_rebuilt': разброс_заново,
        'max_deviation': отклонение,
    }


def _свод_сверки(проверки: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Итог по набору сверок – одной строкой, без пересказа каждой."""
    если_есть = [п for п in проверки if п.get('status') in ('match', 'mismatch')]
    расхождения = [п['name'] for п in если_есть if п['status'] == 'mismatch']
    if not если_есть:
        return {'status': 'not_checked', 'checked': 0}
    return {
        'status': 'verified' if not расхождения else 'mismatch',
        'checked': len(если_есть),
        'mismatched': расхождения,
        'max_deviation': max(п.get('max_deviation') or 0.0 for п in если_есть),
        'tolerance': _ДОПУСК_СВЕРКИ,
    }


def _диапазон_дат(таблица, конфиг, длина_истории, нет) -> Dict[str, Any]:
    """Первая и последняя дата обучающего ряда.

    В модели дат нет вовсе – только длина ряда и шаг. Диапазон берётся из
    файла исходных данных и ТОЛЬКО при совпавшем отпечатке таблицы; иначе
    поле выходит пустым с указанием причины.
    """
    пусто = {
        'date_range': None,
        'date_range_origin': НЕ_ЗАПИСАНО,
    }
    if таблица.get('status') != 'verified':
        нет(
            'history.date_range',
            'диапазон дат обучающего ряда в модели не хранится, а восстановить его из файла '
            f'исходных данных не удалось: {таблица.get("reason") or "причина не установлена"}',
            'столбец дат файла исходных данных, указанный в history.date_column',
        )
        пусто['date_range_note'] = таблица.get('reason')
        return пусто

    столбец = _как_строку(конфиг.get('date_column'))
    рамка = таблица['frame']
    if not столбец or столбец not in рамка.columns:
        нет('history.date_range', 'столбец дат не найден в файле исходных данных')
        return пусто
    try:
        import pandas as pd
        даты = pd.to_datetime(рамка[столбец]).dropna()
        первая, последняя = даты.min(), даты.max()
        строк = int(len(даты))
    except Exception as ошибка:  # noqa: BLE001
        logger.warning('Диапазон дат при выгрузке не определён: %s', ошибка)
        нет('history.date_range', f'столбец дат не разобран: {type(ошибка).__name__}')
        return пусто

    return {
        'date_range': {
            'first': первая.date().isoformat(),
            'last': последняя.date().isoformat(),
            'n_dates': строк,
            'matches_history_length': (строк == длина_истории) if длина_истории else None,
        },
        'date_range_origin': РАССЧИТАНО,
        'date_range_note': (
            'Прочитано из файла исходных данных при выгрузке. Тождественность файла обучающей '
            'таблице доказана: отпечаток содержимого, пересчитанный сейчас, совпал с записанным '
            f'при обучении ({таблица.get("recorded_content_sha256")}). Правила отпечатка – '
            'в reproducibility.data_fingerprint_algorithm.'
        ),
    }


def _календарь_праздников(модель, нормировка, таблица, конфиг, нет) -> Optional[Dict[str, Any]]:
    """Календарные определения праздничных окон + правило режима.

    Двенадцать имён признаков и слово «доля» регрессор собрать не позволяют:
    нужны сами даты окон и правило пересчёта дат в число. И то и другое
    порождается календарным модулем из тех же определений, которыми считались
    дамми при обучении.
    """
    впрыснутые = _как_список_строк(нормировка.get('holiday_cols_injected'))
    if not впрыснутые:
        return None

    try:
        from utils.holiday_calendar_ru import describe_holiday_windows, generate_holiday_dummies
    except ImportError as ошибка:
        logger.warning('Календарь праздников при выгрузке не прочитан: %s', ошибка)
        нет('holiday_calendar', 'календарный модуль недоступен – окна праздников не описаны')
        return None

    режим = _как_строку(нормировка.get('holiday_dummies_mode'))
    даты = None
    годы: List[int] = []
    if таблица.get('status') == 'verified':
        столбец_даты = _как_строку(конфиг.get('date_column'))
        рамка = таблица['frame']
        if столбец_даты and столбец_даты in рамка.columns:
            try:
                import pandas as pd
                даты = pd.to_datetime(рамка[столбец_даты])
                годы = sorted({int(г) for г in даты.dt.year.dropna().tolist()})
            except Exception as ошибка:  # noqa: BLE001
                logger.warning('Столбец дат при выгрузке не разобран: %s', ошибка)
                даты = None

    def описание(для_режима: str) -> Dict[str, Any]:
        свод = describe_holiday_windows(годы, holidays=впрыснутые, mode=для_режима)
        if not годы:
            for событие in свод['events']:
                событие.pop('windows', None)
                событие.pop('n_days_total', None)
                событие['windows_note'] = (
                    'календарные границы не приведены: обучающий ряд дат недоступен '
                    '(см. holiday_calendar.source_data)'
                )
        return свод

    блок: Dict[str, Any] = {
        'origin': СПРАВОЧНО,
        'note': (
            'Определения окон взяты из календарного модуля продукта на момент выгрузки. '
            'Имена признаков и режим – из модели.'
        ),
        'injected': впрыснутые,
        'mode_recorded': режим,
        'mode_recorded_origin': ЗАПИСАНО if режим else НЕ_ЗАПИСАНО,
        'source_data': {
            'status': таблица.get('status'),
            'reason': таблица.get('reason'),
            'note': (
                'календарные границы окон выводятся из годов обучающего ряда, а он берётся из '
                'файла исходных данных только после сверки отпечатка таблицы'
            ),
        },
    }

    if режим:
        блок['calendar'] = описание(режим)
    else:
        блок['calendar'] = None
        блок['calendar_by_mode'] = {'fraction': описание('fraction'), 'binary_point': описание('binary_point')}
        блок['mode_note'] = (
            'Режим генерации признаков в модели не записан, а от него зависят окна распродаж – '
            'поэтому приведены оба варианта, без выбора за читателя.'
        )

    if даты is not None and режим:
        try:
            заново = generate_holiday_dummies(даты, holidays=впрыснутые, mode=режим)
            проверки = [_сверка_ряда(заново[имя], имя, нормировка) for имя in впрыснутые if имя in заново]
            блок['verification'] = _свод_сверки(проверки)
            блок['verification']['per_feature'] = проверки
            блок['verification']['note'] = (
                'признаки построены заново по описанным здесь окнам и режиму, из обучающего ряда '
                'дат, и сверены с записанными в модели средним и разбросом каждого признака'
            )
            if блок['verification'].get('status') == 'verified':
                блок['verification']['std_convention'] = (
                    'сверка сошлась при разбросе, посчитанном с делением на n−1 (соглашение pandas)'
                )
        except Exception as ошибка:  # noqa: BLE001
            logger.warning('Сверка праздничных признаков при выгрузке не выполнена: %s', ошибка)
            блок['verification'] = {'status': 'not_checked', 'reason': f'{type(ошибка).__name__}'}
    else:
        блок['verification'] = {
            'status': 'not_checked',
            'reason': (
                'обучающий ряд дат недоступен' if даты is None
                else 'режим генерации признаков в модели не записан'
            ),
        }

    if not годы:
        нет(
            'holiday_calendar.events[*].windows',
            'календарные границы праздничных окон не приведены: обучающий ряд дат в модели не '
            'хранится, а файл исходных данных не подтверждён отпечатком',
            'utils/holiday_calendar_ru.py – HOLIDAY_DEFINITIONS: окна заданы функцией от года',
        )
    return блок


# ─────────────────────────────────────────────────────────────────────
# Описание метода (не из модели – из кода продукта)
# ─────────────────────────────────────────────────────────────────────

def _спецификация() -> Dict[str, Any]:
    """Формулы модели – сверено с `engines/modeler.py` (сборка модели PyMC).

    Помечено `reference`: это описание метода из кода на момент выгрузки, а не
    запись в файле модели. Держать в согласии с `modeler.py` при правках модели.
    """
    геометрический_откат = {}
    вейбулловский_откат = {}
    try:
        from utils.adstock import geometric_adstock, weibull_adstock
        геометрический_откат = _значения_по_умолчанию(geometric_adstock)
        вейбулловский_откат = _значения_по_умолчанию(weibull_adstock)
    except ImportError as ошибка:
        logger.warning('Параметры переноса по умолчанию не прочитаны: %s', ошибка)

    return {
        'origin': СПРАВОЧНО,
        'source': 'engines/modeler.py – сборка модели PyMC; utils/adstock.py – перенос',
        'target': 'y_norm = (y − y_mean) / y_std',
        'likelihood': 'obs ~ Normal(mu, sigma)',
        'mu': 'mu = intercept + Σ_i beta_i · S_i + Σ_j control_beta_j · z_j',
        'saturation': (
            'S_i = x_i^alpha_i / (x_i^alpha_i + gamma_i^alpha_i + 1e−10), где '
            'x_i = adstock_i / mean(adstock_i). Делитель – среднее ряда переноса, '
            'вычисляемое ВНУТРИ модели на каждой выборке при том же значении затухания, '
            'что и сам ряд. Записанное channels[*].adstock_mean_posterior – апостериорное '
            'среднее этой величины, то есть ИТОГ обучения, а не входной делитель: '
            'подставлять его вместо mean(adstock_i) при пересчёте нельзя. '
            'Точка нормировки насыщения – только эта величина; '
            'normalization.media_means к ней отношения не имеет'
        ),
        'adstock_geometric': 'a_t = spend_t + decay · a_(t−1), a_0 = spend_0',
        'adstock_weibull': (
            'свёртка ряда с весами функции распределения Вейбулла (shape, scale, max_lag); '
            'параметры при обучении фиксированы, в модели не записаны'
        ),
        'controls': 'z_j = (control_j − control_means_j) / control_stds_j',
        'adstock_defaults_in_code': {
            'geometric': геометрический_откат,
            'weibull': вейбулловский_откат,
            'note': (
                'значения по умолчанию из кода продукта на момент выгрузки. Применялись к каналам, '
                'чей перенос считался вне модели (тип отличен от geometric, включая незафиксированный auto)'
            ),
        },
        'note': (
            'Описание метода взято из кода продукта, а не из файла модели: сама модель формул '
            'не хранит. Коэффициенты ниже относятся к нормированной шкале – чтобы вернуться '
            'к исходным единицам KPI, результат умножается на y_std и складывается с y_mean.'
        ),
    }


# ─────────────────────────────────────────────────────────────────────
# Основная выгрузка
# ─────────────────────────────────────────────────────────────────────

def export_model_params_json(
    model_data: Dict[str, Any],
    pretty: bool = True,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> str:
    """Выгрузить параметры обученной модели в JSON-строку (схема 3.0).

    Args:
        model_data: загруженная модель (`load_model_with_compat()`).
        pretty: отступы для чтения человеком. False – компактно.
        diagnostics: необязательное содержимое `results/model-diagnostics.json`.
            В самой модели диагностики нет – не передали, блок объявляется
            отсутствующим, а не заполняется пустышками.

    Returns:
        JSON-строка. Полное описание полей – в ключе `schema` самого документа.

    Побочные чтения (только чтение, ничего не пишется):
        * `engines/modeler.py` – разбирается как текст, чтобы назвать семейства
          приоров и настройки сэмплера, а не переписывать их сюда руками;
        * файл исходных данных проекта – открывается ТОЛЬКО если в модели есть
          отпечаток таблицы, и используется лишь при его совпадении. Отсюда
          берутся диапазон дат обучающего ряда и проверка праздничных признаков.
          Файла нет, он изменился или отпечатка не записано – соответствующие
          поля выходят пустыми с указанием причины.
    """
    модель: Dict[str, Any] = model_data if isinstance(model_data, dict) else {}
    конфиг: Dict[str, Any] = модель.get('config') or {}
    нормировка: Dict[str, Any] = модель.get('normalization') or {}
    выборки: Dict[str, Any] = модель.get('posterior_samples') or {}

    пропуски: List[Dict[str, str]] = []

    def нет(поле: str, почему: str, где: Optional[str] = None) -> None:
        """Зарегистрировать честное отсутствие поля."""
        запись = {'field': поле, 'reason': почему}
        if где:
            запись['where_to_find'] = где
        пропуски.append(запись)

    payload: Dict[str, Any] = {}

    # ─── Паспорт документа ──────────────────────────────────────────
    payload['schema'] = {
        'name': 'aurora-econometrica-model-params',
        'version': СХЕМА_ВЕРСИЯ,
        'language': 'ru',
        'purpose': (
            'Спецификация обученной модели для независимой проверки и воспроизведения '
            'сторонним аналитиком.'
        ),
        'origins': _РАСШИФРОВКА_ИСТОЧНИКОВ,
        'honesty_rule': (
            'Значения по умолчанию не подставляются. Отсутствующее в модели поле выходит пустым '
            '(null) и перечислено в absent_fields с пояснением, где эта величина есть.'
        ),
        # Соглашения документа. Каждое из них читатель прежде выводил догадкой,
        # а догадка в заверяемом документе – это тот же домысел, только на
        # стороне читателя.
        'conventions': {
            'range_90': (
                'Правдоподобный диапазон 90% – квантильный: 5-й и 95-й процентили апостериорных '
                'выборок параметра с линейной интерполяцией. Это НЕ интервал наибольшей плотности.'
            ),
            'signed_factors': (
                'Знаковые факторы входят в ту же сумму, что и остальные контроли: в модели это один '
                'вектор коэффициентов по всем контрольным столбцам. Раздел signed_factors выделен '
                'только по виду фактора, отдельного слагаемого в уравнении у него нет.'
            ),
            'rounding': (
                'Параметры каналов (beta, hill_alpha, hill_gamma, adstock_decay, '
                'adstock_mean_posterior) записаны в модели округлёнными до 4 знаков после запятой – '
                'так их сохраняет обучение. Статистики по выборкам (разброс, границы диапазона) и '
                'величины нормировки приведены с полной точностью, поэтому знаков у них больше.'
            ),
            'origin_of_conventions': СПРАВОЧНО,
        },
    }

    # ─── Модель ─────────────────────────────────────────────────────
    версия_модели = _как_строку(модель.get('model_version'))
    if версия_модели is None:
        нет('model.version', 'версия схемы модели в файле не записана')
    иерархическая = модель.get('use_hierarchical')
    payload['model'] = {
        'version': версия_модели,
        'version_origin': ЗАПИСАНО if версия_модели else НЕ_ЗАПИСАНО,
        'hierarchical_adstock': bool(иерархическая) if isinstance(иерархическая, bool) else None,
        'hierarchical_adstock_origin': ЗАПИСАНО if isinstance(иерархическая, bool) else НЕ_ЗАПИСАНО,
    }

    # Режим анализа: в моделях этой версии не записывается (загрузчик кладёт None).
    режим = _как_строку(модель.get('analysis_mode'))
    выведенный_режим = _как_строку(модель.get('derived_mode'))
    if режим is None:
        нет(
            'model.analysis_mode',
            'режим анализа при обучении не записан (поле появилось в схеме позже)',
            'derived_mode – выводится загрузчиком по полю per_channel_input, это не запись обучения',
        )
    payload['model']['analysis_mode'] = режим
    payload['model']['analysis_mode_origin'] = ЗАПИСАНО if режим else НЕ_ЗАПИСАНО
    payload['model']['derived_mode'] = выведенный_режим
    payload['model']['derived_mode_origin'] = СПРАВОЧНО if выведенный_режим else НЕ_ЗАПИСАНО

    # ─── KPI ────────────────────────────────────────────────────────
    kpi_type = _как_строку(модель.get('kpi_type'))
    kpi_kind = _как_строку(модель.get('kpi_kind'))
    kpi_likelihood = _как_строку(модель.get('kpi_likelihood'))
    kpi_column = _как_строку(конфиг.get('kpi_column'))
    if kpi_column is None:
        нет('kpi.column', 'имя столбца KPI в конфигурации модели не записано')
    # Единица KPI. Валюта в модели не хранится – называем род величины и
    # прямо говорим, что валюту документ не заверяет.
    подпись_единицы = _как_строку(модель.get('value_per_count_unit_label'))
    payload['kpi'] = {
        'type': kpi_type,
        'unit_kind': kpi_kind,
        'unit_kind_origin': ЗАПИСАНО if kpi_kind else НЕ_ЗАПИСАНО,
        'unit_kind_note': (
            "род величины KPI: 'monetary' – денежная, 'count' – счётная, 'proportional' – доля. "
            'Конкретная валюта или единица счёта в модели не записана: она задана столбцом '
            'исходных данных, имя которого приведено в kpi.column'
        ),
        'unit_label': подпись_единицы,
        'unit_label_origin': ЗАПИСАНО if подпись_единицы else НЕ_ЗАПИСАНО,
        'type_origin': ЗАПИСАНО if kpi_type else НЕ_ЗАПИСАНО,
        'kind': kpi_kind,
        'kind_origin': ЗАПИСАНО if kpi_kind else НЕ_ЗАПИСАНО,
        'likelihood': kpi_likelihood,
        'likelihood_origin': ЗАПИСАНО if kpi_likelihood else НЕ_ЗАПИСАНО,
        'column': kpi_column,
        'column_origin': ЗАПИСАНО if kpi_column else НЕ_ЗАПИСАНО,
        'unit_cost': _как_число(модель.get('kpi_unit_cost_snapshot')),
        'unit_cost_origin': (
            ЗАПИСАНО if _как_число(модель.get('kpi_unit_cost_snapshot')) is not None else НЕ_ЗАПИСАНО
        ),
    }

    # ─── История обучения ───────────────────────────────────────────
    ряд_kpi = модель.get('y_actual')
    длина_истории = len(ряд_kpi) if isinstance(ряд_kpi, (list, tuple)) else None
    if длина_истории is None:
        нет('history.length', 'ряд KPI (y_actual) в модели отсутствует – длину истории взять неоткуда')
    гранулярность = _как_строку(модель.get('training_granularity'))
    if гранулярность is None:
        нет(
            'history.granularity',
            'гранулярность обучения не записана (поле появилось в схеме позже)',
            'восстанавливается по столбцу дат исходных данных: utils/forecast_validation.detect_granularity',
        )
    файл_данных = _как_строку(конфиг.get('data_file'))
    таблица = _таблица_исходных_данных(модель, конфиг)
    payload['history'] = {
        'length': длина_истории,
        'length_origin': РАССЧИТАНО if длина_истории is not None else НЕ_ЗАПИСАНО,
        'length_note': 'число наблюдений в ряде KPI, на котором обучалась модель',
        'granularity': гранулярность,
        'granularity_origin': ЗАПИСАНО if гранулярность else НЕ_ЗАПИСАНО,
        'granularity_note': "код периода: 'M' – месяц, 'W' – неделя, 'D' – день",
        'date_column': _как_строку(конфиг.get('date_column')),
        'date_column_origin': ЗАПИСАНО if _как_строку(конфиг.get('date_column')) else НЕ_ЗАПИСАНО,
        # Полный путь намеренно не выводится: документ уходит третьей стороне,
        # а путь несёт имя пользователя и структуру его дисков.
        'data_file_name': Path(файл_данных).name if файл_данных else None,
        'data_file_name_origin': РАССЧИТАНО if файл_данных else НЕ_ЗАПИСАНО,
    }
    payload['history'].update(_диапазон_дат(таблица, конфиг, длина_истории, нет))

    # ─── Спецификация метода ────────────────────────────────────────
    payload['specification'] = _спецификация()

    # ─── Каналы ─────────────────────────────────────────────────────
    payload['channels'] = _каналы(модель, конфиг, нормировка, выборки, нет)

    # ─── Контроли, знаковые факторы, праздники ──────────────────────
    контроли, знаковые, праздники = _контроли(модель, конфиг, нормировка, нет)
    payload['controls'] = контроли
    payload['signed_factors'] = знаковые
    payload['holidays_injected'] = праздники

    # ─── Календарь праздничных окон ─────────────────────────────────
    payload['holiday_calendar'] = _календарь_праздников(модель, нормировка, таблица, конфиг, нет)

    # ─── Сезонность ─────────────────────────────────────────────────
    payload['seasonality'] = _сезонность(модель, нормировка, нет)

    # ─── Нормировка ─────────────────────────────────────────────────
    payload['normalization'] = _нормировка(нормировка, нет)

    # ─── Приоры ─────────────────────────────────────────────────────
    payload['priors'] = _приоры(модель, конфиг, нормировка, нет)

    # ─── Сэмплирование ──────────────────────────────────────────────
    payload['sampling'] = _сэмплирование(модель, выборки, нет)

    # ─── Диагностика ────────────────────────────────────────────────
    payload['diagnostics'] = _диагностика(diagnostics, нет)

    # ─── Воспроизводимость ──────────────────────────────────────────
    payload['reproducibility'] = _воспроизводимость(модель, нет)

    # ─── Чего в документе нет ───────────────────────────────────────
    payload['not_included'] = {
        'channel_roi': {
            'note': (
                'Окупаемость каналов в этом документе не приводится: она не параметр модели, '
                'а результат разложения продаж по вкладам.'
            ),
            'where_to_find': 'engines/decomposer.py – результат в results/decomposition.json проекта',
        },
        'optimization': {
            'note': 'Рекомендации по перераспределению бюджета – отдельный расчёт, не параметр модели.',
            'where_to_find': 'engines/optimizer.py – результат в results/optimization.json проекта',
        },
        'raw_data': {
            'note': 'Исходные данные в документ не включаются – только имя файла и параметры нормировки.',
            'where_to_find': 'файл данных проекта, указанный при обучении',
        },
        'posterior_samples': {
            'note': (
                'Полные апостериорные выборки (тысячи значений на параметр) в документ не включаются '
                'из-за объёма – по ним посчитаны разброс и правдоподобный диапазон 90% каждого параметра.'
            ),
            'where_to_find': 'файл модели проекта, раздел posterior_samples',
        },
    }

    payload['absent_fields'] = пропуски

    return json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)


# ─────────────────────────────────────────────────────────────────────
# Блоки выгрузки
# ─────────────────────────────────────────────────────────────────────

def _каналы(модель, конфиг, нормировка, выборки, нет) -> Dict[str, Any]:
    """Параметры медиаканалов: коэффициент, насыщение, перенос, нормировка.

    Разброс коэффициентов в модели не хранится, но хранятся апостериорные
    выборки – разброс и правдоподобный диапазон считаются из них и помечаются
    расчётными. Выборки сопоставляются каналу ПО ИМЕНИ (`media_columns`), а не
    по позиции: порядок ключей словаря параметров не обязан совпадать с
    порядком строк в массиве выборок, и молчаливая склейка по позиции дала бы
    чужие числа под именем канала.
    """
    параметры_каналов: Dict[str, Any] = модель.get('channel_params') or {}
    категории: Dict[str, Any] = модель.get('channel_categories') or {}
    типы_переноса: Dict[str, Any] = модель.get('channel_adstock_types') or {}
    протокол_переноса: Dict[str, Any] = модель.get('adstock_selection') or {}
    параметры_вейбулла: Dict[str, Any] = модель.get('weibull_params_per_channel') or {}
    стоимости: Dict[str, Any] = модель.get('unit_costs_snapshot') or {}
    единицы_каналов: Dict[str, Any] = модель.get('per_channel_input') or {}
    средние_каналов = _числовой_словарь(нормировка.get('media_means'))
    необученные = set(_как_список_строк(нормировка.get('untrained_channels')))
    порядок_выборок = _как_список_строк(выборки.get('media_columns'))

    if not параметры_каналов:
        нет('channels', 'параметры каналов в модели отсутствуют – модель не обучена или файл повреждён')
        return {}
    if not категории:
        # Пустая категория читается как пробел в спецификации приоров – так её и
        # прочёл посторонний аналитик. Но приоры зависят от категории только в
        # иерархической ветви; когда иерархия выключена, пробела нет вовсе, и
        # сказать об этом надо там, где читатель споткнулся.
        иерархическая = модель.get('use_hierarchical')
        где_искать = 'назначаются пользователем на шаге настройки; пустое поле означает «не назначено»'
        if иерархическая is False:
            где_искать += (
                '. На спецификацию приоров ЭТОЙ модели категория не влияет: иерархия по группам '
                'каналов была выключена, применялся общий приор коэффициента – см. '
                'priors.specification_from_code'
            )
        нет(
            'channels[*].category',
            'категории каналов (бренд / отклик / смешанный) при обучении не назначены',
            где_искать,
        )

    def выборка(имя_массива: str, канал: str):
        строки = выборки.get(имя_массива)
        if строки is None or канал not in порядок_выборок:
            return None
        индекс = порядок_выборок.index(канал)
        try:
            return строки[индекс]
        except (IndexError, KeyError, TypeError):
            return None

    результат: Dict[str, Any] = {}
    for канал, параметры in параметры_каналов.items():
        параметры = параметры or {}
        имя = str(канал)
        источники: Dict[str, str] = {}
        примечания: Dict[str, str] = {}
        запись: Dict[str, Any] = {}

        # Коэффициент и параметры насыщения – прямая запись модели.
        for ключ_выдачи, ключ_модели, имя_выборок in (
            ('beta', 'beta', 'media_betas'),
            ('hill_alpha', 'alpha', 'alphas'),
            ('hill_gamma', 'gamma', 'gammas'),
            ('adstock_decay', 'decay', 'adstock_decay'),
        ):
            значение = _как_число(параметры.get(ключ_модели))
            запись[ключ_выдачи] = значение
            источники[ключ_выдачи] = ЗАПИСАНО if значение is not None else НЕ_ЗАПИСАНО
            if значение is None:
                нет(f'channels["{имя}"].{ключ_выдачи}', f'поле {ключ_модели} в параметрах канала отсутствует')

            статистика = _статистика_по_выборкам(выборка(имя_выборок, имя))
            запись[f'{ключ_выдачи}_std'] = статистика['std'] if статистика else None
            запись[f'{ключ_выдачи}_range_90'] = статистика['range_90'] if статистика else None
            источники[f'{ключ_выдачи}_std'] = РАССЧИТАНО if статистика else НЕ_ЗАПИСАНО
            источники[f'{ключ_выдачи}_range_90'] = РАССЧИТАНО if статистика else НЕ_ЗАПИСАНО
            if статистика is None:
                нет(
                    f'channels["{имя}"].{ключ_выдачи}_std',
                    'апостериорные выборки для этого канала недоступны – разброс не посчитан',
                    'раздел posterior_samples файла модели',
                )

        # Перенос: тип и то, как он попал в модель. Подстановка запрещена.
        запись.update(_перенос_канала(имя, параметры, типы_переноса, протокол_переноса,
                                      параметры_вейбулла, источники, примечания, нет))

        # Нормировочные величины канала – без них воспроизвести насыщение нельзя.
        среднее_переноса = _как_число(параметры.get('adstock_mean_posterior'))
        запись['adstock_mean_posterior'] = среднее_переноса
        источники['adstock_mean_posterior'] = ЗАПИСАНО if среднее_переноса is not None else НЕ_ЗАПИСАНО
        if среднее_переноса is None:
            нет(
                f'channels["{имя}"].adstock_mean_posterior',
                'апостериорное среднее ряда переноса не записано (модели ранних версий)',
                'заменить его нормировочной средней normalization.media_means НЕЛЬЗЯ: '
                'та считается по ряду с фиксированным коэффициентом переноса 0,5, а не по '
                'апостериорному – это другое основание',
            )
        # Единица ряда канала. Валюта нигде не записана – называем род величины
        # и явно относим к нему все производные числа канала.
        род_единицы = _как_строку(единицы_каналов.get(имя))
        запись['unit_kind'] = род_единицы
        источники['unit_kind'] = ЗАПИСАНО if род_единицы else НЕ_ЗАПИСАНО
        примечания['unit_kind'] = (
            "род величины ряда канала: 'monetary' – денежная (бюджет), 'count' – счётная "
            '(показы, контакты). Конкретная валюта или единица счёта в модели не записана – '
            'она задана столбцом исходных данных, имя которого стоит ключом этого раздела. '
            'В этих же единицах выражены adstock_mean_posterior и media_mean; коэффициент beta '
            'безразмерен – он относится к нормированной шкале KPI'
        )
        if род_единицы is None:
            нет(
                f'channels["{имя}"].unit_kind',
                'род величины ряда канала (денежная / счётная) в модели не записан',
                'per_channel_input файла модели – поле появилось в схеме позже',
            )
        запись['media_mean'] = средние_каналов.get(имя)
        источники['media_mean'] = ЗАПИСАНО if средние_каналов.get(имя) is not None else НЕ_ЗАПИСАНО
        примечания['media_mean'] = (
            'среднее ряда ПОСЛЕ переноса с фиксированным коэффициентом 0,5 – масштаб входного '
            'медиаряда, а не средние траты канала. Точкой нормировки насыщения НЕ является: '
            'там делитель считается внутри модели (см. specification.saturation)'
        )
        запись['unit_cost_applied'] = _как_число(стоимости.get(имя))
        источники['unit_cost_applied'] = (
            ЗАПИСАНО if _как_число(стоимости.get(имя)) is not None else НЕ_ЗАПИСАНО
        )
        примечания['unit_cost_applied'] = (
            'множитель, применённый к сырому ряду канала до переноса (перевод в денежную шкалу); '
            'пусто – множитель не применялся'
        )

        # Признаки надёжности.
        хвостовая_выборка = параметры.get('tail_ess_ok')
        запись['tail_ess_ok'] = bool(хвостовая_выборка) if isinstance(хвостовая_выборка, bool) else None
        источники['tail_ess_ok'] = ЗАПИСАНО if isinstance(хвостовая_выборка, bool) else НЕ_ЗАПИСАНО
        примечания['tail_ess_ok'] = (
            'хватило ли эффективного размера выборки в хвостах для устойчивой оценки границ диапазона'
        )
        запись['untrained'] = имя in необученные
        источники['untrained'] = РАССЧИТАНО
        примечания['untrained'] = (
            'канал без изменчивости в обучающих данных: коэффициент не идентифицируем, '
            'оценка определяется приором'
        )

        категория = _как_строку(категории.get(имя))
        запись['category'] = категория
        источники['category'] = ЗАПИСАНО if категория else НЕ_ЗАПИСАНО

        запись['origin'] = источники
        запись['notes'] = примечания
        результат[имя] = запись

    return результат


def _перенос_канала(имя, параметры, типы_переноса, протокол_переноса,
                    параметры_вейбулла, источники, примечания, нет) -> Dict[str, Any]:
    """Тип переноса канала – единственное поле, где подстановка запрещена жёстко.

    Три состояния:
      * записан конкретный тип (`geometric` / `weibull`) → выводим как факт;
      * записана настройка `'auto'` (модели до 06.07.2026) → тип НЕ ВОССТАНАВЛИВАЕМ:
        это «что просили», а не «что применилось». Фактически такой канал входил
        в модель предвычисленным геометрическим рядом (`utils/adstock.apply_adstock`
        уводит неизвестный тип в геометрическую ветку), но восстанавливать по этому
        рассуждению «фактический тип» задним числом мы не вправе – говорим прямо,
        что тип не зафиксирован, и поясняем, как шёл расчёт;
      * поля нет вовсе → пусто.

    Отдельно выводится признак «откат выучен при обучении». По коду модели
    (`modeler.py`, цикл сборки медиа-вклада) сэмплируемый откат входит в
    правдоподобие ТОЛЬКО у геометрических каналов; у остальных ряд переноса
    предвычислен, и апостериорный откат остаётся при своём приоре. Замер на живых
    моделях это подтверждает: у модели со всеми каналами `'auto'` среднее и разброс
    отката совпадают с приорными. Без этого признака число «откат 0,25» читалось бы
    как выученная величина.
    """
    запись: Dict[str, Any] = {}

    вложенный = параметры.get('adstock')
    записанный = None
    if isinstance(вложенный, dict):
        записанный = _как_строку(вложенный.get('type'))
    верхний = _как_строку(типы_переноса.get(имя))
    if записанный is None:
        записанный = верхний

    запись['adstock_type_recorded'] = записанный
    источники['adstock_type_recorded'] = ЗАПИСАНО if записанный else НЕ_ЗАПИСАНО
    примечания['adstock_type_recorded'] = 'значение, записанное в модели буквально, без толкования'

    if записанный in _ФАКТИЧЕСКИЕ_ТИПЫ_ПЕРЕНОСА:
        запись['adstock_type'] = записанный
        источники['adstock_type'] = ЗАПИСАНО
    else:
        запись['adstock_type'] = None
        источники['adstock_type'] = НЕ_ЗАПИСАНО
        if записанный == 'auto':
            примечания['adstock_type'] = (
                'Тип переноса не зафиксирован: в модели записана настройка «auto» – что просили, '
                'а не что применилось. Восстановить фактический тип задним числом нельзя: модель '
                'обучена прежней версией программы, поведение которой этот документ не заверяет. '
                'Чтобы тип был зафиксирован, переобучите модель.'
            )
            нет(
                f'channels["{имя}"].adstock_type',
                'в модели записана настройка «auto» – применённый тип переноса не зафиксирован',
                'модели, обученные после 06.07.2026, записывают конкретный тип и протокол выбора '
                '(adstock_selection)',
            )
        elif записанный is None:
            примечания['adstock_type'] = 'Тип переноса в модели не записан.'
            нет(f'channels["{имя}"].adstock_type', 'тип переноса канала в модели не записан')
        else:
            примечания['adstock_type'] = (
                f'В модели записано значение «{записанный}», которого расчётные пути продукта '
                'не знают. Фактическим типом оно считаться не может.'
            )
            нет(
                f'channels["{имя}"].adstock_type',
                f'записанное значение «{записанный}» не является известным типом переноса',
            )

    if верхний is not None and записанный is not None and верхний != записанный:
        примечания['adstock_type_conflict'] = (
            f'Два источника модели расходятся: в параметрах канала «{записанный}», '
            f'в списке типов «{верхний}». Выведено значение из параметров канала.'
        )

    # Протокол выбора типа: что просили, что применили, кто решил.
    протокол = протокол_переноса.get(имя) if isinstance(протокол_переноса, dict) else None
    if isinstance(протокол, dict):
        запись['adstock_selection'] = {
            'requested': _как_строку(протокол.get('requested')),
            'resolved': _как_строку(протокол.get('resolved')),
            'decided_by': _как_строку(протокол.get('by')),
        }
        источники['adstock_selection'] = ЗАПИСАНО
    else:
        запись['adstock_selection'] = None
        источники['adstock_selection'] = НЕ_ЗАПИСАНО
        нет(
            f'channels["{имя}"].adstock_selection',
            'протокол выбора типа переноса (что просили / что применили / кто решил) не записан – '
            'поле появилось в схеме позже',
        )

    # Выучен ли откат: зависит ровно от того, геометрический ли канал.
    if запись['adstock_type'] == 'geometric':
        запись['adstock_decay_learned'] = True
        примечания['adstock_decay_learned'] = (
            'откат входил в правдоподобие: перенос считался внутри модели с сэмплируемым откатом'
        )
    elif записанный is None:
        запись['adstock_decay_learned'] = None
        примечания['adstock_decay_learned'] = (
            'тип переноса не записан – определить, входил ли откат в правдоподобие, нельзя'
        )
    else:
        запись['adstock_decay_learned'] = False
        примечания['adstock_decay_learned'] = (
            'откат в правдоподобие НЕ входил: ряд переноса для этого канала предвычислен вне модели, '
            'поэтому апостериорная оценка отката осталась близка к приорной и выученной величиной '
            'не является'
        )
    источники['adstock_decay_learned'] = РАССЧИТАНО

    вейбулл = параметры_вейбулла.get(имя) if isinstance(параметры_вейбулла, dict) else None
    if isinstance(вейбулл, dict) and вейбулл:
        запись['weibull_params'] = _числовой_словарь(вейбулл)
        источники['weibull_params'] = ЗАПИСАНО
    elif записанный == 'weibull':
        запись['weibull_params'] = None
        источники['weibull_params'] = НЕ_ЗАПИСАНО
        примечания['weibull_params'] = (
            'параметры вейбулловского переноса при обучении фиксированы кодом и в модели не записаны. '
            'В specification.adstock_defaults_in_code приведены значения из кода продукта на момент '
            'выгрузки – совпадение с версией, которой обучена эта модель, не гарантировано'
        )
        нет(
            f'channels["{имя}"].weibull_params',
            'параметры вейбулловского переноса (shape / scale / max_lag) в модели не записаны',
            'значения по умолчанию из кода продукта на момент выгрузки: specification.adstock_defaults_in_code',
        )

    return запись


def _контроли(модель, конфиг, нормировка, нет):
    """Контрольные переменные, знаковые факторы и праздничные признаки.

    Вид фактора берётся из модели (`normalization.control_kinds`) – это то, что
    применялось при обучении. Классификация имени заново, как делала прежняя
    версия модуля, завела бы второй источник истины: правила распознавания с тех
    пор могли измениться, и документ показал бы вид, отличный от применённого.
    Повторная классификация оставлена только запасным путём для старых моделей,
    где вид не записан, – и помечена расчётной.
    """
    столбцы = _как_список_строк(конфиг.get('control_columns'))
    коэффициенты = [_как_число(v) for v in (нормировка.get('control_betas_mean') or [])]
    виды = _как_список_строк(нормировка.get('control_kinds'))
    приорные_средние = [_как_число(v) for v in (нормировка.get('control_prior_mus') or [])]
    праздники_модели = _как_список_строк(нормировка.get('holiday_cols_injected'))
    необученные = set(_как_список_строк(нормировка.get('untrained_controls')))

    контроли: Dict[str, Any] = {}
    знаковые: Dict[str, Any] = {}

    if not столбцы:
        return контроли, знаковые, праздники_модели

    if len(коэффициенты) != len(столбцы):
        нет(
            'controls[*].beta',
            f'число коэффициентов контролей ({len(коэффициенты)}) не совпадает с числом '
            f'контрольных столбцов ({len(столбцы)}) – сопоставить их нельзя',
            'раздел normalization.control_betas_mean файла модели',
        )

    вид_расчётный = False
    if len(виды) != len(столбцы):
        виды = []
        try:
            from utils.column_detection import classify_column
            виды = [str(classify_column(столбец)) for столбец in столбцы]
            вид_расчётный = True
        except Exception as ошибка:  # noqa: BLE001
            logger.warning('Вид контрольных факторов не определён при выгрузке: %s', ошибка)
            нет('controls[*].kind', 'вид контрольного фактора в модели не записан и не восстановлен')

    for индекс, столбец in enumerate(столбцы):
        коэффициент = коэффициенты[индекс] if индекс < len(коэффициенты) else None
        вид = виды[индекс] if индекс < len(виды) else None
        запись = {
            'beta': коэффициент,
            'kind': вид,
            'prior_mean': приорные_средние[индекс] if индекс < len(приорные_средние) else None,
            'untrained': столбец in необученные,
            'origin': {
                'beta': ЗАПИСАНО if коэффициент is not None else НЕ_ЗАПИСАНО,
                'kind': (РАССЧИТАНО if вид_расчётный else ЗАПИСАНО) if вид else НЕ_ЗАПИСАНО,
                'prior_mean': (
                    ЗАПИСАНО if индекс < len(приорные_средние) and приорные_средние[индекс] is not None
                    else НЕ_ЗАПИСАНО
                ),
                'untrained': РАССЧИТАНО,
            },
        }
        if вид in ('signed_competitor', 'signed_price', 'signed_weather', 'signed_macro'):
            знаковые[столбец] = запись
        else:
            контроли[столбец] = запись

    return контроли, знаковые, праздники_модели


def _правило_фурье(фурье, модель, нормировка) -> Dict[str, Any]:
    """Правило построения сезонных признаков + проверка его на этой модели.

    Период и число гармоник без формулы регрессор не задают: неизвестны начало
    отсчёта и фаза. Формула приводится здесь, а от расхождения с кодом её
    страхует не обещание «держать в согласии», а сверка: ряд строится функцией
    продукта и сличается с записанными средним и разбросом каждого признака.
    Разошлось – так и написано.
    """
    период = _как_целое(фурье.get('period'))
    гармоник = _как_целое(фурье.get('n_harmonics'))
    столбцы = _как_список_строк(фурье.get('columns'))

    правило: Dict[str, Any] = {
        'origin': СПРАВОЧНО,
        'source': 'utils/fourier_seasonality.py – generate_fourier_terms',
        'note': _ОГОВОРКА_КОДА,
        'formula': (
            'season_fourier_sin_k[t] = sin(2π · k · t / P), '
            'season_fourier_cos_k[t] = cos(2π · k · t / P)'
        ),
        'index_rule': (
            't – ПОЗИЦИЯ наблюдения в обучающем ряду, отсчёт с нуля: t = 0, 1, …, n−1. '
            'Календарные даты в построении не участвуют, поэтому фаза привязана к первой строке '
            'ряда, а не к календарному месяцу.'
        ),
        'k_rule': 'k – номер гармоники, от 1 до числа гармоник включительно.',
        'period_symbol': 'P – период сезонности (period ниже), в шагах ряда',
        'column_order': (
            'на каждую гармонику k выходят два столбца в порядке sin_k, cos_k; значения в [−1, 1]'
        ),
    }

    y_ряд = модель.get('y_actual')
    длина = len(y_ряд) if isinstance(y_ряд, (list, tuple)) else None
    if период and гармоник and длина:
        try:
            from utils.fourier_seasonality import generate_fourier_terms
            заново = generate_fourier_terms(длина, период, гармоник)
            проверки = [_сверка_ряда(заново[имя], имя, нормировка) for имя in столбцы if имя in заново]
            свод = _свод_сверки(проверки)
            свод['per_feature'] = проверки
            свод['note'] = (
                'признаки построены заново по приведённой формуле на ряду той же длины и сверены '
                'с записанными в модели средним и разбросом каждого признака'
            )
            правило['verification'] = свод
        except Exception as ошибка:  # noqa: BLE001
            logger.warning('Сверка сезонных признаков при выгрузке не выполнена: %s', ошибка)
            правило['verification'] = {'status': 'not_checked', 'reason': f'{type(ошибка).__name__}'}
    else:
        правило['verification'] = {
            'status': 'not_checked',
            'reason': 'период, число гармоник или длина ряда в модели отсутствуют',
        }
    return правило


def _сезонность(модель, нормировка, нет) -> Dict[str, Any]:
    """Что инжектировано в модель как сезонные признаки и что было обнаружено."""
    фурье = модель.get('fourier_seasonality')
    обнаружено = модель.get('seasonality_detected')

    блок: Dict[str, Any] = {}
    if isinstance(фурье, dict) and фурье:
        блок['fourier_injected'] = {
            'period': _как_число(фурье.get('period')),
            'n_harmonics': _как_число(фурье.get('n_harmonics')),
            'columns': _как_список_строк(фурье.get('columns')),
            'granularity': _как_строку(фурье.get('granularity')),
            'autocorrelation': _как_число(фурье.get('autocorr')),
            'origin': ЗАПИСАНО,
        }
        блок['fourier_rule'] = _правило_фурье(фурье, модель, нормировка)
    else:
        блок['fourier_injected'] = None
        блок['fourier_injected_origin'] = НЕ_ЗАПИСАНО
        блок['fourier_rule'] = None
        нет(
            'seasonality.fourier_injected',
            'сезонная волна в модель не инжектировалась (не прошла проверку или функция '
            'появилась позже обучения)',
        )

    if isinstance(обнаружено, dict) and обнаружено:
        блок['detected'] = {
            'period': _как_число(обнаружено.get('period')),
            'autocorrelation': _как_число(обнаружено.get('autocorr')),
            'origin': ЗАПИСАНО,
            'note': 'результат проверки ряда KPI на цикличность; сам по себе в модель не входит',
        }
    else:
        блок['detected'] = None
        блок['detected_origin'] = НЕ_ЗАПИСАНО

    return блок


def _нормировка(нормировка, нет) -> Dict[str, Any]:
    """Величины нормировки – без них коэффициенты нельзя вернуть в исходную шкалу."""
    if not нормировка:
        нет('normalization', 'раздел нормировки в модели отсутствует')
        return {}

    среднее_kpi = _как_число(нормировка.get('y_mean'))
    разброс_kpi = _как_число(нормировка.get('y_std'))
    свободный_член = _как_число(нормировка.get('intercept_mean'))
    режим_праздников = _как_строку(нормировка.get('holiday_dummies_mode'))
    if среднее_kpi is None or разброс_kpi is None:
        нет('normalization.y_mean / y_std', 'параметры нормировки KPI в модели не записаны')
    if режим_праздников is None:
        нет(
            'normalization.holiday_dummies_mode',
            'режим генерации праздничных признаков не записан (модели до 05.07.2026)',
            'разложение применяет к таким моделям режим точечных признаков – см. engines/decomposer.py',
        )

    return {
        'y_mean': среднее_kpi,
        'y_std': разброс_kpi,
        'intercept_mean': свободный_член,
        'media_means': _числовой_словарь(нормировка.get('media_means')),
        'control_means': _числовой_словарь(нормировка.get('control_means')),
        'control_stds': _числовой_словарь(нормировка.get('control_stds')),
        'untrained_channels': _как_список_строк(нормировка.get('untrained_channels')),
        'untrained_controls': _как_список_строк(нормировка.get('untrained_controls')),
        'holiday_dummies_mode': режим_праздников,
        'origin': {
            'y_mean': ЗАПИСАНО if среднее_kpi is not None else НЕ_ЗАПИСАНО,
            'y_std': ЗАПИСАНО if разброс_kpi is not None else НЕ_ЗАПИСАНО,
            'intercept_mean': ЗАПИСАНО if свободный_член is not None else НЕ_ЗАПИСАНО,
            'media_means': ЗАПИСАНО,
            'control_means': ЗАПИСАНО,
            'control_stds': ЗАПИСАНО,
            'untrained_channels': ЗАПИСАНО,
            'untrained_controls': ЗАПИСАНО,
            'holiday_dummies_mode': ЗАПИСАНО if режим_праздников else НЕ_ЗАПИСАНО,
        },
        'note': (
            'Медиаряды нормированы делением на среднее, контроли – вычитанием среднего и делением '
            'на разброс, KPI – вычитанием среднего и делением на разброс. '
            'media_means – это средние ряда ПОСЛЕ переноса с фиксированным коэффициентом 0,5, '
            'то есть масштаб входного медиаряда, а не средние трат канала. Точкой нормировки '
            'насыщения они НЕ являются: там делитель – среднее ряда переноса, вычисляемое внутри '
            'модели на каждой выборке (см. specification.saturation). Сравнивать media_means '
            'с channels[*].adstock_mean_posterior нельзя – у этих чисел разные основания, '
            'и меньшее значение переноса тут не противоречие.'
        ),
    }


def _приоры(модель, конфиг, нормировка, нет) -> Dict[str, Any]:
    """Приорные предположения. В модели записана лишь часть – остальное честно помечено.

    Полная спецификация приоров (сигмы коэффициентов, форма приоров насыщения,
    приор шума наблюдения) в файле модели не сохраняется. Значения из реестра KPI
    даём отдельным блоком со статусом «справочно»: без них байесовскую модель не
    воспроизвести, но выдавать их за запись обучения нельзя – реестр с тех пор мог
    измениться.
    """
    блок: Dict[str, Any] = {}

    приорные_средние = [_как_число(v) for v in (нормировка.get('control_prior_mus') or [])]
    столбцы = _как_список_строк(конфиг.get('control_columns'))
    if приорные_средние and len(приорные_средние) == len(столбцы):
        блок['control_prior_means'] = dict(zip(столбцы, приорные_средние))
        блок['control_prior_means_origin'] = ЗАПИСАНО
    else:
        блок['control_prior_means'] = None
        блок['control_prior_means_origin'] = НЕ_ЗАПИСАНО
        if столбцы:
            нет('priors.control_prior_means', 'приорные средние контролей в модели не записаны')

    иерархические = модель.get('hierarchical_priors')
    if isinstance(иерархические, dict) and иерархические:
        блок['hierarchical_posterior_means'] = _числовой_словарь(иерархические)
        блок['hierarchical_posterior_means_origin'] = ЗАПИСАНО
        блок['hierarchical_posterior_means_note'] = (
            'апостериорные средние групповых гиперпараметров переноса (бренд / отклик / смешанный), '
            'а не приоры'
        )
    else:
        блок['hierarchical_posterior_means'] = None
        блок['hierarchical_posterior_means_origin'] = НЕ_ЗАПИСАНО
        нет(
            'priors.hierarchical_posterior_means',
            'групповые гиперпараметры переноса не записаны – модель обучена без иерархии по группам',
        )

    знаковые = модель.get('signed_factor_priors_used')
    if isinstance(знаковые, dict) and знаковые:
        блок['signed_factor_priors'] = знаковые
        блок['signed_factor_priors_origin'] = ЗАПИСАНО
    else:
        блок['signed_factor_priors'] = None
        блок['signed_factor_priors_origin'] = НЕ_ЗАПИСАНО
        нет(
            'priors.signed_factor_priors',
            'подробная запись применённых приоров знаковых факторов в модели пуста',
            'приорные средние по каждому контролю – priors.control_prior_means',
        )

    # Справочный блок из реестра KPI. Помечен reference намеренно.
    kpi_type = _как_строку(модель.get('kpi_type'))
    справка: Optional[Dict[str, Any]] = None
    настройка = None
    if kpi_type:
        try:
            from utils.kpi_registry import get_kpi_config
            настройка = get_kpi_config(kpi_type)
            справка = {
                'beta_sigma_brand': _как_число(getattr(настройка, 'brand_beta_sigma', None)),
                'beta_sigma_performance': _как_число(getattr(настройка, 'perf_beta_sigma', None)),
                'beta_sigma_mixed': _как_число(getattr(настройка, 'mixed_beta_sigma', None)),
                'hill_gamma_beta_distribution': [
                    _как_число(getattr(настройка, 'gammas_alpha', None)),
                    _как_число(getattr(настройка, 'gammas_beta', None)),
                ],
                'decay_mu_logit_brand': list(getattr(настройка, 'brand_mu_logit_prior', ()) or ()),
                'decay_mu_logit_performance': list(getattr(настройка, 'perf_mu_logit_prior', ()) or ()),
                'decay_mu_logit_mixed': list(getattr(настройка, 'mixed_mu_logit_prior', ()) or ()),
                'observation_sigma': _как_число(getattr(настройка, 'obs_sigma_prior', None)),
            }
        except Exception as ошибка:  # noqa: BLE001
            logger.warning('Справочные приоры реестра KPI не прочитаны: %s', ошибка)

    блок['registry_reference'] = справка
    блок['registry_reference_origin'] = СПРАВОЧНО if справка else НЕ_ЗАПИСАНО
    блок['registry_reference_note'] = (
        'Значения взяты из реестра KPI кода продукта на момент выгрузки, а НЕ из файла модели: '
        'спецификация приоров при обучении не сохраняется. Если реестр менялся после обучения, '
        'эти значения могут отличаться от применявшихся. Куда именно каждое из них подставляется '
        'и применялось ли оно к этой модели – см. specification_from_code.'
    )

    # Полная спецификация приоров: семейство распределения и его аргументы по
    # каждой величине, с указанием ветви кода и того, применялась ли она здесь.
    из_кода = _приоры_из_кода(модель, конфиг, настройка)
    блок['specification_from_code'] = из_кода
    if из_кода is None:
        блок['specification_from_code_origin'] = НЕ_ЗАПИСАНО
        нет(
            'priors.specification_from_code',
            'спецификацию приоров не удалось прочитать из кода сборки модели (исходник недоступен '
            'или не разобран)',
            'engines/modeler.py – сборка модели PyMC',
        )
    else:
        блок['specification_from_code_origin'] = СПРАВОЧНО

    нет(
        'priors.specification_at_training',
        'полная спецификация приоров (сигмы коэффициентов, приоры насыщения и шума) при обучении '
        'в модель не записывается – семейства и параметры ниже прочитаны из кода продукта',
        'priors.specification_from_code – разбор engines/modeler.py на момент выгрузки; '
        'числа реестра – utils/kpi_registry.py',
    )

    return блок


def _сэмплирование(модель, выборки, нет) -> Dict[str, Any]:
    """Параметры прогонки цепей и апостериорные средние гиперпараметров переноса."""
    цепи = _как_число(выборки.get('n_chains'))
    выборок = _как_число(выборки.get('n_draws'))
    if цепи is None or выборок is None:
        нет(
            'sampling.n_chains / n_draws',
            'число цепей и выборок в модели не записано',
            'диагностика прогона: results/model-diagnostics.json',
        )
    среднее_логит = _как_число(выборки.get('adstock_mu_logit_mean'))
    разброс_логит = _как_число(выборки.get('adstock_sigma_logit_mean'))

    # Прогрев записан в паспорте воспроизводимости модели, а в этом блоке его
    # не было вовсе – читатель видел число выборок без числа шагов настройки.
    паспорт = модель.get('reproducibility') if isinstance(модель.get('reproducibility'), dict) else {}
    прогон = паспорт.get('mcmc') if isinstance(паспорт.get('mcmc'), dict) else {}
    прогрев = _как_целое(прогон.get('tune'))
    if прогрев is None:
        нет(
            'sampling.n_tune',
            'число шагов прогрева в модели не записано (паспорт воспроизводимости появился позже '
            'обучения)',
            'диагностика прогона: results/model-diagnostics.json, раздел metrics.mcmc.tune',
        )

    блок = {
        'n_chains': int(цепи) if цепи is not None else None,
        'n_draws_per_chain': int(выборок) if выборок is not None else None,
        'n_samples_total': (
            int(цепи * выборок) if цепи is not None and выборок is not None else None
        ),
        'n_tune': прогрев,
        'decay_hyper_mu_logit_posterior_mean': среднее_логит,
        'decay_hyper_sigma_logit_posterior_mean': разброс_логит,
        'origin': {
            'n_chains': ЗАПИСАНО if цепи is not None else НЕ_ЗАПИСАНО,
            'n_draws_per_chain': ЗАПИСАНО if выборок is not None else НЕ_ЗАПИСАНО,
            'n_samples_total': РАССЧИТАНО if цепи is not None and выборок is not None else НЕ_ЗАПИСАНО,
            'n_tune': ЗАПИСАНО if прогрев is not None else НЕ_ЗАПИСАНО,
            'decay_hyper_mu_logit_posterior_mean': ЗАПИСАНО if среднее_логит is not None else НЕ_ЗАПИСАНО,
            'decay_hyper_sigma_logit_posterior_mean': (
                ЗАПИСАНО if разброс_логит is not None else НЕ_ЗАПИСАНО
            ),
        },
        'note': (
            'Гиперпараметры переноса даны в логит-шкале: откат канала = сигмоида(mu + sigma · z). '
            'Это апостериорные средние, а не приоры.'
        ),
    }

    настройки = _настройки_сэмплера_из_кода(модель)
    блок['settings_from_code'] = настройки
    if настройки is None:
        блок['settings_from_code_origin'] = НЕ_ЗАПИСАНО
        нет(
            'sampling.settings_from_code',
            'настройки сэмплера не удалось прочитать из кода обучения (исходник недоступен или '
            'не разобран)',
            'engines/modeler.py – вызовы pm.sample',
        )
    else:
        блок['settings_from_code_origin'] = СПРАВОЧНО
        не_переданы = next(
            (в['not_passed'] for в in настройки['calls'] if в.get('applies_to_this_model')), None
        )
        for имя_настройки in (не_переданы or ()):
            нет(
                f'sampling.{имя_настройки}',
                'эту настройку сэмплера код обучения не передаёт – действует значение по умолчанию '
                'библиотеки той версии, что указана в разделе воспроизводимости; побитового '
                'повторения одно зерно поэтому не гарантирует',
                'sampling.settings_from_code – аргументы фактического вызова сэмплера',
            )
    return блок


def _диагностика(diagnostics, нет) -> Dict[str, Any]:
    """Диагностика прогона. В модели её нет – приезжает отдельным файлом.

    Имена полей взяты из реального содержимого `results/model-diagnostics.json`
    (проверено на живых проектах): метрики подгонки и сходимости лежат в разделе
    `metrics`, оценка качества – в `mqs`. Словесный вердикт в выгрузку намеренно
    не переносится: он написан для экрана продукта и содержит формулировки,
    запрещённые в клиентском тексте байесовской модели (INV-50).
    """
    if not isinstance(diagnostics, dict) or not diagnostics:
        нет(
            'diagnostics',
            'диагностика в файле модели не хранится и при выгрузке не передана',
            'единый источник для чтения – results/model-diagnostics.json проекта',
        )
        return {
            'available': False,
            'origin': НЕ_ЗАПИСАНО,
            'where_to_find': 'results/model-diagnostics.json проекта',
        }

    метрики = diagnostics.get('metrics') if isinstance(diagnostics.get('metrics'), dict) else {}
    прогон = метрики.get('mcmc') if isinstance(метрики.get('mcmc'), dict) else {}

    блок: Dict[str, Any] = {
        'available': True,
        'origin': ЗАПИСАНО,
        'source': 'results/model-diagnostics.json проекта',
        'fit': {
            'r_squared': _как_число(метрики.get('r_squared')),
            'mape_pct': _как_число(метрики.get('mape_pct')),
            'rmse': _как_число(метрики.get('rmse')),
        },
        'convergence': {
            'r_hat_max': _как_число(метрики.get('r_hat_max')),
            'divergences': _как_целое(метрики.get('divergences')),
            'ess_bulk_min': _как_число(метрики.get('ess_bulk_min')),
            'ess_tail_min': _как_число(метрики.get('ess_tail_min')),
            'bfmi_min': _как_число(метрики.get('bfmi_min')),
        },
        'data_volume': {
            'n_observations': _как_целое(метрики.get('n_observations')),
            'n_parameters': _как_целое(метрики.get('n_parameters')),
            'effective_parameters': _как_число(метрики.get('effective_parameters')),
            'observations_per_parameter': _как_число(метрики.get('ratio')),
        },
        'mcmc_run': {
            'chains': _как_целое(прогон.get('chains')),
            'draws_per_chain': _как_целое(прогон.get('draws')),
            'tune': _как_целое(прогон.get('tune')),
            'target_accept': _как_число(прогон.get('target_accept')),
        },
        'model_fingerprint': _как_строку(diagnostics.get('model_fingerprint')),
        'holidays_excluded': (
            bool(diagnostics.get('holidays_excluded'))
            if isinstance(diagnostics.get('holidays_excluded'), bool) else None
        ),
        'per_param_r_hat': _числовой_словарь(diagnostics.get('per_param_rhat')),
        'note': (
            'Раздел заполняется из файла диагностики проекта, а не из файла модели. '
            'Словесный вердикт продукта сюда не переносится – он предназначен для экрана.'
        ),
    }

    оценка = diagnostics.get('mqs')
    if isinstance(оценка, dict) and оценка:
        блок['quality'] = {
            'score': _как_число(оценка.get('score')),
            'raw_score': _как_число(оценка.get('raw_score')),
            'tier': _как_строку(оценка.get('tier')),
            'tier_label': _как_строку(оценка.get('tier_label')),
        }
    else:
        блок['quality'] = None
        нет('diagnostics.quality', 'оценка качества модели в файле диагностики отсутствует')

    if блок['model_fingerprint'] is None:
        нет(
            'diagnostics.model_fingerprint',
            'опознаватель модели в файле диагностики не записан (появился позже обучения)',
            'контрольная сумма файла модели: latest.pkl.sha256 в каталоге моделей проекта',
        )

    return блок


def _скалярный_словарь(значение: Any, глубина: int = 2) -> Any:
    """Копия словаря/списка с сохранением вложенности до заданной глубины.

    Прежний копир паспорта брал из вложенного словаря только скаляры – и
    отпечаток данных, у которого содержимое лежит на два уровня ниже
    (`data_fingerprint.content.content_sha256`), выходил в документ ПУСТЫМ
    объектом. Поле называлось «воспроизводимость», а проверить по нему было
    нечего. Ограничение глубины оставлено намеренно: паспорт не должен
    затягивать в документ произвольно глубокие структуры.
    """
    if isinstance(значение, (str, int, float, bool)) or значение is None:
        return значение
    if глубина <= 0:
        return None
    if isinstance(значение, dict):
        результат = {}
        for ключ, вложенное in значение.items():
            приведённое = _скалярный_словарь(вложенное, глубина - 1)
            if приведённое is not None or вложенное is None:
                результат[str(ключ)] = приведённое
        return результат
    if isinstance(значение, (list, tuple)):
        return [_скалярный_словарь(элемент, глубина - 1) for элемент in значение]
    return None


def _воспроизводимость(модель, нет) -> Dict[str, Any]:
    """Паспорт воспроизводимости: зерно, версии, отпечаток данных."""
    паспорт = модель.get('reproducibility')
    if not isinstance(паспорт, dict) or not паспорт:
        нет(
            'reproducibility',
            'паспорт воспроизводимости (зерно генератора, версии библиотек, отпечаток данных) '
            'в модели не записан – поле появилось в схеме позже обучения',
            'у моделей, обученных после появления поля, он лежит в разделе reproducibility',
        )
        return {'available': False, 'origin': НЕ_ЗАПИСАНО}

    блок: Dict[str, Any] = {'available': True, 'origin': ЗАПИСАНО}
    for ключ, значение in паспорт.items():
        блок[str(ключ)] = _скалярный_словарь(значение)

    отпечаток = блок.get('data_fingerprint')
    if isinstance(отпечаток, dict) and отпечаток:
        try:
            from utils.data_fingerprint import describe_frame_algorithm
            блок['data_fingerprint_algorithm'] = describe_frame_algorithm()
            блок['data_fingerprint_algorithm_origin'] = СПРАВОЧНО
        except ImportError as ошибка:
            logger.warning('Правила отпечатка таблицы при выгрузке не прочитаны: %s', ошибка)
            нет(
                'reproducibility.data_fingerprint_algorithm',
                'правила канонизации таблицы не прочитаны – модуль отпечатка недоступен',
                'utils/data_fingerprint.py – describe_frame_algorithm',
            )
    else:
        блок['data_fingerprint_algorithm'] = None
        нет(
            'reproducibility.data_fingerprint',
            'отпечаток исходных данных в паспорте модели не записан – поле появилось в схеме '
            'позже обучения',
        )
    return блок


def export_model_params_to_file(
    model_data: Dict[str, Any],
    output_path: Path,
    pretty: bool = True,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Path:
    """Записать выгрузку параметров в файл.

    Args:
        model_data: загруженная модель.
        output_path: куда сохранить JSON.
        pretty: отступы для чтения человеком.
        diagnostics: необязательное содержимое results/model-diagnostics.json.

    Returns:
        Путь записанного файла.
    """
    json_str = export_model_params_json(model_data, pretty=pretty, diagnostics=diagnostics)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json_str, encoding='utf-8')
    return output_path
