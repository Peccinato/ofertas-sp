/* Service worker do Ofertas SP.
 *
 * Objetivo: dentro do mercado, sem sinal, a lista e os últimos preços continuam abrindo.
 *
 * Estratégia por tipo de pedido:
 *   - a casca do app e os dados do dia: rede primeiro, guardado só quando não há conexão;
 *   - GET /api/...: rede primeiro, cache como rede de segurança (preço velho é melhor que tela vazia);
 *   - POST /api/...: se a rede falhar, entra numa fila e é reenviado quando a conexão volta.
 *
 * O que NÃO é guardado: nada de 11 MB de catálogo. O offline é a lista, os favoritos e o preço
 * desses itens — alguns KB, que é o que cabe e o que importa dentro da loja.
 */
const VERSAO = "ofertas-sp-v3";
const CASCA = ["./", "index.html", "manifest.json", "icone-192.png", "icone-512.png"];
const MAX_API = 60;          // quantas respostas de API guardar
const FILA_CHAVE = "ofertas-fila";

self.addEventListener("install", e => {
  e.waitUntil((async () => {
    const c = await caches.open(VERSAO);
    // addAll falha inteiro se um arquivo faltar; cada um por si é mais tolerante
    await Promise.all(CASCA.map(u => c.add(u).catch(() => {})));
    self.skipWaiting();
  })());
});

self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    const chaves = await caches.keys();
    await Promise.all(chaves.filter(k => k !== VERSAO).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

function ehApi(url) {
  return url.pathname.includes("/api/") || url.pathname.endsWith("/dados/meta.json");
}

self.addEventListener("fetch", e => {
  const req = e.request;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;   // lojas e CDNs seguem direto para a rede

  // POST: grava na fila se estiver offline (marcar item da lista dentro do mercado)
  if (req.method === "POST") {
    e.respondWith((async () => {
      try {
        return await fetch(req.clone());
      } catch {
        await enfileirar(req);
        return new Response(JSON.stringify({offline: true, fila: true}), {
          status: 202, headers: {"Content-Type": "application/json"},
        });
      }
    })());
    return;
  }

  if (req.method !== "GET") return;

  if (ehApi(url)) {
    e.respondWith((async () => {
      try {
        const r = await fetch(req);
        if (r.ok) guardarApi(req, r.clone());
        return r;
      } catch {
        const salvo = await caches.match(req);
        if (salvo) return salvo;
        return new Response(JSON.stringify({erro: "sem conexão", offline: true}), {
          status: 503, headers: {"Content-Type": "application/json"},
        });
      }
    })());
    return;
  }

  // casca do app e dados do dia: rede primeiro, para a versão e os preços novos aparecerem na hora;
  // o que está guardado só entra quando não há conexão (dentro do mercado, sem sinal).
  // Antes era "guardado primeiro": cada visita mostrava a página e os preços da visita anterior.
  e.respondWith((async () => {
    try {
      const r = await fetch(req);
      if (r.ok) caches.open(VERSAO).then(c => c.put(req, r.clone()));
      return r;
    } catch {
      const salvo = await caches.match(req);
      if (salvo) return salvo;
      const raiz = await caches.match("index.html");
      return raiz || new Response("Sem conexão", {status: 503, headers: {"Content-Type": "text/plain"}});
    }
  })());
});

async function guardarApi(req, resp) {
  const c = await caches.open(VERSAO);
  await c.put(req, resp);
  // poda: mantém as MAX_API respostas de API mais recentes
  const chaves = await c.keys();
  const apis = chaves.filter(k => ehApi(new URL(k.url)));
  if (apis.length > MAX_API) {
    for (const k of apis.slice(0, apis.length - MAX_API)) await c.delete(k);
  }
}

async function enfileirar(req) {
  const corpo = await req.clone().text();
  const fila = await lerFila();
  fila.push({url: req.url, method: req.method, corpo, quando: Date.now()});
  await gravarFila(fila);
  // pede ao navegador para tentar de novo quando a conexão voltar
  if (self.registration.sync) {
    try { await self.registration.sync.register("ofertas-sincronizar"); } catch {}
  }
}

async function lerFila() {
  try {
    const c = await caches.open(VERSAO);
    const r = await c.match("fila-interna");
    return r ? await r.json() : [];
  } catch { return []; }
}

async function gravarFila(fila) {
  const c = await caches.open(VERSAO);
  await c.put("fila-interna", new Response(JSON.stringify(fila), {
    headers: {"Content-Type": "application/json"},
  }));
}

async function drenarFila() {
  const fila = await lerFila();
  if (!fila.length) return;
  const restantes = [];
  for (const item of fila) {
    try {
      const r = await fetch(item.url, {
        method: item.method, headers: {"Content-Type": "application/json"}, body: item.corpo,
      });
      if (!r.ok) restantes.push(item);
    } catch {
      restantes.push(item);
    }
  }
  await gravarFila(restantes);
  if (restantes.length < fila.length) {
    const clientes = await self.clients.matchAll();
    for (const c of clientes) c.postMessage({tipo: "fila-enviada", enviados: fila.length - restantes.length});
  }
}

self.addEventListener("sync", e => {
  if (e.tag === "ofertas-sincronizar") e.waitUntil(drenarFila());
});

self.addEventListener("message", e => {
  if (e.data?.tipo === "drenar") e.waitUntil(drenarFila());
});
