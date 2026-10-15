"""Gera a versão online (estática) do app: coleta tudo e grava em site/.

Roda todo dia no GitHub Actions (.github/workflows/publicar.yml), mas também funciona no PC:
    py gerar_site.py

Variáveis de ambiente (opcionais):
    OFERTAS_CEP        CEP usado para regionalizar os preços (padrão: centro de SP)
    SITE_URL           endereço do site publicado, para reaproveitar folhetos já lidos pela IA
    ANTHROPIC_API_KEY  liga a leitura de folhetos com IA
    OFERTAS_TERMOS     limita a cesta aos N primeiros termos (para testes rápidos)
    OFERTAS_PROXY      endereço do proxy (Cloudflare Worker) que permite busca ao vivo com qualquer CEP
    OFERTAS_SAIDA      pasta de saída (padrão: site/)
"""
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urljoin

PASTA = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.environ.get("OFERTAS_SAIDA") or os.path.join(PASTA, "site")
os.environ.setdefault("OFERTAS_DB", os.path.join(tempfile.gettempdir(), "ofertas-site.db"))

import app  # noqa: E402  (precisa do OFERTAS_DB definido antes)
import db  # noqa: E402
from coletores import extrator_ia, local  # noqa: E402
from coletores.folhetos import _data_br, _ofertas_assai  # noqa: E402

# a cesta do app + itens extras, para a busca online ter bastante coisa
CESTA_EXTRA = [
    "arroz integral", "arroz parboilizado", "feijão preto", "lentilha", "grão de bico", "milho verde", "ervilha",
    "sal", "vinagre", "maionese", "ketchup", "mostarda", "extrato de tomate", "creme de leite", "leite condensado",
    "leite em pó", "requeijão", "queijo prato", "peito de peru", "salsicha", "mortadela", "bacon", "hambúrguer",
    "nuggets", "peixe", "tilápia", "sardinha", "carne moída", "alcatra", "contrafilé", "costela", "coxa de frango",
    "peito de frango", "ovo", "pão francês", "torrada", "bolacha", "cereal matinal", "aveia", "granola",
    "café em cápsula", "chá", "açúcar mascavo", "adoçante", "mel", "geleia", "doce de leite", "sorvete",
    "pizza congelada", "lasanha", "batata palha", "salgadinho", "amendoim", "pipoca", "gelatina",
    "fermento", "amido de milho", "farofa", "tempero", "caldo", "macarrão instantâneo", "molho shoyu",
    "azeitona", "palmito", "cerveja lata", "cerveja long neck", "vinho", "vodka", "whisky", "energético",
    "água com gás", "refrigerante 2l", "suco de laranja", "isotônico", "leite fermentado",
    "maçã", "laranja", "limão", "mamão", "melancia", "uva", "abacate", "cebola", "alho", "cenoura",
    "batata doce", "alface", "brócolis", "pepino", "abobrinha",
    "sabonete", "desodorante", "condicionador", "papel toalha", "guardanapo", "saco de lixo", "esponja",
    "água sanitária", "limpador multiuso", "lava louças", "sabão líquido", "alvejante", "inseticida",
    "absorvente", "lenço umedecido", "escova de dente", "fio dental", "aparelho de barbear",
    "ração para cachorro", "ração para gato", "areia para gato", "pilha", "carvão",
]


