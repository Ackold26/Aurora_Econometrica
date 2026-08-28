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

// --- Наблюдаемость доставки (2026-08-28) ---------------------------------
//
// Дверь `/content` открывается знанием одного лишь отпечатка машины, и до сих
// пор в журнале не было видно, КТО забрал файл: событие `content_downloaded`
// несло только имя файла, продукт и версию. Отличить обычное обновление от
// вычерпывания всей истории (399 объектов, 9,64 МБ) было нечем. Ниже — только
// запись в журнал: ни одного отказа, ни одной задержки клиенту не добавляется.

/** Окно наблюдения, секунды. */
const BURST_WINDOW_SECS = 600;

/**
 * Порог всплеска — сколько РАЗЛИЧНЫХ файлов один отпечаток забрал за окно.
 *
 * Почему считаем различные файлы, а не обращения. Прогон по боевому журналу
 * (1687 событий `content_downloaded`, 31.03–17.08.2026, 12 отпечатков) показал:
 * законный клиент умеет повторять один и тот же файл десятками раз — 16.08 одна
 * машина сделала 253 обращения за 16 минут, но различных файлов в них было
 * всего 9 (244 повтора). По сырым обращениям порог 60 сработал бы 448 раз на
 * совершенно законной картине и утонул бы в шуме. По различным файлам
 * исторический максимум за 10 минут — 14.
 *
 * Почему именно 60:
 *  - исторический максимум 14 (запас более чем четырёхкратный);
 *  - худший мыслимый законный случай — машина со всеми лицензиями заново
 *    качает текущие версии всех 11 продуктов: 50 различных файлов, всё ещё
 *    ниже порога;
 *  - самая большая одна версия — 13 файлов, обычное обновление не приблизится;
 *  - вычерпывание истории (399 объектов) отмечается на 60-м файле.
 * На исторических данных порог не сработал бы ни разу.
 */
const BURST_DISTINCT_FILES = 60;

/**
 * Предел строк, вычитываемых из журнала за окно. Ограничивает и трафик, и
 * работу базы, если кто-то ломится в дверь: для перехода порога достаточно
 * увидеть 60 различных файлов, а берём мы самые свежие записи.
 */
const BURST_SCAN_LIMIT = 600;

/** Строка журнала за окно — ровно те поля, что нужны счётчику. */
type BurstRow = { event: string; p: string | null; v: string | null; f: string | null };

/** Ключ различимости: один и тот же файл одной версии считается один раз. */
function fileKey(product: string, version: string, file: string): string {
  return `${product}/${version}/${file}`;
}

/**
 * Сколько различных файлов набралось за окно и надо ли писать всплеск.
 *
 * Чистая функция: ввода-вывода нет, поэтому её поведение проверяемо отдельно.
 * `rows` — записи журнала этого отпечатка за окно (и скачивания, и уже
 * записанные всплески), `current` — файл, который отдаём прямо сейчас.
 * Повторный всплеск в том же окне не пишется: одна запись на окно, иначе на
 * длинном вычерпывании журнал залило бы сотнями одинаковых строк.
 */
function assessBurst(
  rows: BurstRow[],
  current: string,
  threshold: number
): { distinct: number; report: boolean } {
  const seen = new Set<string>([current]);
  let alreadyReported = false;
  for (const r of rows) {
    if (r.event === "content_burst") {
      alreadyReported = true;
      continue;
    }
    if (r.p && r.v && r.f) seen.add(fileKey(r.p, r.v, r.f));
  }
  return { distinct: seen.size, report: !alreadyReported && seen.size >= threshold };
}

/**
 * Первые 12 знаков отпечатка в нижнем регистре — метка машины для журнала.
 *
 * Целиком отпечаток в журнал не кладём: он же служит паролем к содержимому,
 * и запись его в общедоступную для служебного ключа таблицу удвоила бы число
 * мест, откуда его можно взять. Двенадцати знаков хватает с огромным запасом:
 * среди всех 12 отпечатков боевой базы усечения не совпадают ни разу, а по
 * самой метке восстановить отпечаток нельзя. Ничего сверх этого о машине
 * клиента не пишем (INV-38). Возвращает `null`, если отпечаток не похож на
 * шестнадцатеричный — тогда просто не считаем всплеск и не пишем метку.
 */
function shortFingerprint(fingerprint_hash: string): string | null {
  const head = fingerprint_hash.slice(0, 12);
  return /^[0-9a-fA-F]{12}$/.test(head) ? head.toLowerCase() : null;
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
      // 4а. Метка машины и счётчик всплеска. Считаем ровно там, где и без того
      // идём в журнал, — на начальном запросе файла: при докачке кусками ни
      // одного лишнего обращения к базе не появляется. Один запрос на файл
      // вместо прежних нуля; тело ответа при этом всё равно едет из хранилища,
      // и оно дороже. Весь блок обёрнут так, чтобы отказ журнала не мешал
      // выдаче: при любой ошибке счётчик просто молчит, а файл уходит клиенту.
      const fp12 = shortFingerprint(fingerprint_hash);
      let recentFiles: number | null = null;
      let burst: number | null = null;

      if (fp12) {
        try {
          const since = new Date(Date.now() - BURST_WINDOW_SECS * 1000).toISOString();
          const { data: recent, error: recentError } = await supabase
            .from("audit_log")
            .select("event, p:details->>product, v:details->>version, f:details->>file")
            .in("event", ["content_downloaded", "content_burst"])
            .eq("details->>fp12", fp12)
            .gte("created_at", since)
            .order("created_at", { ascending: false })
            .limit(BURST_SCAN_LIMIT);

          // Клиент не бросает исключений на сетевом сбое, а возвращает ошибку
          // объектом — проверено живым зондом. Считать по пустому ответу в этом
          // случае нельзя: поле `recent_files` тогда показало бы «забрал один
          // файл» там, где счётчик попросту не отработал. Молчим честно.
          if (!recentError) {
            const verdict = assessBurst(
              (recent ?? []) as unknown as BurstRow[],
              fileKey(product, version, file),
              BURST_DISTINCT_FILES
            );
            recentFiles = verdict.distinct;
            if (verdict.report) burst = verdict.distinct;
          }
        } catch {
          // Журнал недоступен — доставку это не касается.
          console.error("content: burst counter unavailable");
        }
      }

      await supabase.from("audit_log").insert({
        event: "content_downloaded",
        license_id: license.id,
        details: {
          product,
          version,
          file,
          size,
          ranged: range !== null,
          ...(fp12 ? { fp12 } : {}),
          ...(recentFiles !== null ? { recent_files: recentFiles } : {}),
        },
      });

      // 4б. Всплеск — отдельной строкой, чтобы его было видно без разбора всего
      // журнала. Ни отказа, ни задержки: к этому мгновению файл уже прочитан и
      // уходит клиенту тем же ответом, что и без всплеска.
      if (burst !== null) {
        try {
          await supabase.from("audit_log").insert({
            event: "content_burst",
            license_id: license.id,
            details: {
              fp12,
              product,
              distinct_files: burst,
              window_secs: BURST_WINDOW_SECS,
              threshold: BURST_DISTINCT_FILES,
            },
          });
        } catch {
          console.error("content: burst event not written");
        }
      }
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
