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
import hashlib
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
from coletores.regioes import REGIOES  # noqa: E402
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

    # a região "sp" vem primeiro: os folhetos usam o Assaí mais perto do CEP dela
    regioes = {rid: dict(r) for rid, r in REGIOES.items()}
    regioes["sp"]["cep"] = os.environ.get("OFERTAS_CEP", "").strip() or regioes["sp"]["cep"]
    print("CEP SP:", regioes["sp"]["cep"])
    regioes["sp"]["local"] = app.definir_cep(regioes["sp"]["cep"], folhetos_em_segundo_plano=False)

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
    for rid, r in regioes.items():
        if rid != "sp":   # cada região coleta com o próprio CEP (sem apagar o que já foi coletado)
            r["local"] = app.definir_cep(r["cep"], folhetos_em_segundo_plano=False, limpar=False)
        r["regiao_lojas"] = json.loads(db.config("regiao", "{}") or "{}")   # ids de região/loja de cada rede para o CEP padrão
        print(f"Região {r['nome']} (CEP {r['cep']}):", ", ".join(r["online"]))
        for i, t in enumerate(termos, 1):
            for m, e in app.buscar_ao_vivo(t, n=40, regiao=rid).items():
                falhas.setdefault(m, []).append(e)
            if i % 40 == 0 or i == len(termos):
                print(f"  [{i}/{len(termos)}] termos coletados")
    for m, es in falhas.items():
        print(f"  ! {m}: {len(es)} falhas, ex.: {es[0]}")

    # leitura dos folhetos com IA, reaproveitando o que a execução anterior já leu
    cache_url = (os.environ.get("SITE_URL") or "").rstrip("/") + "/dados/folhetos-lidos.json"
    cache = (baixar_json(cache_url) if os.environ.get("SITE_URL") else None) or {}
    lidos = {}
    ia_ok = extrator_ia.disponivel()[0]
    novos = 0
    # a leitura com IA é a parte lenta e incerta da coleta: passado este tempo (contado do início),
    # o que falta fica para a próxima execução, em vez de estourar o limite do Actions e não publicar nada
    limite_ia = inicio + 60 * float(os.environ.get("OFERTAS_MINUTOS_IA") or 40)
    for f in intercalar_por_mercado(db.listar_folhetos()):
        img = f["imagem"]
        try:
            if img in cache:
                app.ler_folheto(img, itens=cache[img])
            elif ia_ok and time.time() > limite_ia:
                print("  Tempo da leitura com IA esgotado; os folhetos restantes ficam para a próxima coleta.")
                ia_ok = False
                continue
            elif ia_ok:
                app.ler_folheto(img)
                novos += 1
                print("  lido com IA:", img.rsplit("/", 1)[-1])
            else:
                continue
            lidos[img] = [{"nome": p["nome"], "preco": p["preco"], "preco_de": p["preco_de"], "condicao": p["extra"]}
                          for p in db.consultar(origem="folheto", limite=10**6) if p["fonte"] == img]
        except extrator_ia.CotaEsgotada:
            print("  Cota grátis da IA esgotada hoje; os folhetos restantes ficam para a próxima coleta.")
            ia_ok = False
        except Exception as e:
            print("  ! folheto", img.rsplit("/", 1)[-1], e)
    pendentes = len(db.listar_folhetos()) - len(lidos)
    print(f"Folhetos lidos: {len(lidos)} ({novos} novos hoje, {pendentes} pendentes)")

    # exporta
    os.makedirs(os.path.join(SAIDA, "dados"), exist_ok=True)
    for raiz, _, arqs in os.walk(SAIDA):   # limpa os arquivos da execução anterior (mantém as pastas)
        for a in arqs:
            os.remove(os.path.join(raiz, a))
    colunas = db.CAMPOS
    produtos = db.consultar(limite=10**7)
    gravar("produtos.json", {"colunas": colunas, "linhas": [[p[c] for c in colunas] for p in produtos]})
    folhetos = [f for f in db.listar_folhetos() if f["mercado"] != "Assaí"]
    capas_dos_pdfs(folhetos, os.path.join(SAIDA, "dados", "capas"))
    gravar("folhetos.json", folhetos)
    gravar("assai.json", assai)
    gravar("folhetos-lidos.json", lidos)
    # histórico: só o necessário para o gráfico e o veredito, sem inflar o site.
    # o publicado é lido de volta porque o Actions roda sem banco de histórico.
    hist_url = (os.environ.get("SITE_URL") or "").rstrip("/") + "/dados/historico.json"
    hist_anterior = (baixar_json(hist_url) if os.environ.get("SITE_URL") else None) or {}
    gravar("historico.json", exportar_historico(anteriores=hist_anterior))
    gravar("meta.json", {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "local": regioes["sp"]["local"], "regioes": regioes,
        "mercados_online": [n for n, _ in app.fontes()],
        "mercados_folheto": sorted({m for r in regioes.values() for m in r["folhetos"]}),
        "termos": len(termos), "falhas": {m: len(e) for m, e in falhas.items()},
        "proxy": os.environ.get("OFERTAS_PROXY", ""), "assai_lojas": assai_lojas,
    })
    # o site publicado também é um PWA: leva manifest, service worker e ícones
    for nome in ("index.html", "manifest.json", "sw.js", "icone-192.png", "icone-512.png"):
        origem = os.path.join(PASTA, "static", nome)
        if os.path.exists(origem):
            shutil.copy(origem, os.path.join(SAIDA, nome))
    print(f"Pronto: {len(produtos)} preços em {SAIDA} ({time.time() - inicio:.0f}s)")
    if not produtos:
        sys.exit("Nenhum preço coletado; não publicar.")


