"""B4-3 (2026-07-03): генератор линейных пиктограмм для отчётов (прототип).

Стайлгайд §«Иллюстрации»: единый строгий стиль — тонкие линии в фирменных
цветах (deep #1E293B, gold #C5A46D), прозрачный фон, 256×256. Прототип из
6 концептуальных пиктограмм; полная библиотека (несколько десятков) —
расширяется этим же скриптом или дизайнером в том же стиле.

Запуск: python tools/gen_report_icons.py
Выход:  sidecar/econometrica/aurora_pptx/assets/icons/*.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica' / 'aurora_pptx' / 'assets' / 'icons'
DEEP = (30, 41, 59, 255)      # deep-80 #1E293B
GOLD = (197, 164, 109, 255)   # gold #C5A46D
W = 8  # толщина линии (256px канва)


def _canvas():
    img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def icon_growth():
    """Рост: восходящая ломаная со стрелкой (секция «Декомпозиция/оптимизация»)."""
    img, d = _canvas()
    d.line([(28, 210), (100, 140), (150, 170), (224, 70)], fill=DEEP, width=W, joint='curve')
    d.polygon([(224, 70), (196, 74), (212, 98)], fill=GOLD)
    d.line([(28, 226), (228, 226)], fill=GOLD, width=4)
    return img


def icon_lens():
    """Лупа: методология и проверка."""
    img, d = _canvas()
    d.ellipse([56, 40, 176, 160], outline=DEEP, width=W)
    d.line([(160, 150), (216, 208)], fill=GOLD, width=W + 2)
    return img


def icon_db():
    """Данные: цилиндр БД."""
    img, d = _canvas()
    d.ellipse([60, 40, 196, 84], outline=DEEP, width=W)
    d.arc([60, 120, 196, 164], 0, 180, fill=DEEP, width=W)
    d.arc([60, 176, 196, 220], 0, 180, fill=GOLD, width=W)
    d.line([(60, 62), (60, 198)], fill=DEEP, width=W)
    d.line([(196, 62), (196, 198)], fill=DEEP, width=W)
    return img


def icon_book():
    """Книга: глоссарий и источники."""
    img, d = _canvas()
    d.line([(128, 60), (128, 204)], fill=GOLD, width=4)
    d.polygon([(40, 56), (128, 72), (128, 204), (40, 188)], outline=DEEP, width=W)
    d.polygon([(216, 56), (128, 72), (128, 204), (216, 188)], outline=DEEP, width=W)
    return img


def icon_balance():
    """Баланс: портфель каналов (равновесие)."""
    img, d = _canvas()
    d.line([(128, 48), (128, 200)], fill=DEEP, width=W)
    d.line([(48, 84), (208, 84)], fill=DEEP, width=W)
    d.arc([28, 96, 88, 156], 0, 180, fill=GOLD, width=W)
    d.arc([168, 96, 228, 156], 0, 180, fill=GOLD, width=W)
    d.line([(48, 84), (58, 126)], fill=DEEP, width=4)
    d.line([(208, 84), (198, 126)], fill=DEEP, width=4)
    d.line([(88, 200), (168, 200)], fill=DEEP, width=W)
    return img


def icon_compass():
    """Компас: рекомендации и направление."""
    img, d = _canvas()
    d.ellipse([44, 44, 212, 212], outline=DEEP, width=W)
    d.polygon([(128, 78), (150, 150), (128, 136), (106, 150)], fill=GOLD)
    return img


ICONS = {
    'growth': icon_growth,
    'lens': icon_lens,
    'db': icon_db,
    'book': icon_book,
    'balance': icon_balance,
    'compass': icon_compass,
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in ICONS.items():
        path = OUT / f'{name}.png'
        fn().save(path)
        print(f'  [OK] {path.name}')
    print(f'{len(ICONS)} пиктограмм → {OUT}')


if __name__ == '__main__':
    main()
