"""Ofertas SP - compara preços e folhetos dos grandes mercados de São Paulo.

Uso:
    py app.py               abre o app em http://localhost:8765
    py app.py --rede        também acessível pelo celular no mesmo Wi-Fi
    py app.py --atualizar   só coleta ofertas e folhetos (para agendar no Windows)
"""
import json
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import alertas
import db
import historico
from coletores import extrator_ia, local
from coletores.base import Produto
from coletores.folhetos import ASSAI_LOJAS_SP, todos_folhetos
from coletores.regioes import REGIOES
from coletores.sites import VTEX, fontes

PORTA = int(sys.argv[sys.argv.index("--porta") + 1]) if "--porta" in sys.argv else \
    int(os.environ.get("OFERTAS_PORTA") or os.environ.get("PORT") or "8765")
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

def buscar_ao_vivo(termo, n=24, regiao=None):
    """Busca o termo nas lojas online (da região, se informada) em paralelo e salva no banco."""
    resultados, erros = [], {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(f, termo, n): nome for nome, f in fontes(regiao)}
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
    folhetos, erros = todos_folhetos(db.config("loja_assai", "Mooca"), db.config("loja_assai_id") or None)
    db.limpar_vencidos()
    db.salvar_folhetos(folhetos)
    return erros


def ler_folheto(img, itens=None):
    f = next((x for x in db.listar_folhetos(False) if x["imagem"] == img), None)
    if not f:
        return
    try:
        itens = extrator_ia.extrair(img) if itens is None else itens
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


def definir_cep(cep, folhetos_em_segundo_plano=True, limpar=True):
    """Resolve o CEP, descobre a região de cada rede e o Assaí mais próximo."""
    end = local.resolver_cep(cep)
    reg = local.regioes(end["cep"])
    proximas = []
    if end["lat"] is not None:
        try:
            proximas = local.assai_mais_proximas(end["lat"], end["lon"])
        except Exception:
            pass
    end["assai"] = proximas
    db.set_config("endereco", json.dumps(end, ensure_ascii=False))
    db.set_config("regiao", json.dumps(reg))
    local.aplicar(reg)
    if proximas:
        db.set_config("loja_assai", proximas[0]["nome"])
        db.set_config("loja_assai_id", str(proximas[0]["id"]))
    if limpar:
        db.limpar_precos_site()
    if folhetos_em_segundo_plano:
        threading.Thread(target=atualizar_folhetos, daemon=True).start()
    return info_local()


def da_regiao(itens, regiao):
    """Filtra produtos/folhetos pelas redes da região (sem região: tudo)."""
    if regiao not in REGIOES:
        return itens
    redes = set(REGIOES[regiao]["online"]) | set(REGIOES[regiao]["folhetos"])
    return [i for i in itens if i["mercado"] in redes]


def info_local():
    end = json.loads(db.config("endereco", "null") or "null")
    reg = json.loads(db.config("regiao", "null") or "null") or {}
    if not end:
        return {"endereco": None}
    vtex = reg.get("vtex") or {}
    redes = {nome: bool(vtex.get(host)) for nome, host in VTEX.items()}
    gpa = reg.get("gpa")
    extra = reg.get("extra")
    return {"endereco": end, "redes_regionalizadas": redes,
            "pao_de_acucar": gpa["nome"] if gpa else None, "extra": extra["nome"] if extra else None}


def lojas_assai_menu():
    """Lojas para o seletor: as mais próximas do CEP primeiro, depois as da capital."""
    end = json.loads(db.config("endereco", "null") or "null") or {}
    menu = [{"nome": f"{l['nome']} ({l['km']} km)", "id": l["id"]} for l in end.get("assai") or []]
    vistos = {m["id"] for m in menu}
    menu += [{"nome": n, "id": i} for n, i in sorted(ASSAI_LOJAS_SP.items()) if i not in vistos]
    return menu


def precos_favoritos(favs):
    """Preço atual de cada favorito + a opção mais barata (por kg/L) em qualquer rede."""
    atuais = db.produtos_por_chave([[f["mercado"], f["nome"]] for f in favs])
    out = {}
    for f in favs:
        k = f"{f['mercado']}|{f['nome']}"
        alts = [p for p in db.consultar(f.get("termo") or f["nome"], limite=200, max_idade_h=24 * 7)
                if f"{p['mercado']}|{p['nome']}" != k]
        atual = atuais.get(k)
        if atual and atual.get("preco_unidade"):
            # compara por kg/L só com produtos medidos na mesma unidade
            alts = [p for p in alts if p["preco_unidade"] and p["unidade"] == atual["unidade"]]
            chave = lambda p: p["preco_unidade"]
        else:
            chave = lambda p: p["preco"]
        out[k] = {"atual": atual, "alternativa": min(alts, key=chave) if alts else None}
    return out


