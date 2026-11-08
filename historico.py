"""Histórico de preços: arquivo SQLite próprio, que sobrevive à regeração diária do banco de produtos.

Por que um arquivo separado: o `gerar_site.py` apaga o banco de produtos no começo de cada
execução (é um banco descartável, refeito do zero todo dia). Se o histórico morasse lá dentro,
ele morreria junto. Aqui ele fica em `historico.db`, fora do alcance dessa limpeza.

Uma linha por (dia, mercado, nome, origem). Rodar a coleta duas vezes no mesmo dia atualiza a
linha do dia em vez de duplicar, então o preço guardado é o último observado naquele dia.

Uso típico:
    import historico
    historico.criar()
    historico.registrar(produtos)          # lista de dicts com mercado/nome/preco/origem
    historico.resumo("Covabra", "Arroz Camil Tipo I 5kg")
"""
import os
import sqlite3
import statistics
import threading
import time

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.environ.get("OFERTAS_HIST") or os.path.join(PASTA, "historico.db")

_lock = threading.Lock()

# quantos dias de histórico guardar antes de podar (90 dias de gráfico + folga)
DIAS_GUARDADOS = int(os.environ.get("OFERTAS_HIST_DIAS") or "400")

# abaixo disso não dá para julgar se uma promoção é verdadeira
MIN_DIAS_JULGAR = 14


