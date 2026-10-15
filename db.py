"""Armazenamento local (SQLite) de produtos, folhetos e configurações."""
import os
import sqlite3
import threading
import time

from coletores.base import sem_acento

ARQUIVO = os.environ.get("OFERTAS_DB") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "ofertas.db")
_lock = threading.Lock()

CAMPOS = ["mercado", "nome", "preco", "preco_de", "marca", "imagem", "url", "origem", "validade",
          "extra", "unidade", "preco_unidade", "desconto"]


def conectar():
    con = sqlite3.connect(ARQUIVO, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def criar():
    with conectar() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY,
            mercado TEXT, nome TEXT, nome_busca TEXT, preco REAL, preco_de REAL, marca TEXT,
            imagem TEXT, url TEXT, origem TEXT, validade TEXT, extra TEXT, unidade TEXT,
            preco_unidade REAL, desconto REAL, fonte TEXT, atualizado_em REAL,
            UNIQUE (mercado, nome, origem)
        );
        CREATE INDEX IF NOT EXISTS ix_prod_busca ON produtos(nome_busca);
        CREATE TABLE IF NOT EXISTS buscas (termo TEXT PRIMARY KEY, feita_em REAL);
        CREATE TABLE IF NOT EXISTS folhetos (
            imagem TEXT PRIMARY KEY, mercado TEXT, loja TEXT, titulo TEXT, pagina INTEGER,
            validade TEXT, inicio TEXT, fim TEXT, status TEXT DEFAULT 'pendente', erro TEXT,
            n_itens INTEGER DEFAULT 0, atualizado_em REAL
        );
        CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT);
        """)


def salvar_produtos(produtos, fonte):
    """Insere/atualiza produtos (dicts). `fonte` identifica de onde vieram (termo ou URL do folheto)."""
    agora = time.time()
    with _lock, conectar() as con:
        for p in produtos:
            vals = [p.get(c) for c in CAMPOS]
            con.execute(f"""
                INSERT INTO produtos ({",".join(CAMPOS)}, nome_busca, fonte, atualizado_em)
                VALUES ({",".join("?" * len(CAMPOS))}, ?, ?, ?)
                ON CONFLICT (mercado, nome, origem) DO UPDATE SET
                {",".join(f"{c}=excluded.{c}" for c in CAMPOS)}, nome_busca=excluded.nome_busca,
                fonte=excluded.fonte, atualizado_em=excluded.atualizado_em
            """, vals + [sem_acento(p["nome"] + " " + (p.get("marca") or "")), fonte, agora])


def apagar_da_fonte(fonte):
    with _lock, conectar() as con:
        con.execute("DELETE FROM produtos WHERE fonte = ?", (fonte,))


def _filtro_texto(q):
    """Cada palavra da busca precisa aparecer no nome (tolerando plural/acentos)."""
    sql, args = [], []
    for w in sem_acento(q).split():
        if len(w) < 2:
            continue
        raiz = w[:-1] if len(w) > 4 and w.endswith("s") else w
        raiz = raiz[:-1] if len(raiz) > 4 and raiz[-1] in "aeo" else raiz
        sql.append("nome_busca LIKE ?")
        args.append(f"%{raiz}%")
    return sql, args


def consultar(q="", mercado="", so_ofertas=False, origem="", limite=500, max_idade_h=None):
    where, args = _filtro_texto(q)
    if mercado:
        where.append("mercado = ?"); args.append(mercado)
    if origem:
        where.append("origem = ?"); args.append(origem)
    if so_ofertas:
        where.append("(desconto > 0 OR origem = 'folheto' OR extra <> '')")
    if max_idade_h:
        where.append("(origem = 'folheto' OR atualizado_em > ?)"); args.append(time.time() - max_idade_h * 3600)
    sql = "SELECT * FROM produtos" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY COALESCE(preco_unidade, preco) LIMIT ?"
    with conectar() as con:
        return [dict(r) for r in con.execute(sql, args + [limite])]


def busca_recente(termo, horas=6):
    with conectar() as con:
        r = con.execute("SELECT feita_em FROM buscas WHERE termo = ?", (sem_acento(termo).strip(),)).fetchone()
    return bool(r and time.time() - r["feita_em"] < horas * 3600)


def marcar_busca(termo):
    with _lock, conectar() as con:
        con.execute("INSERT OR REPLACE INTO buscas VALUES (?, ?)", (sem_acento(termo).strip(), time.time()))


def salvar_folhetos(folhetos):
    with _lock, conectar() as con:
        for f in folhetos:
            con.execute("""
                INSERT INTO folhetos (imagem, mercado, loja, titulo, pagina, validade, inicio, fim, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (imagem) DO UPDATE SET validade=excluded.validade, fim=excluded.fim, loja=excluded.loja
            """, (f["imagem"], f["mercado"], f["loja"], f["titulo"], f["pagina"], f["validade"],
                  f["inicio"], f["fim"], time.time()))


def listar_folhetos(apenas_vigentes=True):
    sql = "SELECT * FROM folhetos"
    args = []
    if apenas_vigentes:
        sql += " WHERE fim = '' OR fim >= ?"
        args.append(time.strftime("%Y-%m-%d"))
    sql += " ORDER BY mercado, titulo, pagina"
    with conectar() as con:
        return [dict(r) for r in con.execute(sql, args)]


def status_folheto(imagem, status, erro="", n=0):
    with _lock, conectar() as con:
        con.execute("UPDATE folhetos SET status=?, erro=?, n_itens=? WHERE imagem=?", (status, erro, n, imagem))


def limpar_vencidos():
    """Remove folhetos vencidos e os produtos extraídos deles."""
    hoje = time.strftime("%Y-%m-%d")
    with _lock, conectar() as con:
        vencidos = [r[0] for r in con.execute("SELECT imagem FROM folhetos WHERE fim <> '' AND fim < ?", (hoje,))]
        for img in vencidos:
            con.execute("DELETE FROM produtos WHERE fonte = ?", (img,))
        con.execute("DELETE FROM folhetos WHERE fim <> '' AND fim < ?", (hoje,))


def config(chave, padrao=""):
    with conectar() as con:
        r = con.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
    return r["valor"] if r else padrao


def set_config(chave, valor):
    with _lock, conectar() as con:
        con.execute("INSERT OR REPLACE INTO config VALUES (?, ?)", (chave, valor))


def contagens():
    with conectar() as con:
        rows = con.execute("SELECT mercado, origem, COUNT(*) n, MAX(atualizado_em) t FROM produtos GROUP BY mercado, origem")
        return [dict(r) for r in rows]


def limpar_precos_site():
    """Ao trocar de CEP os preços online mudam: descarta os antigos e o cache de buscas."""
    with _lock, conectar() as con:
        con.execute("DELETE FROM produtos WHERE origem = 'site'")
        con.execute("DELETE FROM buscas")


def produtos_por_chave(chaves):
    """chaves: lista de [mercado, nome] -> {"mercado|nome": produto atual}."""
    out = {}
    with conectar() as con:
        for mercado, nome in chaves:
            r = con.execute("SELECT * FROM produtos WHERE mercado = ? AND nome = ? ORDER BY atualizado_em DESC LIMIT 1",
                            (mercado, nome)).fetchone()
            if r:
                out[f"{mercado}|{nome}"] = dict(r)
    return out