def precos_lista(itens):
    """Para cada item da lista: opção mais barata no geral e em cada mercado."""
    out = []
    for it in itens:
        texto = (it.get("texto") or "").strip()
        if not texto:
            out.append({"melhor": None, "por_mercado": {}})
            continue
        if not db.busca_recente(texto):
            buscar_ao_vivo(texto)
        por_mercado = {}
        for p in db.consultar(texto, limite=400, max_idade_h=24 * 7):
            m = p["mercado"]
            if m not in por_mercado or _custo(p) < _custo(por_mercado[m]):
                por_mercado[m] = p
        melhor = min(por_mercado.values(), key=_custo) if por_mercado else None
        fixo = None
        if it.get("prod"):  # produto escolhido pelo usuário (veio do botão 🛒)
            fixo = db.produtos_por_chave([[it["prod"]["mercado"], it["prod"]["nome"]]]).get(it["prod"]["k"])
        out.append({"melhor": melhor, "por_mercado": por_mercado, "fixo": fixo})
    return out


def _custo(p):
    # compara por kg/L quando dá; sem quantidade no nome, pelo preço da embalagem
    return p["preco_unidade"] if p.get("preco_unidade") else p["preco"]


def atualizar_termos(termos):
    def f():
        for t in termos:
            erros = buscar_ao_vivo(t)
            trabalho["erros"] += [f"{m}: {e}" for m, e in erros.items()]
            trabalho["feito"] += 1
    return _rodar("Atualizando preços dos favoritos", len(termos), f)


def ler_folhetos(imagens):
    def f():
        for img in imagens:
            try:
                ler_folheto(img)
            except Exception as e:
                trabalho["erros"].append(f"{img.rsplit('/', 1)[-1]}: {e}")
            trabalho["feito"] += 1
    return _rodar("Lendo folhetos com IA", len(imagens), f)


# ---------------------------------------------------------------- histórico e promoção falsa

def historico_produto(mercado, nome, dias=90):
    """Série + veredito do desconto de um produto específico."""
    av = historico.avaliar_oferta(mercado, nome, _preco_atual(mercado, nome) or 0, dias=dias)
    av["melhor_dia"] = historico.melhor_dia(mercado, nome)
    av["mercado"] = mercado
    av["nome"] = nome
    return av


def _preco_atual(mercado, nome):
    p = db.produtos_por_chave([[mercado, nome]]).get(f"{mercado}|{nome}")
    return p["preco"] if p else None


def ofertas_reais(limite=40, dias=90):
    """Só as ofertas que sobrevivem ao histórico: desconto de verdade, não teatro de preço."""
    out = []
    for p in db.consultar(so_ofertas=True, limite=1200):
        av = historico.avaliar_oferta(p["mercado"], p["nome"], p["preco"], p.get("preco_de"), dias=dias)
        if av.get("veredito") in ("boa", "inflada"):
            out.append({**p, "historico": {k: v for k, v in av.items() if k != "serie"}})
    out.sort(key=lambda x: -(x["historico"].get("desconto_real_pct") or 0))
    return out[:limite]


