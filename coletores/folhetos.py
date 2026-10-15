"""Coletores de folhetos/tabloides (imagens) publicados pelas redes."""
import json
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from urllib.parse import urljoin, quote, unquote

from .base import UA, http, http_json

# Lojas Assaí na cidade de São Paulo (nome -> loja_id usado no JSON de ofertas do site)
ASSAI_LOJAS_SP = {
    "Águia de Haia": 49, "Aeroporto Congonhas": 279, "Anhanguera": 272, "Aricanduva": 144,
    "Barra Funda": 45, "Casa Verde": 2, "Cidade Dutra": 155, "Cidade Tiradentes": 208,
    "Fernão Dias": 89, "Freguesia do Ó": 285, "Guaianases": 60, "Interlagos": 269, "Itaquera": 19,
    "Jaçanã": 20, "Jabaquara": 31, "Jacu Pêssego": 124, "Jaguaré": 22, "Jaraguá/Taipas": 126,
    "João Dias": 18, "Marginal Tietê - Tatuapé": 254, "Marginal Tietê Vila Maria": 64, "Mooca": 260,
    "Nações Unidas": 199, "Nordestina": 32, "Penha - Marginal Tietê": 53, "Raposo Tavares": 270,
    "São Mateus": 153, "São Miguel": 3, "Santa Catarina": 166, "Sapopemba": 17,
    "Sezefredo Fagundes": 148, "Tancredo Neves": 137, "Teotônio Vilela": 85, "Vila Carrão": 1,
    "Vila Sônia": 8,
}


def _data_br(s):
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def _ofertas_assai():
    # sem o parâmetro de tempo o CDN devolve uma cópia antiga do arquivo
    url = f"https://www.assai.com.br/sites/default/files/static/ofertas_assai.json?{int(time.time())}"
    return http_json(url).get("ofertas", [])


def folhetos_assai(loja="Mooca", loja_id=None):
    loja_id = int(loja_id) if loja_id else ASSAI_LOJAS_SP.get(loja, 260)
    hoje = date.today()
    out = []
    for o in _ofertas_assai():
        if not any(int(l.get("loja_id", 0)) == loja_id for l in o.get("lojas", [])):
            continue
        fim, ini = _data_br(o.get("end_date")), _data_br(o.get("start_date"))
        if fim and fim < hoje:
            continue
        for i, img in enumerate(o.get("images", []), 1):
            out.append({
                "mercado": "Assaí", "loja": loja, "titulo": o.get("title") or f"Tabloide {o.get('id_oferta')}",
                "pagina": i, "imagem": urljoin("https://www.assai.com.br/", img["url"]), "validade": o.get("custom_text", ""),
                "inicio": ini.isoformat() if ini else "", "fim": fim.isoformat() if fim else "",
            })
    return out


def folhetos_roldao():
    html = http("https://www.roldao.com.br/ofertas")
    urls = re.findall(r'https://(?:www\.)?roldao\.com\.br/wp-content/uploads/\d{4}/\d{2}/[^"\'\s>]+?\.(?:jpe?g|png|webp)', html, re.I)
    melhores = {}
    for u in urls:
        if "marcas-parceiras" in u or "Aspect-Ratio" in u:
            continue
        base = re.sub(r"(-\d+x\d+|-scaled)(\.\w+)$", r"\2", u)
        nota = 3 if "-scaled." in u else (1 if re.search(r"-\d+x\d+\.", u) else 2)
        if nota > melhores.get(base, ("", 0))[1]:
            melhores[base] = (u, nota)
    out = []
    for base, (u, _) in sorted(melhores.items()):
        nome = base.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        m = re.search(r"(\d{1,2})-A-(\d{1,2})-(\d{1,2})-(\d{4})", nome, re.I)
        fim = ""
        if m:
            try:
                fim = date(int(m.group(4)), int(m.group(3)), int(m.group(2))).isoformat()
            except ValueError:
                pass
            if fim and fim < date.today().isoformat():
                continue
        elif not re.search(r"(?i)oferta|encarte|tabloide|especial|combate|folheto", nome):
            continue  # imagem que não parece folheto
        titulo = re.sub(r"-\d.*$", "", nome).replace("-", " ").title()
        out.append({"mercado": "Roldão", "loja": "", "titulo": titulo, "pagina": 1, "imagem": u,
                    "validade": f"Válido até {fim[8:10]}/{fim[5:7]}/{fim[:4]}" if fim else "", "inicio": "", "fim": fim})
    return out


def _folheto(mercado, titulo, url, pagina=1, loja="", validade="", fim=""):
    return {"mercado": mercado, "loja": loja, "titulo": titulo, "pagina": pagina, "imagem": url,
            "validade": validade, "inicio": "", "fim": fim}


def _fim_por_nome(nome):
    """'...13-A-15-10...' -> data ISO do último dia (ano atual)."""
    m = re.search(r"(\d{1,2})-A-(\d{1,2})-(\d{1,2})", nome, re.I)
    if not m:
        return ""
    try:
        return date(date.today().year, int(m.group(3)), int(m.group(2))).isoformat()
    except ValueError:
        return ""


def folhetos_akki():
    h = http("https://akkiatacadista.com.br/jornal-de-ofertas/")
    pdfs = {unquote(u) for u in re.findall(r"file=(https?%3A%2F%2F[^&\"'\s]+?\.pdf)", h)}
    pdfs |= set(re.findall(r'https://akkiatacadista\.com\.br/wp-content/uploads/[^"\'\s]+?\.pdf', h))
    out = []
    for u in sorted(pdfs):
        nome = u.rsplit("/", 1)[-1][:-4]
        fim = _fim_por_nome(nome)
        if fim and fim < date.today().isoformat():
            continue
        out.append(_folheto("Akki", nome.replace("-", " ").title(), u, fim=fim,
                            validade=f"Válido até {fim[8:10]}/{fim[5:7]}" if fim else ""))
    return out


