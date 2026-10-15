"""Utilitários compartilhados pelos coletores."""
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"


def http(url, data=None, headers=None, timeout=20, tentativas=2):
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"}
    h.update(headers or {})
    for i in range(tentativas):
        req = urllib.request.Request(url, data=data, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8-sig", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tentativas - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == tentativas - 1:
                raise
        time.sleep(1.5)


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
