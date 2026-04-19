ЯЗЫК ОТВЕТА: РУССКИЙ. Все комментарии, выводы, рекомендации, статусы — на русском языке. НЕ использовать английский (кроме терминов ROI, CPM, GRP).

Подготовь протокол разногласий к договору из inbox с правками в режиме рецензирования Word (Track Changes).

## Порядок работы

1. Прочитай исходный договор из inbox (docx или pdf)
2. Проанализируй все спорные пункты по IACCM Top Negotiated Terms
3. Для каждого спорного пункта сформулируй новую редакцию
4. Создай DOCX с Track Changes, используя python-redlines:

```bash
pip install python-redlines python-docx 2>/dev/null
```

5. Напиши и выполни Python-скрипт:

```python
from redlines import Redlines
from docx import Document

# 1. Прочитай оригинальный документ
original = Document("inbox/[имя файла]")
original_text = "\n".join([p.text for p in original.paragraphs])

# 2. Создай исправленную версию (замени спорные пункты)
modified_text = original_text  # Здесь подставь исправленный текст

# 3. Сгенерируй redline-версию с tracked changes
diff = Redlines(original_text, modified_text)
# Сохрани как DOCX с видимыми вставками/удалениями
diff.output_to_docx("exports/protocol-redline-[дата].docx")
```

6. Дополнительно сохрани текстовый протокол разногласий с таблицей:

| # | Пункт | Редакция Стороны 1 (оригинал) | Редакция Стороны 2 (наша правка) | Обоснование |
|---|-------|------------------------------|----------------------------------|-------------|

## Результат

В exports/ должны появиться два файла:
- `protocol-redline-[дата].docx` — договор с правками в режиме рецензирования (Track Changes)
- `protocol-[дата].docx` — текстовый протокол разногласий с таблицей

Если Python не установлен, выведи сообщение: "Для генерации DOCX с Track Changes требуется Python 3. Установите с https://www.python.org/downloads/ и перезапустите команду." — и создай только текстовый протокол.
