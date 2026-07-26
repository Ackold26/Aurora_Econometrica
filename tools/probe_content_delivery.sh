#!/usr/bin/env bash
# Зонд облачной доставки снаружи — приёмка функции `content` после выкладки.
#
# Зачем: деплою верить на слово нельзя. Разбор отказа у клиента 26.07.2026
# показал, что расхождение между «функция задеплоена» и «файл доезжает» стоит
# двух недель простоя. Зонд ходит по тому же адресу, что и клиент, с теми же
# параметрами, и проверяет ровно то, от чего зависит докачка по частям.
#
# Запуск:  bash tools/probe_content_delivery.sh [fingerprint_hash]
# Секреты: ~/.secrets/supabase_aurora.env (SUPABASE_URL)
set -u

FP="${1:-493288e1961cca7a6902a77aefc98ce904cc745c01d66fd8cda0ab5528efce72}"
PRODUCT="${PRODUCT:-econometrica}"
VERSION="${VERSION:-c3}"
FILE="${FILE:-econometrist.vault}"

set -a; . ~/.secrets/supabase_aurora.env; set +a
BASE="$SUPABASE_URL/functions/v1/content"
U="$BASE?fingerprint_hash=$FP&product=$PRODUCT&version=$VERSION&file=$FILE"

fail=0
ok()   { echo "  ок    $1"; }
bad()  { echo "  ПРОВАЛ $1"; fail=$((fail+1)); }
have() { grep -qi "$1" "$2" && ok "$3" || bad "$3 (в ответе нет: $1)"; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "1. Запрос целиком: длина обязана быть явной, порционной передачи быть не должно"
curl -s -D "$tmp/h1" -o "$tmp/full.bin" "$U"
grep -qiE "^HTTP/[0-9.]+ 200" "$tmp/h1" && ok "код 200" || bad "код не 200"
have "^content-length:" "$tmp/h1" "длина объявлена"
have "^accept-ranges: *bytes" "$tmp/h1" "докачка по частям объявлена"
if grep -qi "^transfer-encoding: *chunked" "$tmp/h1"; then
  bad "передача всё ещё порционная — это и есть лечимый дефект"
else
  ok "порционной передачи нет"
fi
SIZE=$(wc -c < "$tmp/full.bin" | tr -d ' ')
DECL=$(grep -i "^content-length:" "$tmp/h1" | tail -1 | tr -dc '0-9')
[ "$SIZE" = "$DECL" ] && ok "объявленная длина совпала с полученной ($SIZE)" \
                      || bad "объявлено $DECL, получено $SIZE"

echo "2. Запрос части: 206 с внятными границами"
curl -s -D "$tmp/h2" -o "$tmp/part.bin" -H "Range: bytes=0-1023" "$U"
grep -qiE "^HTTP/[0-9.]+ 206" "$tmp/h2" && ok "код 206" || bad "код не 206 — часть не поддержана"
grep -qi "^content-range: *bytes 0-1023/$SIZE" "$tmp/h2" \
  && ok "границы куска: bytes 0-1023/$SIZE" || bad "нет внятного Content-Range"
[ "$(wc -c < "$tmp/part.bin" | tr -d ' ')" = "1024" ] \
  && ok "получено ровно 1024 байта" || bad "размер куска не 1024"

echo "3. Невыполнимый диапазон: 416 с полным размером"
code=$(curl -s -o /dev/null -D "$tmp/h3" -w "%{http_code}" -H "Range: bytes=$SIZE-" "$U")
[ "$code" = "416" ] && ok "код 416" || bad "на диапазон за концом файла пришло $code"
grep -qi "content-range: *bytes \*/$SIZE" "$tmp/h3" \
  && ok "сообщён полный размер" || bad "416 без полного размера"

echo "4. Сборка кусками по 2 КБ обязана дать тот же файл"
: > "$tmp/joined.bin"
off=0; chunks=0
while [ "$off" -lt "$SIZE" ]; do
  endb=$((off + 2047)); [ "$endb" -ge "$SIZE" ] && endb=$((SIZE - 1))
  curl -s -H "Range: bytes=$off-$endb" "$U" >> "$tmp/joined.bin" || break
  off=$((endb + 1)); chunks=$((chunks + 1))
done
h_full=$(sha256sum < "$tmp/full.bin" | cut -d' ' -f1)
h_join=$(sha256sum < "$tmp/joined.bin" | cut -d' ' -f1)
[ "$h_full" = "$h_join" ] && ok "$chunks кусков склеились в тот же файл ($h_join)" \
                          || bad "склейка разошлась с целым файлом"

echo "5. Отказы по существу не сломаны"
code=$(curl -s -o "$tmp/denied.json" -w "%{http_code}" \
  "$BASE?fingerprint_hash=0000000000000000000000000000000000000000000000000000000000000000&product=$PRODUCT&version=$VERSION&file=$FILE")
[ "$code" = "403" ] && ok "чужой отпечаток — 403" || bad "на чужой отпечаток пришло $code"
grep -q "Лицензия" "$tmp/denied.json" \
  && ok "русский текст отказа читается (кодировка цела)" \
  || bad "текст отказа испорчен: $(cat "$tmp/denied.json")"
code=$(curl -s -o /dev/null -w "%{http_code}" \
  "$BASE?fingerprint_hash=$FP&product=$PRODUCT&version=$VERSION&file=no-such-file.vault")
[ "$code" = "404" ] && ok "несуществующий файл — 404" || bad "на несуществующий файл пришло $code"

echo
[ "$fail" -eq 0 ] && echo "Доставка проверена снаружи: замечаний нет." \
                  || echo "Замечаний: $fail — выкладку считать непринятой."
exit "$fail"
