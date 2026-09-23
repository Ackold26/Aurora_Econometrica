import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function jsonResponse(data: Record<string, unknown>, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return jsonResponse({ status: "error", message: "Method not allowed" }, 405);
  }

  try {
    const { fingerprint_hash, instance_id } = await req.json();

    if (!fingerprint_hash || !instance_id) {
      return jsonResponse({ status: "error", message: "Missing fingerprint_hash or instance_id" }, 400);
    }

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    // 1. Найти лицензию.
    // fingerprint_hash общий для всех продуктов Aurora на одной машине, поэтому поиск
    // ТОЛЬКО по нему + .single() падал у клиентов с >1 лицензией (multi-product) → status=blocked.
    // Фикс: сначала по instance_id через activations (точная привязка к конкретной лицензии/продукту).
    // limit(1) + массив (НЕ .single()/.maybeSingle()) — устойчиво к дублям строк в activations.
    let license: { id: string; is_active: boolean; expires_at: string; product: string } | null = null;

    const { data: acts } = await supabase
      .from("activations")
      .select("license_id")
      .eq("instance_id", instance_id)
      .limit(1);

    if (acts && acts.length > 0) {
      const { data: lics } = await supabase
        .from("licenses")
        .select("id, is_active, expires_at, product")
        .eq("id", acts[0].license_id)
        .eq("is_active", true)
        .limit(1);
      license = lics && lics.length > 0 ? lics[0] : null;
    }

    // Fallback: активации ещё нет (heartbeat до первого auth) — первая активная лицензия по fingerprint.
    if (!license) {
      const { data: lics2 } = await supabase
        .from("licenses")
        .select("id, is_active, expires_at, product")
        .eq("fingerprint_hash", fingerprint_hash)
        .eq("is_active", true)
        .limit(1);
      license = lics2 && lics2.length > 0 ? lics2[0] : null;
    }

    if (!license) {
      return jsonResponse({ status: "blocked", message: "Лицензия не найдена" }, 403);
    }

    if (new Date(license.expires_at) < new Date()) {
      return jsonResponse({ status: "expired", message: "Лицензия истекла" }, 403);
    }

    // 2. Обновить last_seen
    const { error: updateError } = await supabase
      .from("activations")
      .update({ last_seen: new Date().toISOString() })
      .eq("license_id", license.id)
      .eq("instance_id", instance_id);

    if (updateError) {
      return jsonResponse({ status: "error", message: "Failed to update session" }, 500);
    }

    // 3. Проверить, есть ли обновление контента
    const { data: contentVer } = await supabase
      .from("content_versions")
      .select("version, app_min_version")
      .eq("product", license.product)
      .eq("is_current", true)
      .single();

    return jsonResponse({
      status: "ok",
      content_version: contentVer?.version || null,
      app_min_version: contentVer?.app_min_version || "0.3.2",
    });
  } catch (err) {
    return jsonResponse({ status: "error", message: "Internal server error" }, 500);
  }
});
