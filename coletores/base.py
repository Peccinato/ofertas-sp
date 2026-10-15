"""Utilitários compartilhados pelos coletores."""
from http.client import HTTPException
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"


_pelo_proxy = set()   # sites que recusam este computador (ex.: GitHub nos EUA) e passam a ir direto pelo proxy


def _http_direto(url, data, h, timeout, tentativas):
    for i in range(tentativas):
        req = urllib.request.Request(url, data=data, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8-sig", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tentativas - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, HTTPException):
            if i == tentativas - 1:
                raise
        time.sleep(1.5)


def http(url, data=None, headers=None, timeout=20, tentativas=2):
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"}
    h.update(headers or {})
    proxy = os.environ.get("OFERTAS_PROXY", "").rstrip("/")
    host = urllib.parse.urlsplit(url).hostname
    if proxy and host in _pelo_proxy:
        return _http_direto(f"{proxy}/?url={urllib.parse.quote(url, safe='')}", data, h, timeout, tentativas)
    try:
        return _http_direto(url, data, h, timeout, tentativas)
    except (urllib.error.URLError, TimeoutError, ConnectionError, HTTPException) as e:
        # alguns sites bloqueiam servidores fora do Brasil; o proxy do Cloudflare roda em São Paulo
        bloqueio = not isinstance(e, urllib.error.HTTPError) or e.code in (403, 429) or e.code >= 500
        if not (proxy and bloqueio):
            raise
        try:
            resp = _http_direto(f"{proxy}/?url={urllib.parse.quote(url, safe='')}", data, h, timeout, 1)
        except Exception:
            raise e from None
        _pelo_proxy.add(host)
        return resp


def http_json(url, data=None, headers=None, timeout=20):
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        headers = {"Content-Type": "application/json", **(headers or {})}
    return json.loads(http(url, data, headers, timeout))


@dataclass
class Produto:
    mercado: str
    nome: str
    preco: float
    preco_de: float | None = None      # preço "de" (antes do desconto)
    marca: str = ""
    imagem: str = ""
    url: str = ""
    origem: str = "site"               # "site" ou "folheto"
    validade: str = ""
    extra: str = ""                    # ex.: "leve 3 pague 2", "no cartão"
    unidade: str = ""                  # "kg", "L" ou "un"
    preco_unidade: float | None = None # R$ por kg / L / unidade
    desconto: float = field(default=0.0)

    def finalizar(self):
        if self.preco_de and self.preco_de > self.preco > 0:
            self.desconto = round(100 * (1 - self.preco / self.preco_de))
        else:
            self.preco_de = None
        qtd, un = quantidade(self.nome)
        if qtd and self.preco:
            self.unidade = un
            self.preco_unidade = round(self.preco / qtd, 2)
        return self

    def dict(self):
        return asdict(self)


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


_QTD = re.compile(
    r"(?:(\d+)\s*(?:x|un\w*\s*de)\s*)?(\d+(?:[.,]\d+)?)\s*(kg|kilo|g|gr|gramas|mg|l|lt|litros?|ml)\b",
    re.I,
)


def quantidade(nome):
    """Extrai a quantidade total do nome, ex. '12x350ml' -> (4.2, 'L'), 'Arroz 5kg' -> (5, 'kg')."""
    m = None
    for m in _QTD.finditer(sem_acento(nome)):
        pass  # usa a última ocorrência (normalmente o tamanho da embalagem)
    if not m:
        return None, ""
    mult = int(m.group(1)) if m.group(1) else 1
    v = float(m.group(2).replace(",", ".")) * mult
    u = m.group(3).lower()
    if u in ("g", "gr", "gramas"):
        return v / 1000, "kg"
    if u == "mg":
        return None, ""
    if u in ("kg", "kilo"):
        return v, "kg"
    if u == "ml":
        return v / 1000, "L"
    return v, "L"
