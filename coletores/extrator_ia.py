"""Lê a imagem de um folheto com o Claude e devolve produtos + preços.

Opcional: só funciona com o pacote `anthropic` instalado e uma credencial
(variável ANTHROPIC_API_KEY ou `ant auth login`).
"""
import json
import os

MODELO = os.environ.get("OFERTAS_MODELO", "claude-opus-5-5")

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
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "pacote 'anthropic' não instalado (pip install anthropic)"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_PROFILE")
            or os.path.isdir(os.path.expanduser("~/.config/anthropic"))):
        return False, "nenhuma credencial (defina ANTHROPIC_API_KEY)"
    return True, ""


def extrair(url_imagem):
    """Retorna lista de dicts {nome, preco, preco_de, condicao}."""
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
