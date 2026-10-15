"""Ofertas SP - compara preços e folhetos dos grandes mercados de São Paulo.

Uso:
    py app.py               abre o app em http://localhost:8765
    py app.py --rede        também acessível pelo celular no mesmo Wi-Fi
    py app.py --atualizar   só coleta ofertas e folhetos (para agendar no Windows)
"""
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db
from coletores import extrator_ia
from coletores.base import Produto
from coletores.folhetos import ASSAI_LOJAS_SP, todos_folhetos
from coletores.sites import fontes

PORTA = int(os.environ.get("OFERTAS_PORTA", "8765"))
PASTA = os.path.dirname(os.path.abspath(__file__))

# Cesta de itens usada para montar a aba "Ofertas" a partir das lojas online
CESTA = [
    "arroz", "feijão", "café", "açúcar", "óleo de soja", "leite", "azeite", "macarrão", "farinha de trigo",
    "ovos", "manteiga", "margarina", "queijo mussarela", "presunto", "iogurte", "pão de forma",
    "carne bovina", "frango", "linguiça", "picanha", "cerveja", "refrigerante", "suco", "água mineral",
    "papel higiênico", "detergente", "sabão em pó", "amaciante", "desinfetante", "shampoo",
    "creme dental", "fralda", "biscoito", "chocolate", "achocolatado", "molho de tomate", "atum",
    "banana", "tomate", "batata",
]

trabalho = {"tarefa": "", "feito": 0, "total": 0, "erros": [], "inicio": 0.0, "fim": 0.0}
_trab_lock = threading.Lock()


# ---------------------------------------------------------------- coleta

def buscar_ao_vivo(termo, n=24):
    """Busca o termo em todas as lojas online em paralelo e salva no banco."""
    resultados, erros = [], {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(f, termo, n): nome for nome, f in fontes()}
        for fut in as_completed(futs):
            try:
                resultados += [p.dict() for p in fut.result()]
            except Exception as e:
                erros[futs[fut]] = str(e)[:120]
    db.salvar_produtos(resultados, fonte=f"busca:{termo}")
    db.marcar_busca(termo)
    return erros


def _rodar(nome, total, func):
    with _trab_lock:
        if trabalho["tarefa"] and not trabalho["fim"]:
            return False
        trabalho.update(tarefa=nome, feito=0, total=total, erros=[], inicio=time.time(), fim=0.0)

    def alvo():
        try:
            func()
        except Exception as e:
            trabalho["erros"].append(str(e))
        finally:
            trabalho["fim"] = time.time()

    threading.Thread(target=alvo, daemon=True).start()
    return True


def atualizar_ofertas():
    def f():
        for termo in CESTA:
            erros = buscar_ao_vivo(termo, n=40)
            trabalho["erros"] += [f"{m}: {e}" for m, e in erros.items()]
            trabalho["feito"] += 1
    return _rodar("Atualizando ofertas das lojas online", len(CESTA), f)


def atualizar_folhetos():
    folhetos, erros = todos_folhetos(db.config("loja_assai", "Mooca"))
    db.limpar_vencidos()
    db.salvar_folhetos(folhetos)
    return erros


def ler_folheto(img):
    f = next((x for x in db.listar_folhetos(False) if x["imagem"] == img), None)
    if not f:
        return
    try:
        itens = extrator_ia.extrair(img)
    except Exception as e:
        db.status_folheto(img, "erro", str(e)[:300])
        raise
    prods = []
    for it in itens:
        if not it.get("nome") or not it.get("preco"):
            continue
        prods.append(Produto(
            mercado=f["mercado"], nome=it["nome"], preco=float(it["preco"]), preco_de=it.get("preco_de"),
            origem="folheto", validade=f["validade"], extra=it.get("condicao", ""), url=img,
            imagem=img,
        ).finalizar().dict())
    db.apagar_da_fonte(img)
    db.salvar_produtos(prods, fonte=img)
    db.status_folheto(img, "lido", "", len(prods))


