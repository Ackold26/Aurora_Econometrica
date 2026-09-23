import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, {
      headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type' }
    })
  }

  try {
    const { product } = await req.json()
    if (!product) {
      return new Response(JSON.stringify({ error: 'product required' }), { status: 400, headers: { 'Content-Type': 'application/json' } })
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    )

    const { data, error } = await supabase
      .from('app_versions')
      .select('version, download_url, checksum, release_notes, mandatory, min_version, signature')
      .eq('product', product)
      .single()

    if (error || !data) {
      return new Response(JSON.stringify({ error: 'product not found' }), { status: 404, headers: { 'Content-Type': 'application/json' } })
    }

    // SEC-3: always emit a string signature. Products without a signed row
    // return '' → their clients skip the update (fail-safe), unchanged behaviour.
    const body = { ...data, signature: data.signature ?? '' }
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  } catch (e) {
    return new Response(JSON.stringify({ error: 'invalid request' }), { status: 400, headers: { 'Content-Type': 'application/json' } })
  }
})