def saude(familia=""):
    """Estado do serviço, para o painel e para o monitoramento externo.

    A pergunta que importa não é "o servidor está de pé", é "a coleta de hoje rodou".
    Um app que serve preço de três dias atrás como se fosse de hoje é pior que um app fora do ar.
    """
    h = historico.contagens()
    ultima = db.ultima_execucao_ok("coleta")
    horas = round((time.time() - ultima) / 3600, 1) if ultima else None
    # com família informada, conta só os alertas dela: é o número que aparece ao lado da lista
    if familia:
        alertas_ativos = len([a for a in db.alertas_listar(familia) if a.get("ativo")])
    else:
        alertas_ativos = len(db.alertas_ativos())
    avisos = []
    if horas is None:
        avisos.append("nenhuma coleta registrada ainda")
    elif horas > 36:
        avisos.append(f"a última coleta bem-sucedida foi há {horas:.0f} horas")
    if h.get("d") == 0:
        avisos.append("histórico de preços vazio")
    return {
        "ok": not avisos,
        "avisos": avisos,
        "ultima_coleta_horas": horas,
        "historico": h,
        "alertas_ativos": alertas_ativos,
        "telegram": alertas.telegram_configurado(),
        "produtos": sum(c["n"] for c in db.contagens()),
        "execucoes": db.execucoes_recentes(10),
    }


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

    def _familia_gravar(self, corpo):
        """Cria ou atualiza a lista compartilhada.

        O código é a única credencial, então ele precisa ser longo o bastante para não ser
        adivinhado: 12 caracteres de um alfabeto sem letras ambíguas (0/O, 1/I/L) dá ~10^18
        combinações. Quem tem o código entra; não existe "revogar acesso" sem trocar o código.
        """
        codigo = (corpo.get("codigo") or "").strip().upper()
        dados = corpo.get("dados")
        if dados is None:
            return {"erro": "nada para gravar"}, 400
        if not codigo:
            codigo = _novo_codigo()
        elif len(codigo) < 8:
            return {"erro": "código curto demais"}, 400
        r = db.familia_gravar(codigo, dados, corpo.get("versao"))
        if r["conflito"]:
            atual = db.familia_ler(codigo) or {}
            return {"conflito": True, "versao": r["versao"], "dados": atual.get("dados"),
                    "codigo": codigo}
        return {"codigo": codigo, "versao": r["versao"], "conflito": False}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/buscar":
                termo = q.get("q", "").strip()
                if not termo:
                    return self._json({"produtos": [], "erros": {}})
                erros = {}
                reg = q.get("regiao") if q.get("regiao") in REGIOES else None
                if q.get("forcar") == "1" or not db.busca_recente(f"{reg}:{termo}"):
                    erros = buscar_ao_vivo(termo, regiao=reg)
                    db.marcar_busca(f"{reg}:{termo}")
                return self._json({"produtos": da_regiao(db.consultar(termo, limite=600, max_idade_h=24 * 7), reg), "erros": erros})
            if u.path == "/api/ofertas":
                return self._json({"produtos": da_regiao(db.consultar(q.get("q", ""), q.get("mercado", ""), so_ofertas=True,
                                                                      origem=q.get("origem", ""), limite=2000), q.get("regiao"))})
            if u.path == "/api/folhetos":
                return self._json({"folhetos": da_regiao(db.listar_folhetos(), q.get("regiao"))})
            if u.path == "/api/local":
                return self._json(info_local())
            if u.path == "/api/dados":
                return self._json(json.loads(db.config("dados", "{}") or "{}"))
            if u.path == "/api/status":
                ok, motivo = extrator_ia.disponivel()
                return self._json({
                    "trabalho": trabalho, "ia": ok, "ia_motivo": motivo, "contagens": db.contagens(),
                    "loja_assai_id": int(db.config("loja_assai_id") or ASSAI_LOJAS_SP.get(db.config("loja_assai", "Mooca"), 260)),
                    "lojas_assai": lojas_assai_menu(),
                    "mercados_online": [n for n, _ in fontes()], "regioes": REGIOES, "mercados_folheto": ["Assaí", "Roldão", "Akki", "Lopes", "Max Atacadista", "Barbosa", "3M"],
                    "historico": historico.contagens(), "telegram": alertas.telegram_configurado(),
                })
            if u.path == "/api/saude":
                return self._json(saude(q.get("familia", "")))
            if u.path == "/api/historico":
                return self._json(historico_produto(q.get("mercado", ""), q.get("nome", ""),
                                                    int(q.get("dias") or 90)))
            if u.path == "/api/historico/ean":
                return self._json({"ean": q.get("ean", ""), "precos": db.por_ean(q.get("ean", "")),
                                   "serie": historico.serie_ean(q.get("ean", ""), int(q.get("dias") or 90))})
            if u.path == "/api/ofertas/reais":
                return self._json({"produtos": ofertas_reais(int(q.get("limite") or 40))})
            if u.path == "/api/quedas":
                return self._json({"quedas": historico.quedas_bruscas(pct=float(q.get("pct") or 40))})
            if u.path == "/api/cesta":
                chaves = [c.split("|", 1) for c in (q.get("itens") or "").split(";") if "|" in c]
                return self._json(historico.indice_cesta(chaves, int(q.get("dias") or 90)))
            if u.path == "/api/familia":
                codigo = q.get("codigo", "").strip().upper()
                fam = db.familia_ler(codigo) if codigo else None
                if not fam:
                    return self._json({"erro": "código não encontrado"}, 404)
                return self._json(fam)
            if u.path == "/api/alertas":
                return self._json({"alertas": db.alertas_listar(q.get("familia", "").strip().upper()),
                                   "telegram": alertas.telegram_configurado()})
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
            if u.path == "/api/local":
                try:
                    return self._json(definir_cep(corpo.get("cep", "")))
                except ValueError as e:
                    return self._json({"erro": str(e)}, 400)
            if u.path == "/api/dados":
                db.set_config("dados", json.dumps(corpo, ensure_ascii=False))
                return self._json({"ok": True})
            if u.path == "/api/favoritos/precos":
                return self._json(precos_favoritos(corpo.get("favoritos") or []))
            if u.path == "/api/favoritos/atualizar":
                termos = sorted({t for t in corpo.get("termos") or [] if t})
                return self._json({"iniciado": atualizar_termos(termos)})
            if u.path == "/api/lista/precos":
                return self._json({"itens": precos_lista(corpo.get("itens") or [])})
            if u.path == "/api/folhetos/atualizar":
                if corpo.get("loja_assai_id"):
                    db.set_config("loja_assai_id", str(corpo["loja_assai_id"]))
                    db.set_config("loja_assai", corpo.get("loja_assai", ""))
                return self._json({"erros": atualizar_folhetos(), "folhetos": db.listar_folhetos()})
            if u.path == "/api/folhetos/ler":
                ok, motivo = extrator_ia.disponivel()
                if not ok:
                    return self._json({"erro": motivo}, 400)
                imgs = corpo.get("imagens") or [f["imagem"] for f in db.listar_folhetos() if f["status"] != "lido"]
                return self._json({"iniciado": ler_folhetos(imgs), "total": len(imgs)})
            if u.path == "/api/familia":
                return self._json(self._familia_gravar(corpo))
            if u.path == "/api/alertas":
                familia = (corpo.get("familia") or "").strip().upper()
                if not familia:
                    return self._json({"erro": "informe o código da família"}, 400)
                if corpo.get("apagar"):
                    db.alerta_apagar(int(corpo["apagar"]))
                elif corpo.get("id"):
                    db.alerta_atualizar(int(corpo["id"]), **{k: v for k, v in corpo.items() if k != "id"})
                else:
                    if not corpo.get("nome") or not corpo.get("alvo"):
                        return self._json({"erro": "informe o produto e o preço-alvo"}, 400)
                    db.alerta_criar(familia, corpo["nome"], corpo["alvo"], corpo.get("mercado", ""),
                                    corpo.get("termo", ""), corpo.get("telegram_chat", ""))
                return self._json({"alertas": db.alertas_listar(familia),
                                   "telegram": alertas.telegram_configurado()})
            if u.path == "/api/alertas/checar":
                return self._json(alertas.checar_alertas())
            if u.path == "/api/alertas/teste":
                ok, det = alertas.enviar_telegram("✅ Ofertas SP: o Telegram está ligado. "
                                                      "Os avisos de preço vão chegar aqui.")
                return self._json({"ok": ok, "detalhe": det})
            if u.path == "/api/resumo-semanal":
                texto = alertas.texto_resumo_semanal((corpo.get("familia") or "").strip().upper())
                if texto is None:
                    return self._json({"erro": "família sem lista para resumir"}, 400)
                if corpo.get("enviar"):
                    ok, det = alertas.enviar_telegram(texto)
                    return self._json({"ok": ok, "detalhe": det, "texto": texto})
                return self._json({"texto": texto})
        except Exception as e:
            return self._json({"erro": str(e)}, 500)
        self._json({"erro": "rota desconhecida"}, 404)


def _novo_codigo(n=12):
    """Código de convite da família: sem 0/O/1/I/L, para ninguém errar ao digitar."""
    alfabeto = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(n))


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
    local.aplicar(json.loads(db.config("regiao", "null") or "null"))
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
    # no Windows, reutilizar o endereço deixa dois servidores "dividirem" a porta sem erro
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    try:
        srv = ThreadingHTTPServer(("0.0.0.0" if rede else "127.0.0.1", PORTA), Handler)
    except OSError:
        sys.exit(f"A porta {PORTA} já está em uso (o app já está aberto?). Use: py app.py --porta 8766")
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