def ler_folhetos(imagens):
    def f():
        for img in imagens:
            try:
                ler_folheto(img)
            except Exception as e:
                trabalho["erros"].append(f"{img.rsplit('/', 1)[-1]}: {e}")
            trabalho["feito"] += 1
    return _rodar("Lendo folhetos com IA", len(imagens), f)


# ---------------------------------------------------------------- servidor

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(PASTA, "static"), **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/buscar":
                termo = q.get("q", "").strip()
                if not termo:
                    return self._json({"produtos": [], "erros": {}})
                erros = {}
                if q.get("forcar") == "1" or not db.busca_recente(termo):
                    erros = buscar_ao_vivo(termo)
                return self._json({"produtos": db.consultar(termo, limite=600, max_idade_h=24 * 7), "erros": erros})
            if u.path == "/api/ofertas":
                return self._json({"produtos": db.consultar(q.get("q", ""), q.get("mercado", ""), so_ofertas=True,
                                                            origem=q.get("origem", ""), limite=2000)})
            if u.path == "/api/folhetos":
                return self._json({"folhetos": db.listar_folhetos()})
            if u.path == "/api/status":
                ok, motivo = extrator_ia.disponivel()
                return self._json({
                    "trabalho": trabalho, "ia": ok, "ia_motivo": motivo, "contagens": db.contagens(),
                    "loja_assai": db.config("loja_assai", "Mooca"), "lojas_assai": sorted(ASSAI_LOJAS_SP),
                    "mercados_online": [n for n, _ in fontes()], "mercados_folheto": ["Assaí", "Roldão", "Akki", "Lopes", "Max Atacadista"],
                })
        except Exception as e:
            return self._json({"erro": str(e)}, 500)
        if u.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        try:
            corpo = self._corpo()
            if u.path == "/api/ofertas/atualizar":
                return self._json({"iniciado": atualizar_ofertas()})
            if u.path == "/api/folhetos/atualizar":
                if "loja_assai" in corpo:
                    db.set_config("loja_assai", corpo["loja_assai"])
                return self._json({"erros": atualizar_folhetos(), "folhetos": db.listar_folhetos()})
            if u.path == "/api/folhetos/ler":
                ok, motivo = extrator_ia.disponivel()
                if not ok:
                    return self._json({"erro": motivo}, 400)
                imgs = corpo.get("imagens") or [f["imagem"] for f in db.listar_folhetos() if f["status"] != "lido"]
                return self._json({"iniciado": ler_folhetos(imgs), "total": len(imgs)})
        except Exception as e:
            return self._json({"erro": str(e)}, 500)
        self._json({"erro": "rota desconhecida"}, 404)


def ip_local():
    """IP deste PC na rede local (não envia nada; só consulta a rota)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    db.criar()
    if "--atualizar" in sys.argv:
        print("Atualizando folhetos...", atualizar_folhetos() or "ok")
        for i, termo in enumerate(CESTA, 1):
            print(f"[{i}/{len(CESTA)}] {termo}", buscar_ao_vivo(termo, n=40) or "")
        if extrator_ia.disponivel()[0]:
            for f in db.listar_folhetos():
                if f["status"] != "lido":
                    try:
                        ler_folheto(f["imagem"]); print("lido:", f["imagem"])
                    except Exception as e:
                        print("erro:", f["imagem"], e)
        return
    rede = "--rede" in sys.argv
    srv = ThreadingHTTPServer(("0.0.0.0" if rede else "127.0.0.1", PORTA), Handler)
    url = f"http://localhost:{PORTA}"
    print(f"Ofertas SP rodando em {url}  (Ctrl+C para sair)")
    if rede:
        print(f"\nNo celular (mesmo Wi-Fi deste PC), abra:  http://{ip_local()}:{PORTA}\n")
    if "--sem-navegador" not in sys.argv:
        threading.Timer(1, lambda: webbrowser.open(url)).start()
    if not db.listar_folhetos():
        threading.Thread(target=atualizar_folhetos, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
