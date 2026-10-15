// Proxy do Ofertas SP no Cloudflare Workers.
// O navegador não pode consultar as lojas direto (elas bloqueiam CORS); o site chama
//   https://<worker>/?url=<endereço da loja>
// e este worker repassa a requisição, só para os domínios da lista abaixo.

const PERMITIDOS = [
  "api.vendas.gpa.digital",          // Pão de Açúcar
  "api.tendaatacado.com.br",         // Tenda
  "www.sondadelivery.com.br",        // Sonda
  "www.atacadao.com.br", "www.samsclub.com.br", "www.mambo.com.br", "www.obahortifruti.com.br",
  "www.coopsupermercado.com.br", "www.savegnago.com.br", "www.zaffari.com.br", "www.swift.com.br",
  "www.assai.com.br",                // lojas e tabloides do Assaí
];

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36";

export default {
  async fetch(req, env, ctx) {
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
    const alvo = new URL(req.url).searchParams.get("url");
    let destino;
    try { destino = new URL(alvo); } catch { return erro(400, "parâmetro url inválido"); }
    if (destino.protocol !== "https:" || !PERMITIDOS.includes(destino.hostname)) return erro(403, "domínio não permitido");
    if (!["GET", "POST"].includes(req.method)) return erro(405, "método não permitido");

    // buscas GET iguais ficam 10 min no cache da Cloudflare
    const cache = caches.default;
    const chaveCache = new Request(req.url, { method: "GET" });
    if (req.method === "GET") {
      const salvo = await cache.match(chaveCache);
      if (salvo) return salvo;
    }

    const resp = await fetch(destino.toString(), {
      method: req.method,
      headers: {
        "User-Agent": UA,
        "Accept": "application/json, text/html;q=0.9",
        ...(req.method === "POST" ? { "Content-Type": req.headers.get("Content-Type") || "application/json" } : {}),
      },
      body: req.method === "POST" ? await req.text() : undefined,
      redirect: "follow",
    });
    const out = new Response(resp.body, {
      status: resp.status,
      headers: { ...CORS, "Content-Type": resp.headers.get("Content-Type") || "application/octet-stream", "Cache-Control": "public, max-age=600" },
    });
    if (req.method === "GET" && resp.ok) ctx.waitUntil(cache.put(chaveCache, out.clone()));
    return out;
  },
};

function erro(status, msg) {
  return new Response(JSON.stringify({ erro: msg }), { status, headers: { ...CORS, "Content-Type": "application/json" } });
}