def folhetos_lopes():
    d = http_json("https://www.lopessupermercados.com.br/api/site-data")
    vistos = {}
    for loja in d.get("tabloides") or []:
        for t in loja.get("tabloide") or []:
            arqs = t.get("arquivos") or []
            img = next((a for a in arqs if re.search(r"\.(png|jpe?g|webp)$", a, re.I)), None) or next(iter(arqs), None)
            if not img:
                continue
            url = "https://www.lopessupermercados.com.br/" + img.lstrip("/")
            titulo = " - ".join(x for x in (t.get("nome_categoria"), t.get("descricao_categoria")) if x).title()
            f = vistos.setdefault(url, _folheto("Lopes", titulo, url, loja=""))
            f.setdefault("_lojas", []).append(loja.get("nome_loja", ""))
    out = []
    for f in vistos.values():
        lojas = f.pop("_lojas")
        f["loja"] = lojas[0] if len(lojas) == 1 else f"{len(lojas)} lojas"
        out.append(f)
    return out


def folhetos_max(loja=120):
    raw = http(f"https://institucional.supermuffato.com.br/webtools/services/api/sm-rds-ofertas.php?action=getOffers&store={loja}")
    d = json.loads(re.sub(r"^[^\[{]*\(|\);?\s*$", "", raw.strip()))
    out = []
    for oferta in d.get("offers") or []:
        for fl in oferta.get("flyer") or []:
            for i, it in enumerate(fl.get("item") or [], 1):
                url = it.get("image", "")
                if url.startswith("//"):
                    url = "https:" + url
                nome = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                nome = re.sub(r"(?i)\(\d+\)|p[áa]g\.?\s*\d+|p[áa]gina\s*\d+", "", nome)
                titulo = re.sub(r"[-_\s]+", " ", nome).strip().title()
                url = quote(url, safe=":/%")
                out.append(_folheto("Max Atacadista", titulo, url, pagina=i, loja="São Paulo"))
    return out


_BARBOSA = "https://www.barbosasupermercados.com.br"
_BARBOSA_API = "https://api-barbosa.applay.tech/api2/ecommerce/"


def _token_barbosa():
    """Token de acesso que o site do Barbosa (plataforma Applay) pede ao abrir, via "server action" do Next.js.
    O identificador da action muda quando o site é atualizado, então é procurado nos scripts da página."""
    h = http(_BARBOSA + "/tabloides")
    ids = []
    for c in sorted(set(re.findall(r'/_next/static/chunks/[^"\'\s\\]+\.js', h))):
        js = http(_BARBOSA + c)
        if "api2/ecommerce" in js or "handleUnauthorized" in js:
            ids += re.findall(r'\)\("([0-9a-f]{40})"\)', js)
    for action in dict.fromkeys(ids):
        req = urllib.request.Request(_BARBOSA + "/tabloides", data=json.dumps(["https://api-barbosa.applay.tech/"]).encode(),
                                     headers={"User-Agent": UA, "Accept": "text/x-component", "Next-Action": action,
                                              "Content-Type": "text/plain;charset=UTF-8", "Origin": _BARBOSA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                for linha in r.read().decode("utf-8", "replace").splitlines():
                    m = re.search(r'"token":"([^"]+)"', linha)
                    if m:
                        return m.group(1)
        except urllib.error.HTTPError:
            continue
    raise RuntimeError("não achei o token de acesso do site do Barbosa")


def folhetos_barbosa():
    token = _token_barbosa()
    api = lambda rota, corpo: http_json(_BARBOSA_API + rota, corpo, {"x-access-token": token, "Origin": _BARBOSA})
    hoje = date.today()
    out = []
    for t in api("enav/listar_tabloides", {"session": {}}).get("data") or []:
        fim = ""
        m = re.match(r"(\d{1,2})/(\d{1,2})", t.get("dataFinal") or "")
        if m:
            try:
                fim = date(hoje.year, int(m.group(2)), int(m.group(1))).isoformat()
            except ValueError:
                pass
            if fim and fim < hoje.isoformat():
                continue
        arquivos = (api("enav/tabloide", {"tabloideId": t["_id"]}).get("data") or {}).get("files") or []
        urls = [a["url"] for a in arquivos if a.get("url")] or ([t["url"]] if t.get("url") else [])
        for i, u in enumerate(urls, 1):
            out.append(_folheto("Barbosa", (t.get("nome") or "Tabloide").strip(), u, pagina=i,
                                loja=f"{len(t.get('lojasId') or [])} lojas",
                                validade=f"De {t.get('dataInicial', '')} a {t.get('dataFinal', '')}", fim=fim))
    return out


def todos_folhetos(loja_assai="Mooca", loja_assai_id=None):
    out, erros = [], {}
    for nome, f in (("Assaí", lambda: folhetos_assai(loja_assai, loja_assai_id)), ("Roldão", folhetos_roldao),
                    ("Akki", folhetos_akki), ("Lopes", folhetos_lopes), ("Max Atacadista", folhetos_max),
                    ("Barbosa", folhetos_barbosa)):
        try:
            out += f()
        except Exception as e:  # uma rede fora do ar não derruba as outras
            erros[nome] = str(e)
    return out, erros
