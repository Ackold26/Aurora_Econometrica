ЯЗЫК ОТВЕТА: РУССКИЙ. Все комментарии, выводы, рекомендации, статусы — на русском языке. НЕ использовать английский (кроме терминов ROI, CPM, GRP).

Прочитай рекламный текст из inbox, исправь все юридические нарушения и сохрани результат с правками в режиме рецензирования Word (Track Changes).

## Порядок работы

1. Прочитай рекламный материал из inbox (docx или текст)
2. Проведи проверку по чек-листу /qa (38-ФЗ, ОРД, категорийные требования)
3. Исправь все выявленные нарушения прямо в тексте
4. Создай DOCX с Track Changes, используя python-redlines:

```bash
pip install python-redlines python-docx 2>/dev/null
```

5. Напиши и выполни Python-скрипт:

```python
from redlines import Redlines
from docx import Document

# 1. Прочитай оригинальный текст
original = Document("inbox/[имя файла]")
original_text = "\n".join([p.text for p in original.paragraphs])

# 2. Создай исправленную версию (с устранёнными нарушениями)
fixed_text = original_text  # Здесь подставь исправленный текст

# 3. Сгенерируй redline-версию
diff = Redlines(original_text, fixed_text)
diff.output_to_docx("exports/[оригинальное-имя]-redline.docx")
```

6. Также сохрани чистую исправленную версию (без разметки изменений):

```python
fixed_doc = Document()
for line in fixed_text.split("\n"):
    fixed_doc.add_paragraph(line)
fixed_doc.save("exports/[оригинальное-имя]-fixed.docx")
```

7. Приложи краткий список изменений с указанием нормы закона для каждого исправления:

| # | Было | Стало | Норма | Штраф |
|---|------|-------|-------|-------|

## Результат

В exports/ должны появиться:
- `[имя]-redline.docx` — оригинал с видимыми правками (Track Changes) — для согласования с командой
- `[имя]-fixed.docx` — чистая исправленная версия — для публикации
- Список изменений в чате

Если Python не установлен, выведи сообщение: "Для генерации DOCX с Track Changes требуется Python 3. Установите с https://www.python.org/downloads/ и перезапустите команду." — и создай только чистую исправленную версию через скил docx.