def conectar():
    con = sqlite3.connect(ARQUIVO, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def criar():
    os.makedirs(os.path.dirname(ARQUIVO) or ".", exist_ok=True)
    with conectar() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS precos (
            dia TEXT NOT NULL,
            mercado TEXT NOT NULL,
            nome TEXT NOT NULL,
            origem TEXT NOT NULL DEFAULT 'site',
            ean TEXT DEFAULT '',
            preco REAL NOT NULL,
            preco_de REAL,
            preco_unidade REAL,
            unidade TEXT DEFAULT '',
            PRIMARY KEY (dia, mercado, nome, origem)
        );
        CREATE INDEX IF NOT EXISTS ix_hist_nome ON precos(nome);
        CREATE INDEX IF NOT EXISTS ix_hist_ean ON precos(ean);
        CREATE INDEX IF NOT EXISTS ix_hist_dia ON precos(dia);
        """)
    return ARQUIVO


def hoje():
    """Dia local no formato AAAA-MM-DD (no servidor, rode com TZ=America/Sao_Paulo)."""
    return time.strftime("%Y-%m-%d")


def registrar(produtos, dia=None):
    """Grava o preço observado hoje. Aceita lista de dicts (o mesmo formato de db.salvar_produtos)."""
    dia = dia or hoje()
    linhas = []
    for p in produtos:
        preco = p.get("preco")
        if not preco or preco <= 0:
            continue
        nome = (p.get("nome") or "").strip()
        mercado = (p.get("mercado") or "").strip()
        if not nome or not mercado:
            continue
        linhas.append((
            dia, mercado, nome, p.get("origem") or "site", (p.get("ean") or "").strip(),
            float(preco), p.get("preco_de"), p.get("preco_unidade"), p.get("unidade") or "",
        ))
    if not linhas:
        return 0
    with _lock, conectar() as con:
        con.executemany("""
            INSERT INTO precos (dia, mercado, nome, origem, ean, preco, preco_de, preco_unidade, unidade)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (dia, mercado, nome, origem) DO UPDATE SET
                preco=excluded.preco, preco_de=excluded.preco_de,
                preco_unidade=excluded.preco_unidade, unidade=excluded.unidade,
                ean=CASE WHEN excluded.ean <> '' THEN excluded.ean ELSE precos.ean END
        """, linhas)
    return len(linhas)


def serie(mercado, nome, dias=90):
    """Série de preços de um produto num mercado: [{"dia": "2026-11-08", "preco": 17.9}, ...]."""
    desde = _desde(dias)
    with conectar() as con:
        rows = con.execute("""
            SELECT dia, MIN(preco) preco FROM precos
            WHERE mercado = ? AND nome = ? AND dia >= ?
            GROUP BY dia ORDER BY dia
        """, (mercado, nome, desde))
        return [{"dia": r["dia"], "preco": r["preco"]} for r in rows]


def serie_ean(ean, dias=90):
    """Série por código de barras: o mesmo produto em todos os mercados que informam EAN."""
    desde = _desde(dias)
    with conectar() as con:
        rows = con.execute("""
            SELECT dia, mercado, MIN(preco) preco FROM precos
            WHERE ean = ? AND ean <> '' AND dia >= ?
            GROUP BY dia, mercado ORDER BY dia
        """, (ean, desde))
        return [dict(r) for r in rows]


def _desde(dias):
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - dias * 86400))


def resumo(mercado, nome, dias=90):
    """Estatísticas do produto no período: mínimo, mediana, máximo, tendência e nº de dias observados."""
    s = serie(mercado, nome, dias)
    if not s:
        return {"dias": 0}
    precos = [x["preco"] for x in s]
    atual = precos[-1]
    mediana = statistics.median(precos)
    # tendência: média dos primeiros 7 dias contra os últimos 7 (só com massa suficiente)
    tendencia = None
    if len(precos) >= 14:
        ini = statistics.mean(precos[:7])
        fim = statistics.mean(precos[-7:])
        if ini > 0:
            tendencia = round(100 * (fim - ini) / ini, 1)
    return {
        "dias": len(precos),
        "atual": atual,
        "minimo": min(precos),
        "maximo": max(precos),
        "mediana": round(mediana, 2),
        "primeiro": precos[0],
        "tendencia_pct": tendencia,
        "serie": s,
    }


def avaliar_oferta(mercado, nome, preco, preco_de=None, dias=90):
    """A pergunta que importa: esse desconto é real?

    Compara o preço de hoje com a mediana do que o produto custou nos últimos `dias`.
    Devolve um veredito determinístico, com os números que o sustentam:

        boa          preço bem abaixo do normal (>= 15% abaixo da mediana)
        normal       preço na faixa de sempre
        inflada      o "de/por" é teatro: o preço "original" está acima do que ele custa normalmente
        sem_historico ainda não há dias suficientes para julgar
    """
    r = resumo(mercado, nome, dias)
    if r["dias"] < MIN_DIAS_JULGAR:
        return {"veredito": "sem_historico", "dias": r["dias"], "precisa": MIN_DIAS_JULGAR,
                "mediana": r.get("mediana"), "minimo": r.get("minimo")}
    mediana = r["mediana"]
    if not mediana:
        return {"veredito": "sem_historico", "dias": r["dias"]}

    desconto_real = round(100 * (1 - preco / mediana), 1) if mediana else 0
    out = {
        "dias": r["dias"], "mediana": mediana, "minimo": r["minimo"], "maximo": r["maximo"],
        "desconto_real_pct": desconto_real, "tendencia_pct": r["tendencia_pct"],
        "serie": r["serie"],
    }

    # o "de" anunciado está acima do preço normal do produto: o desconto foi inflado antes de anunciar
    if preco_de and preco_de > mediana * 1.05:
        out["veredito"] = "inflada"
        out["motivo"] = (f"o preço \"de\" ({_brl(preco_de)}) está acima do que este produto costuma custar "
                         f"({_brl(mediana)} em {r['dias']} dias)")
        out["desconto_anunciado_pct"] = round(100 * (1 - preco / preco_de), 1)
        return out

    if desconto_real >= 15:
        out["veredito"] = "boa"
        out["motivo"] = f"{desconto_real:.0f}% abaixo da mediana de {r['dias']} dias ({_brl(mediana)})"
        if preco <= r["minimo"] * 1.02:
            out["motivo"] += " — é o menor preço já registrado"
        return out

    if desconto_real <= -10:
        out["veredito"] = "cara"
        out["motivo"] = f"{abs(desconto_real):.0f}% acima da mediana de {r['dias']} dias ({_brl(mediana)})"
        return out

    out["veredito"] = "normal"
    out["motivo"] = f"na faixa de sempre ({_brl(mediana)} de mediana em {r['dias']} dias)"
    return out


def melhor_dia(mercado, nome, dias=120):
    """Em que dia da semana esse produto costuma estar mais barato (mínimo de 3 observações por dia)."""
    desde = _desde(dias)
    with conectar() as con:
        rows = con.execute("""
            SELECT dia, MIN(preco) preco FROM precos
            WHERE mercado = ? AND nome = ? AND dia >= ? GROUP BY dia
        """, (mercado, nome, desde)).fetchall()
    if len(rows) < 21:
        return None
    por_dia = {}
    for r in rows:
        try:
            wd = time.strptime(r["dia"], "%Y-%m-%d").tm_wday
        except ValueError:
            continue
        por_dia.setdefault(wd, []).append(r["preco"])
    medias = {wd: statistics.mean(v) for wd, v in por_dia.items() if len(v) >= 3}
    if len(medias) < 3:
        return None
    nomes = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    melhor = min(medias, key=medias.get)
    return {"dia_semana": nomes[melhor], "media": round(medias[melhor], 2),
            "economia_pct": round(100 * (1 - medias[melhor] / statistics.mean(medias.values())), 1)}


def indice_cesta(itens, dias=90):
    """Quanto custava, dia a dia, a compra de sempre da família.

    `itens` é uma lista de [mercado, nome]. Em cada dia, usa o menor preço observado de cada item
    entre os mercados informados; dias em que algum item não foi visto ficam de fora (a cesta só
    é comparável quando está completa).
    """
    if not itens:
        return {"dias": 0, "serie": []}
    desde = _desde(dias)
    with conectar() as con:
        marcas = ",".join("?" * len(itens))
        cond = " OR ".join("(mercado = ? AND nome = ?)" for _ in itens)
        args = [desde] + [x for par in itens for x in par]
        rows = con.execute(f"""
            SELECT dia, mercado, nome, MIN(preco) preco FROM precos
            WHERE dia >= ? AND ({cond}) GROUP BY dia, mercado, nome
        """, args).fetchall()
    por_dia = {}
    for r in rows:
        por_dia.setdefault(r["dia"], {})[(r["mercado"], r["nome"])] = r["preco"]
    serie = []
    for dia in sorted(por_dia):
        achados = por_dia[dia]
        if len(achados) < len(itens):
            continue
        serie.append({"dia": dia, "total": round(sum(achados.values()), 2)})
    if not serie:
        return {"dias": 0, "serie": [], "itens": len(itens)}
    totais = [x["total"] for x in serie]
    return {
        "dias": len(serie), "itens": len(itens), "serie": serie,
        "atual": totais[-1], "primeiro": totais[0],
        "minimo": min(totais), "maximo": max(totais),
        "variacao_pct": round(100 * (totais[-1] - totais[0]) / totais[0], 1) if totais[0] else 0,
    }


def quedas_bruscas(dia=None, pct=40, minimo_dias=14):
    """Produtos que caíram mais de `pct`% contra a mediana: provável erro de preço ou liquidação real.

    Vale ouro quando é erro de preço (acontece mais do que parece) e vale como aviso de liquidação
    quando é real. Só entram produtos com histórico suficiente para a comparação valer.
    """
    dia = dia or hoje()
    desde = _desde(90)
    with conectar() as con:
        hoje_rows = con.execute("""
            SELECT mercado, nome, preco, preco_de, ean FROM precos WHERE dia = ?
        """, (dia,)).fetchall()
        out = []
        for r in hoje_rows:
            hist = con.execute("""
                SELECT preco FROM precos WHERE mercado = ? AND nome = ? AND dia >= ? AND dia < ?
            """, (r["mercado"], r["nome"], desde, dia)).fetchall()
            if len(hist) < minimo_dias:
                continue
            precos = [h["preco"] for h in hist]
            mediana = statistics.median(precos)
            if mediana <= 0:
                continue
            queda = 100 * (1 - r["preco"] / mediana)
            if queda >= pct:
                out.append({
                    "mercado": r["mercado"], "nome": r["nome"], "preco": r["preco"],
                    "preco_de": r["preco_de"], "ean": r["ean"], "mediana": round(mediana, 2),
                    "minimo_hist": min(precos), "queda_pct": round(queda, 1), "dias": len(precos),
                })
    return sorted(out, key=lambda x: -x["queda_pct"])


def podar(dias=None):
    """Remove o que passou da janela de guarda."""
    dias = dias or DIAS_GUARDADOS
    corte = _desde(dias)
    with _lock, conectar() as con:
        n = con.execute("DELETE FROM precos WHERE dia < ?", (corte,)).rowcount
    return n


def contagens():
    with conectar() as con:
        r = con.execute("SELECT COUNT(*) n, COUNT(DISTINCT dia) d, COUNT(DISTINCT nome) p, MIN(dia) ini, MAX(dia) fim FROM precos").fetchone()
    return dict(r) if r else {"n": 0, "d": 0, "p": 0, "ini": None, "fim": None}


def _brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
