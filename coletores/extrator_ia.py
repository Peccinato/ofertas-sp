"""Lê a imagem de um folheto com IA e devolve produtos + preços.

Usa, nesta ordem, o que estiver configurado:
- Gemini (Google, tem plano grátis): variável GEMINI_API_KEY
- Claude (Anthropic, pago por uso): pacote `anthropic` + ANTHROPIC_API_KEY (ou `ant auth login`)
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

MODELO = os.environ.get("OFERTAS_MODELO", "claude-opus-5-5")
GEMINI_MODELO = os.environ.get("GEMINI_MODELO", "")   # vazio: escolhe sozinho o "flash" mais novo disponível

ESQUEMA = {
    "type": "object",
    "properties": {
        "produtos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string", "description": "Nome do produto com marca e tamanho, ex. 'Arroz Camil Tipo 1 5kg'"},
                    "preco": {"type": "number", "description": "Preço principal em reais"},
                    "preco_de": {"type": ["number", "null"], "description": "Preço antigo/riscado, se houver"},
                    "condicao": {"type": "string", "description": "Condição do preço: 'kg', 'cada', 'leve 3 pague 2', 'no cartão', 'a partir de 6 un' ou ''"},
                },
                "required": ["nome", "preco", "preco_de", "condicao"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["produtos"],
    "additionalProperties": False,
}

PROMPT = """Este é um folheto de ofertas de supermercado brasileiro (uma ou mais páginas).
Liste TODOS os produtos com preço visíveis. Para cada um:
- nome: descrição completa como aparece (marca, variedade, peso/volume). Não invente tamanhos que não aparecem.
- preco: o preço de venda em destaque (ex. "9,99" -> 9.99). Se houver dois preços (varejo e atacado, ou normal e no cartão), use o mais comum/sem condição como preco e descreva o outro em condicao.
- preco_de: preço "de"/riscado se existir, senão null.
- condicao: unidade ou regra (ex. "kg", "cada", "leve 3 pague 2", "no Cartão Passaí: R$ 8,99", "a partir de 6 un: R$ 4,49"), ou "".
Ignore textos legais, logotipos e itens sem preço."""


def disponivel():
    if os.environ.get("GEMINI_API_KEY"):
        return True, ""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "pacote 'anthropic' não instalado (pip install anthropic)"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_PROFILE")
            or os.path.isdir(os.path.expanduser("~/.config/anthropic"))):
        return False, "nenhuma chave de IA (defina GEMINI_API_KEY, grátis, ou ANTHROPIC_API_KEY)"
    return True, ""


def extrair(url_imagem):
    """Retorna lista de dicts {nome, preco, preco_de, condicao}."""
    if os.environ.get("GEMINI_API_KEY"):
        return _extrair_gemini(url_imagem)
    return _extrair_claude(url_imagem)


# esquema no formato do Gemini (subconjunto do OpenAPI: tipos em maiúsculas, "nullable")
_ESQUEMA_GEMINI = {
    "type": "OBJECT",
    "properties": {"produtos": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "nome": {"type": "STRING"}, "preco": {"type": "NUMBER"},
        "preco_de": {"type": "NUMBER", "nullable": True}, "condicao": {"type": "STRING"},
    }, "required": ["nome", "preco", "preco_de", "condicao"]}}},
    "required": ["produtos"],
}
_ultima_chamada = [0.0]


class CotaEsgotada(RuntimeError):
    """A cota grátis do dia acabou em todos os modelos: o resto fica para a próxima execução."""


_fila = []   # modelos a usar, em ordem; os que esgotam a cota do dia são removidos


def _modelos_gemini():
    """O Google aposenta modelos com frequência: pergunta à API quais existem.
    Usa o 'flash' estável mais novo e, quando a cota dele acaba, o 'flash-lite' (cota grátis maior)."""
    if _fila or GEMINI_MODELO:
        return _fila or [GEMINI_MODELO]
    nomes, pagina = [], ""
    while True:
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200" + (f"&pageToken={pagina}" if pagina else "")
        req = urllib.request.Request(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        nomes += [m["name"].split("/", 1)[1] for m in d.get("models", [])
                  if "generateContent" in m.get("supportedGenerationMethods", [])]
        pagina = d.get("nextPageToken")
        if not pagina:
            break
    for sufixo in ("flash", "flash-lite"):   # só versões estáveis (sem preview/exp/image)
        vs = [(float(m.group(1)), n) for n in nomes if (m := re.fullmatch(rf"gemini-(\d+(?:\.\d+)?)-{sufixo}", n))]
        if vs:
            _fila.append(max(vs)[1])
    if not _fila:
        raise RuntimeError(f"nenhum modelo Gemini flash disponível ({', '.join(nomes[:8])}...)")
    print("  Gemini: modelos", " -> ".join(_fila))
    return _fila


def _baixar(url):
    """Baixa a imagem; se o site bloquear (ex.: servidor no exterior), tenta pelo proxy do Cloudflare."""
    tentativas = [url]
    if os.environ.get("OFERTAS_PROXY"):
        tentativas.append(os.environ["OFERTAS_PROXY"].rstrip("/") + "/?url=" + urllib.parse.quote(url, safe=""))
    for i, u in enumerate(tentativas):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128 Safari/537.36"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read(), (r.headers.get_content_type() or "image/jpeg")
        except urllib.error.HTTPError:
            if i == len(tentativas) - 1:
                raise


def _extrair_gemini(url):
    dados, tipo = _baixar(url)
    if tipo in ("application/octet-stream", "text/plain"):
        tipo = "image/jpeg"
    if url.lower().endswith(".pdf"):
        tipo = "application/pdf"
    corpo = json.dumps({
        "contents": [{"parts": [{"inline_data": {"mime_type": tipo, "data": base64.b64encode(dados).decode()}},
                                {"text": PROMPT}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": _ESQUEMA_GEMINI, "temperature": 0},
    }).encode()
    d, tentativa = None, 0
    while d is None:
        fila = _modelos_gemini()
        if not fila:
            raise CotaEsgotada("cota grátis do Gemini esgotada hoje")
        modelo = fila[0]
        # o plano grátis também limita as chamadas por minuto: espaça as chamadas
        espera = 7 - (time.time() - _ultima_chamada[0])
        if espera > 0:
            time.sleep(espera)
        _ultima_chamada[0] = time.time()
        api = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        req = urllib.request.Request(api, data=corpo, headers={"Content-Type": "application/json",
                                                               "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            tentativa += 1
            if e.code == 429 and re.search(r"PerDay|per day", msg, re.I):
                print(f"  Gemini: cota do dia esgotada em {modelo}")
                fila.pop(0)                      # passa para o próximo modelo (ou para de vez)
                if not fila:
                    raise CotaEsgotada("cota grátis do Gemini esgotada hoje")
            elif e.code in (429, 500, 503) and tentativa <= 3:
                time.sleep(60 if e.code == 429 else 20 * tentativa)   # limite por minuto ou instabilidade
            else:
                raise RuntimeError(f"Gemini HTTP {e.code} ({modelo}): {msg[:200]}")
    cand = (d.get("candidates") or [{}])[0]
    if cand.get("finishReason") not in (None, "STOP"):
        raise RuntimeError(f"Gemini parou: {cand.get('finishReason')}")
    texto = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    return json.loads(texto)["produtos"]


def _extrair_claude(url_imagem):
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODELO,
        max_tokens=16000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA}},
        # se o modelo recusar, o servidor tenta automaticamente outro modelo
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "document" if url_imagem.lower().endswith(".pdf") else "image",
                 "source": {"type": "url", "url": url_imagem}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("o modelo recusou a imagem")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("resposta cortada (folheto grande demais)")
    texto = next(b.text for b in resp.content if b.type == "text")
    return json.loads(texto)["produtos"]