def _dia_num(x):
    """Dia como número (dias desde 1970). O formato antigo guardava segundos."""
    x = int(x)
    return x // 86400 if x > 10 ** 6 else x


def _expandir_serie(serie):
    """Série compacta -> {dia: preço}, um por dia. Entre dois pontos de mesmo preço, o preço valeu
    em todos os dias do meio."""
    dias, ant = {}, None
    for p in serie if isinstance(serie, list) else []:
        try:
            d, preco = _dia_num(p[0]), round(float(p[1]), 2)
        except (TypeError, ValueError, IndexError):
            continue
        if preco <= 0:
            continue
        if ant and ant[1] == preco and d > ant[0]:
            for k in range(ant[0] + 1, d):
                dias[k] = preco
        dias[d] = preco
        ant = (d, preco)
    return dias


def _comprimir_serie(dias):
    """{dia: preço} -> [[dia, preço], ...] só com o primeiro e o último dia de cada preço seguido."""
    out = []
    for d in sorted(dias):
        preco = dias[d]
        if len(out) >= 2 and out[-1][1] == preco and out[-2][1] == preco:
            out[-1][0] = d          # o preço continua o mesmo: só estica o fim
        else:
            out.append([d, preco])
    return out


def capas_dos_pdfs(folhetos, pasta, largura=480):
    """Folheto em PDF: desenha a primeira página para servir de capa no site (campo "capa").
    Usa o PyMuPDF; sem ele, ou se um PDF falhar, o site mostra o cartão sem imagem."""
    pdfs = [f for f in folhetos if f["imagem"].lower().endswith(".pdf")]
    if not pdfs:
        return 0
    try:
        import pymupdf
    except ImportError:
        print("  ! capas dos PDFs: PyMuPDF não instalado; os folhetos em PDF ficam sem capa")
        return 0
    os.makedirs(pasta, exist_ok=True)
    feitas = 0
    for f in pdfs:
        try:
            dados, _ = extrator_ia._baixar(f["imagem"])
            with pymupdf.open(stream=dados, filetype="pdf") as doc:
                pagina = doc[0]
                escala = largura / pagina.rect.width
                nome = hashlib.sha1(f["imagem"].encode()).hexdigest()[:12] + ".jpg"
                pagina.get_pixmap(matrix=pymupdf.Matrix(escala, escala)).save(os.path.join(pasta, nome), jpg_quality=72)
            f["capa"] = "dados/capas/" + nome
            feitas += 1
        except Exception as e:
            print(f"  ! capa de {f['titulo']}: {e}")
    print(f"Capas de PDF: {feitas} de {len(pdfs)}")
    return feitas


