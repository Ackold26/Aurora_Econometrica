# -*- coding: utf-8 -*-
"""Встраивание TrueType-шрифтов в .pptx (OOXML), которого нет в python-pptx из коробки.

Портирован из Smart Analytica (Dev/ROSST_AI_Media/tools/creative/font_embed.py,
2026-06-07). Делает презентацию самодостаточной: PowerPoint у клиента рисует
встроенный шрифт, даже если он НЕ установлен в системе → пиксель-стабильная
вёрстка (закрывает класс «программа ≠ отчёт» из-за подстановки системного шрифта).

⚠️ ЛИЦЕНЗИОННЫЙ ГЕЙТ (важно для Econometrica): встраивать можно ТОЛЬКО шрифты с
разрешающей встраивание лицензией (OFL: Inter, Lora, Montserrat). Econometrica PPTX
СЕЙЧАС использует Georgia + Arial (builder.py:185-186) — это Microsoft-проприетарные
шрифты, встраивание/распространение которых ЗАПРЕЩЕНО. Поэтому:
  • core `embed_fonts(path, fonts)` встраивает РОВНО то, что ему передали (generic);
  • обёртка `embed_brand_fonts` имеет OFL-allowlist и ОТКАЗЫВАЕТ MS-проприетарным;
  • в `save()` билдера это НЕ вплетено — активировать имеет смысл только после
    перехода PPTX на OFL-шрифт (Inter/Lora, как уже сделано в HTML-отчёте,
    aurora_html/templates/fonts/*.woff2 → нужны .ttf-версии). Решение за продуктом.

API:
    embed_fonts(path, [{"typeface": "Inter", "regular": reg_ttf, "bold": bold_ttf}])
    embed_brand_fonts(path, ["Inter", "Lora"])   # с OFL-guard
"""
import os
import zipfile
from lxml import etree

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
FONT_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"
CT_NAME = "[Content_Types].xml"
RELS_NAME = "ppt/_rels/presentation.xml.rels"
PRES_NAME = "ppt/presentation.xml"

# Шрифты, чья лицензия РАЗРЕШАЕТ встраивание (SIL OFL и аналоги). Только их можно
# легально класть внутрь распространяемого .pptx. MS-проприетарные (Arial/Georgia/
# Calibri/Verdana/Tahoma) — НЕ здесь и будут отвергнуты обёрткой.
OFL_EMBEDDABLE = {"Inter", "Lora", "Montserrat", "Roboto", "OpenSans", "NotoSans"}


def _q(ns, tag):
    return "{%s}%s" % (ns, tag)


def _xml(b):
    return etree.tostring(b, xml_declaration=True, encoding="UTF-8", standalone=True)


def embed_fonts(pptx_path, fonts):
    """Встраивает шрифты в .pptx. fonts = [{"typeface", "regular": ttf, "bold": ttf}].

    Generic: встраивает ровно переданные файлы (вызывающий отвечает за лицензию).
    Возвращает True, если что-то встроено."""
    with zipfile.ZipFile(pptx_path, "r") as z:
        data = {n: z.read(n) for n in z.namelist()}

    idx = 1
    embed_map = []
    for f in fonts:
        entry = {"typeface": f["typeface"]}
        for weight in ("regular", "bold"):
            path = f.get(weight)
            if path and os.path.exists(path):
                part = "ppt/fonts/font%d.fntdata" % idx
                with open(path, "rb") as fh:
                    data[part] = fh.read()
                entry[weight] = part
                idx += 1
        embed_map.append(entry)
    if idx == 1:
        return False

    ct = etree.fromstring(data[CT_NAME])
    if not any(d.get("Extension") == "fntdata" for d in ct.findall(_q(CT_NS, "Default"))):
        d = etree.SubElement(ct, _q(CT_NS, "Default"))
        d.set("Extension", "fntdata")
        d.set("ContentType", "application/x-fontdata")
    data[CT_NAME] = _xml(ct)

    rels = etree.fromstring(data[RELS_NAME])
    maxn = 0
    for r in rels.findall(_q(REL_NS, "Relationship")):
        rid = r.get("Id") or ""
        if rid.startswith("rId"):
            try:
                maxn = max(maxn, int(rid[3:]))
            except ValueError:
                pass

    def add_rel(part):
        nonlocal maxn
        maxn += 1
        rid = "rId%d" % maxn
        r = etree.SubElement(rels, _q(REL_NS, "Relationship"))
        r.set("Id", rid)
        r.set("Type", FONT_REL_TYPE)
        r.set("Target", part.replace("ppt/", "", 1))
        return rid

    for entry in embed_map:
        for weight in ("regular", "bold"):
            if weight in entry:
                entry[weight + "_rid"] = add_rel(entry[weight])
    data[RELS_NAME] = _xml(rels)

    pres = etree.fromstring(data[PRES_NAME])
    pres.set("embedTrueTypeFonts", "1")
    pres.set("saveSubsetFonts", "0")
    lst = etree.Element(_q(P_NS, "embeddedFontLst"))
    for entry in embed_map:
        ef = etree.SubElement(lst, _q(P_NS, "embeddedFont"))
        fo = etree.SubElement(ef, _q(P_NS, "font"))
        fo.set("typeface", entry["typeface"])
        if "regular_rid" in entry:
            el = etree.SubElement(ef, _q(P_NS, "regular"))
            el.set(_q(R_NS, "id"), entry["regular_rid"])
        if "bold_rid" in entry:
            el = etree.SubElement(ef, _q(P_NS, "bold"))
            el.set(_q(R_NS, "id"), entry["bold_rid"])
    anchor = None
    for tag in ("notesSz", "sldSz", "sldIdLst"):
        el = pres.find(_q(P_NS, tag))
        if el is not None:
            anchor = el
            break
    if anchor is not None:
        anchor.addnext(lst)
    else:
        pres.append(lst)
    data[PRES_NAME] = _xml(pres)

    tmp = pptx_path + ".embed.tmp"
    order = [CT_NAME] + [n for n in data if n != CT_NAME]
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            z.writestr(n, data[n])
    os.replace(tmp, pptx_path)
    return True


def embed_brand_fonts(pptx_path, typefaces, *, strict=False):
    """Встраивает брендовые шрифты с OFL-guard. typefaces = ["Inter", "Lora", ...].

    Резолвит .ttf через text_metrics.font_path. ОТКАЗЫВАЕТ шрифтам вне OFL_EMBEDDABLE
    (MS-проприетарные) — возвращает их в списке skipped. strict=True → исключение
    при попытке встроить не-OFL шрифт. Возвращает {"embedded": [...], "skipped": [...],
    "missing": [...]}.
    """
    try:
        from . import text_metrics as TM
    except ImportError:
        import text_metrics as TM  # type: ignore

    fonts, skipped, missing = [], [], []
    for tf in typefaces:
        if tf not in OFL_EMBEDDABLE:
            if strict:
                raise ValueError(
                    f"Шрифт '{tf}' не в OFL-allowlist — встраивание запрещено лицензией. "
                    f"Econometrica использует Georgia/Arial (MS-проприетарные); для "
                    f"встраивания перейдите на OFL-шрифт (Inter/Lora)."
                )
            skipped.append(tf)
            continue
        reg = TM.font_path(tf, bold=False)
        bold = TM.font_path(tf, bold=True)
        if not reg:
            missing.append(tf)
            continue
        fonts.append({"typeface": tf, "regular": reg, "bold": bold})
    embedded = [f["typeface"] for f in fonts] if (fonts and embed_fonts(pptx_path, fonts)) else []
    return {"embedded": embedded, "skipped": skipped, "missing": missing}
