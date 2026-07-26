import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, Range",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  // Без этого браузерный вызывающий не увидит длину и границы куска.
  "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
};

function jsonResponse(data: Record<string, unknown>, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

/** Включительные границы запрошенного куска. */
type RangeSpec = { start: number; end: number };

/**
 * Разобрать заголовок `Range` для единицы `bytes`.
 *
 * Возвращает:
 *  - `null` — заголовка нет, единица не байтовая, запрошено несколько
 *    диапазонов или синтаксис не распознан. Спецификация разрешает в таком
 *    случае просто отдать файл целиком, что и делаем;
 *  - `"invalid"` — синтаксис верен, но диапазон невыполним для этого файла
 *    (начало за последним байтом, пустой суффикс, перевёрнутые границы) →
 *    ответ 416;
 *  - `{start, end}` — включительные границы внутри файла; хвост за краем
 *    обрезается до последнего байта, как того требует спецификация.
 */
function parseRange(header: string | null, size: number): RangeSpec | "invalid" | null {
  if (!header) return null;

  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match) return null;

  const [, rawStart, rawEnd] = match;
  if (rawStart === "" && rawEnd === "") return null;

  let start: number;
  let end: number;

  if (rawStart === "") {
    // bytes=-N — последние N байт файла.
    const suffix = Number(rawEnd);
    if (!Number.isSafeInteger(suffix) || suffix <= 0) return "invalid";
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(rawStart);
    end = rawEnd === "" ? size - 1 : Number(rawEnd);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end)) return "invalid";
    if (end > size - 1) end = size - 1;
  }

  if (start > end || start >= size || start < 0) return "invalid";
  return { start, end };
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  if (req.method !== "GET") {
    return jsonResponse({ status: "error", message: "Method not allowed" }, 405);
  }

  try {
    const url = new URL(req.url);
    const fingerprint_hash = url.searchParams.get("fingerprint_hash");
    const product = url.searchParams.get("product");
    const version = url.searchParams.get("version");
    const file = url.searchParams.get("file");

    if (!fingerprint_hash || !product || !version || !file) {
      return jsonResponse(
        { status: "error", message: "Missing required params: fingerprint_hash, product, version, file" },
        400
      );
    }

    // Строгая проверка сегментов пути. Лицензия сверяется только по `product`,
    // а путь в хранилище склеивается из `product/version/file` — без этой
    // проверки `version=../<чужой-продукт>/<версия>` отдаёт материалы другого
    // продукта владельцу любой действующей лицензии: слой HTTP нормализует
    // `..` до обращения к хранилищу. Проверено боем 27.07.2026 — обход
    // возвращал 200 и файл целиком.
    const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
    const safeSegment = (v: string) => SEGMENT.test(v) && !v.includes("..");
    if (!safeSegment(product) || !safeSegment(version) || !safeSegment(file)) {
      return jsonResponse({ status: "error", message: "Invalid params" }, 400);
    }

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    // 1. Find license by fingerprint + product
    let query = supabase
      .from("licenses")
      .select("id, product, is_active, expires_at")
      .eq("fingerprint_hash", fingerprint_hash)
      .eq("is_active", true);

    // Filter by product if provided
    query = query.eq("product", product);

    const { data: licenses } = await query;
    const license = licenses && licenses.length > 0 ? licenses[0] : null;

    if (!license) {
      return jsonResponse({ status: "blocked", message: "Лицензия не найдена" }, 403);
    }

    if (new Date(license.expires_at) < new Date()) {
      return jsonResponse({ status: "blocked", message: "Лицензия истекла" }, 403);
    }

    // 2. Download file from Storage
    const storagePath = `${product}/${version}/${file}`;
    const { data: fileData, error: downloadError } = await supabase
      .storage
      .from("vaults")
      .download(storagePath);

    if (downloadError || !fileData) {
      return jsonResponse({ status: "error", message: "Файл не найден" }, 404);
    }

    // 3. Тело целиком в память. Через этот адрес ходят файлы кабинетов —
    // единицы и десятки килобайт, и хранилище всё равно отдаёт объект целиком,
    // так что нарезка куска в памяти ничего не удорожает. Отдавать байты, а не
    // Blob, принципиально: только так в ответе появляется явный Content-Length
    // и исчезает порционная передача, которую посредники у клиентов режут.
    const bytes = new Uint8Array(await fileData.arrayBuffer());
    const size = bytes.byteLength;

    const range = parseRange(req.headers.get("range"), size);
    const invalidRange = range === "invalid";

    // 4. Журнал доставки. Пишем только начальный запрос: при докачке кусками по
    // одному-два килобайта запись на каждый кусок раздула бы журнал в десятки
    // раз и сделала бы его непригодным для разбора отказов — а он нужен именно
    // для этого. Признак `ranged` показывает, что клиент качает по частям.
    if (!invalidRange && (range === null || range.start === 0)) {
      await supabase.from("audit_log").insert({
        event: "content_downloaded",
        license_id: license.id,
        details: { product, version, file, size, ranged: range !== null },
      });
    }

    if (invalidRange) {
      return new Response(null, {
        status: 416,
        headers: {
          "Content-Range": `bytes */${size}`,
          "Accept-Ranges": "bytes",
          ...corsHeaders,
        },
      });
    }

    const fileHeaders: Record<string, string> = {
      "Content-Type": "application/octet-stream",
      "Content-Disposition": `attachment; filename="${file}"`,
      "Accept-Ranges": "bytes",
      ...corsHeaders,
    };

    // 5. Кусок файла.
    if (range) {
      // Копия, а не подпредставление: тело ответа не должно зависеть от
      // разделяемого буфера.
      const chunk = bytes.slice(range.start, range.end + 1);
      return new Response(chunk, {
        status: 206,
        headers: {
          ...fileHeaders,
          "Content-Range": `bytes ${range.start}-${range.end}/${size}`,
          "Content-Length": String(chunk.byteLength),
        },
      });
    }

    // 6. Файл целиком.
    return new Response(bytes, {
      status: 200,
      headers: { ...fileHeaders, "Content-Length": String(size) },
    });
  } catch (err) {
    return jsonResponse({ status: "error", message: "Internal server error" }, 500);
  }
});