def exportar_historico(dias=90, max_produtos=100000, anteriores=None):
    """Histórico de todos os produtos para o site estático.

    Formato: {chave: [[dia, preco], ...]}, com `dia` em dias desde 1970. Para caber todo o catálogo
    (mais de 40 mil produtos), a série só guarda as MUDANÇAS: o primeiro e o último dia de cada
    preço seguido. Um produto que ficou 30 dias no mesmo preço ocupa 2 pontos, não 30. O site
    desfaz isso (expandirSerie) antes de desenhar o gráfico e de julgar a oferta.

    `anteriores` é o historico.json do site publicado. O GitHub Actions roda em máquina limpa, sem
    banco de histórico: cada execução só conhece o dia de hoje. Por isso os dias já publicados são
    SOMADOS aos do banco, produto a produto (no mesmo dia, vale o banco). O site publicado é, ele
    mesmo, o arquivo de longo prazo.
    """
    import calendar
    import historico as hist
    anteriores = anteriores if isinstance(anteriores, dict) else {}
    hoje_num = calendar.timegm(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")) // 86400
    corte = hoje_num - dias
    desde = time.strftime("%Y-%m-%d", time.localtime(time.time() - dias * 86400))

    banco = {}   # chave -> {dia: preco}
    try:
        hist.criar()
        with hist.conectar() as con:
            rows = con.execute("""
                SELECT mercado, nome, dia, MIN(preco) preco FROM precos
                WHERE dia >= ? GROUP BY mercado, nome, dia ORDER BY mercado, nome, dia
            """, (desde,)).fetchall()
        for r in rows:
            try:
                d = calendar.timegm(time.strptime(r["dia"], "%Y-%m-%d")) // 86400
            except ValueError:
                continue
            banco.setdefault(f"{r['mercado']}|{r['nome']}", {})[d] = round(r["preco"], 2)
    except Exception as e:   # noqa: BLE001
        print("  ! histórico indisponível:", e)

    # soma o publicado com o banco: o passado é preservado e o dia novo entra (ou corrige o mesmo dia)
    series, continuados = {}, 0
    for k in set(banco) | set(anteriores):
        pontos = {d: v for d, v in _expandir_serie(anteriores.get(k)).items() if d >= corte}
        if pontos and k in banco:
            continuados += 1
        pontos.update(banco.get(k, {}))
        if pontos:
            series[k] = pontos

    # teto de segurança: primeiro quem tem mais dias (a série não pode ser interrompida);
    # no empate, um de cada mercado por vez, para nenhuma rede ficar de fora
    if len(series) > max_produtos:
        por_mercado = {}
        for k in sorted(series, key=lambda k: (-len(series[k]), k)):
            por_mercado.setdefault(k.split("|", 1)[0], []).append(k)
        ordem, filas = [], list(por_mercado.values())
        while filas and len(ordem) < max_produtos:
            mais = max(len(series[f[0]]) for f in filas)
            for f in filas:
                if len(ordem) < max_produtos and len(series[f[0]]) == mais:
                    ordem.append(f.pop(0))
            filas = [f for f in filas if f]
        series = {k: series[k] for k in ordem}
    out = {k: _comprimir_serie(series[k]) for k in sorted(series)}
    if continuados:
        print(f"Histórico: {continuados} produtos continuam a série do site publicado")
    print(f"Histórico exportado: {len(out)} produtos, até {max((len(v) for v in series.values()), default=0)} dias por produto, "
          f"{sum(len(v) for v in out.values())} pontos guardados (de {sum(len(v) for v in series.values())} dias observados)")
    return out


def intercalar_por_mercado(folhetos):
    """Assaí, Max, Roldão, Assaí, Max, ...: com cota curta, cada rede recebe parte das leituras."""
    grupos = {}
    for f in folhetos:
        grupos.setdefault(f["mercado"], []).append(f)
    out = []
    while any(grupos.values()):
        for g in grupos.values():
            if g:
                out.append(g.pop(0))
    return out


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