def baixar_json(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ofertas-sp"}), timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def main():
    inicio = time.time()
    if os.path.exists(db.ARQUIVO):
        os.remove(db.ARQUIVO)
    db.criar()

    cep = os.environ.get("OFERTAS_CEP", "").strip() or "01310100"
    print("CEP:", cep)
    info = app.definir_cep(cep, folhetos_em_segundo_plano=False)
    print("  região:", info.get("endereco", {}).get("bairro"), "| Pão de Açúcar:", info.get("pao_de_acucar"))

    print("Folhetos...")
    erros = app.atualizar_folhetos()
    print("  ", len(db.listar_folhetos()), "páginas", erros or "")
    # tabloides de todas as lojas Assaí de SP: o site mostra os da loja mais perto do CEP de cada pessoa
    assai_lojas, assai = [], []
    try:
        assai_lojas = [{k: l[k] for k in ("nome", "id", "cidade", "lat", "lon")} for l in local.lojas_assai()]
        assai = tabloides_assai({l["id"] for l in assai_lojas})
        db.salvar_folhetos([{**f, "loja": "", "inicio": ""} for f in assai])   # entram na leitura com IA
        print("   Assaí SP:", len(assai_lojas), "lojas,", len(assai), "páginas")
    except Exception as e:
        print("  ! Assaí SP:", e)

    termos = list(dict.fromkeys(app.CESTA + CESTA_EXTRA))
    if os.environ.get("OFERTAS_TERMOS"):
        termos = termos[: int(os.environ["OFERTAS_TERMOS"])]
    falhas = {}
    for i, t in enumerate(termos, 1):
        for m, e in app.buscar_ao_vivo(t, n=40).items():
            falhas.setdefault(m, []).append(e)
        if i % 20 == 0 or i == len(termos):
            print(f"  [{i}/{len(termos)}] termos coletados")
    for m, es in falhas.items():
        print(f"  ! {m}: {len(es)} falhas, ex.: {es[0]}")

    # leitura dos folhetos com IA, reaproveitando o que a execução anterior já leu
    cache_url = (os.environ.get("SITE_URL") or "").rstrip("/") + "/dados/folhetos-lidos.json"
    cache = (baixar_json(cache_url) if os.environ.get("SITE_URL") else None) or {}
    lidos = {}
    ia_ok = extrator_ia.disponivel()[0]
    for f in db.listar_folhetos():
        img = f["imagem"]
        try:
            if img in cache:
                app.ler_folheto(img, itens=cache[img])
            elif ia_ok:
                app.ler_folheto(img)
                print("  lido com IA:", img.rsplit("/", 1)[-1])
            else:
                continue
            lidos[img] = [{"nome": p["nome"], "preco": p["preco"], "preco_de": p["preco_de"], "condicao": p["extra"]}
                          for p in db.consultar(origem="folheto", limite=10**6) if p["fonte"] == img]
        except Exception as e:
            print("  ! folheto", img.rsplit("/", 1)[-1], e)
    print("Folhetos lidos:", len(lidos), "(IA ligada)" if ia_ok else "(IA desligada; só reaproveitados)")

    # exporta
    os.makedirs(os.path.join(SAIDA, "dados"), exist_ok=True)
    for raiz, _, arqs in os.walk(SAIDA):   # limpa os arquivos da execução anterior (mantém as pastas)
        for a in arqs:
            os.remove(os.path.join(raiz, a))
    colunas = db.CAMPOS
    produtos = db.consultar(limite=10**7)
    gravar("produtos.json", {"colunas": colunas, "linhas": [[p[c] for c in colunas] for p in produtos]})
    gravar("folhetos.json", [f for f in db.listar_folhetos() if f["mercado"] != "Assaí"])
    gravar("assai.json", assai)
    gravar("folhetos-lidos.json", lidos)
    gravar("meta.json", {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "local": app.info_local(),
        "mercados_online": [n for n, _ in app.fontes()],
        "mercados_folheto": ["Assaí", "Roldão", "Akki", "Lopes", "Max Atacadista"],
        "termos": len(termos), "falhas": {m: len(e) for m, e in falhas.items()},
        "proxy": os.environ.get("OFERTAS_PROXY", ""), "assai_lojas": assai_lojas,
    })
    shutil.copy(os.path.join(PASTA, "static", "index.html"), os.path.join(SAIDA, "index.html"))
    print(f"Pronto: {len(produtos)} preços em {SAIDA} ({time.time() - inicio:.0f}s)")
    if not produtos:
        sys.exit("Nenhum preço coletado; não publicar.")


def tabloides_assai(lojas_ids):
    """Uma entrada por página de tabloide vigente, com as lojas (de SP) em que vale."""
    hoje = time.strftime("%Y-%m-%d")
    out = {}
    for o in _ofertas_assai():
        fim = _data_br(o.get("end_date"))
        if fim and fim.isoformat() < hoje:
            continue
        ids = sorted({int(l["loja_id"]) for l in o.get("lojas", [])} & lojas_ids)
        if not ids:
            continue
        for i, img in enumerate(o.get("images", []), 1):
            f = out.setdefault(urljoin("https://www.assai.com.br/", img["url"]), {"mercado": "Assaí", "titulo": o.get("title") or f"Tabloide {o.get('id_oferta')}",
                                            "pagina": i, "imagem": urljoin("https://www.assai.com.br/", img["url"]), "validade": o.get("custom_text", ""),
                                            "fim": fim.isoformat() if fim else "", "lojas": []})
            f["lojas"] = sorted(set(f["lojas"]) | set(ids))
    return list(out.values())


def gravar(nome, obj):
    with open(os.path.join(SAIDA, "dados", nome), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
