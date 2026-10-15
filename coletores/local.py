"""Localização por CEP: endereço, coordenadas, região de entrega de cada rede e Assaí mais próximo."""
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from .base import http, http_json
from .sites import REGIAO, VTEX

# coordenada genérica que a BrasilAPI devolve quando não sabe a exata (centro de SP)
_CENTRO_GENERICO = ("-23.5475", "-46.6361")


def limpar_cep(cep):
    c = re.sub(r"\D", "", cep or "")
    if len(c) != 8:
        raise ValueError("CEP deve ter 8 números")
    return c


def resolver_cep(cep):
    """CEP -> {cep, rua, bairro, cidade, uf, lat, lon}."""
    cep = limpar_cep(cep)
    end = {"cep": cep, "rua": "", "bairro": "", "cidade": "", "uf": "", "lat": None, "lon": None}
    try:
        d = http_json(f"https://brasilapi.com.br/api/cep/v2/{cep}")
        end.update(rua=d.get("street") or "", bairro=d.get("neighborhood") or "", cidade=d.get("city") or "", uf=d.get("state") or "")
        c = (d.get("location") or {}).get("coordinates") or {}
        if c.get("latitude") and (c.get("latitude"), c.get("longitude")) != _CENTRO_GENERICO:
            end.update(lat=float(c["latitude"]), lon=float(c["longitude"]))
    except Exception:
        d = http_json(f"https://viacep.com.br/ws/{cep}/json/")
        if d.get("erro"):
            raise ValueError("CEP não encontrado")
        end.update(rua=d.get("logradouro", ""), bairro=d.get("bairro", ""), cidade=d.get("localidade", ""), uf=d.get("uf", ""))
    if end["lat"] is None and end["cidade"]:
        # coordenada pelo OpenStreetMap (rua + cidade, ou só bairro + cidade)
        for q in ({"street": end["rua"], "city": end["cidade"], "state": end["uf"]},
                  {"q": f"{end['bairro']}, {end['cidade']}, {end['uf']}"}):
            try:
                r = http_json("https://nominatim.openstreetmap.org/search?" + urlencode({**q, "country": "Brasil", "format": "json", "limit": 1}))
                if r:
                    end.update(lat=float(r[0]["lat"]), lon=float(r[0]["lon"]))
                    break
            except Exception:
                pass
    return end


def _regiao_vtex(host, cep):
    try:
        r = http_json(f"https://{host}/api/checkout/pub/regions?country=BRA&postalCode={cep}")
        return host, (r[0]["id"] if r else "")
    except Exception:
        return host, ""


def _loja_gpa(cep):
    try:
        d = http_json(f"https://api.vendas.gpa.digital/pa/delivery/options?zipCode={cep}")
        tipos = (d.get("content") or {}).get("deliveryTypes") or []
        if tipos:
            return {"id": tipos[0]["storeid"], "nome": tipos[0].get("storeName", "")}
    except Exception:
        pass
    return None


def regioes(cep):
    """Descobre a região/loja que atende o CEP em cada rede online."""
    with ThreadPoolExecutor(max_workers=10) as ex:
        vtex = dict(ex.map(lambda h: _regiao_vtex(h, cep), VTEX.values()))
        gpa = _loja_gpa(cep)
    return {"vtex": vtex, "gpa": gpa}


def aplicar(reg):
    """Faz os coletores usarem a região salva."""
    REGIAO["vtex"] = dict((reg or {}).get("vtex") or {})
    gpa = (reg or {}).get("gpa")
    REGIAO["gpa_loja"] = gpa["id"] if gpa else None


def lojas_assai():
    """Todas as lojas Assaí do estado de SP com coordenadas (do próprio site)."""
    h = http("https://www.assai.com.br/ofertas")
    k = "jQuery.extend(Drupal.settings,"
    st, _ = json.JSONDecoder().raw_decode(h[h.index(k) + len(k):].lstrip())
    out = []
    for l in st["assai"]["lojas"]:
        try:
            if l.get("uf") == "SP":
                out.append({"nome": l["n"].replace("Assaí ", "").strip(), "id": int(l["loja_id"]),
                            "cidade": l.get("c", ""), "lat": float(l["lat"]), "lon": float(l["lon"])})
        except (KeyError, ValueError):
            pass
    return out


def distancia_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def assai_mais_proximas(lat, lon, n=5):
    lojas = lojas_assai()
    for l in lojas:
        l["km"] = round(distancia_km(lat, lon, l["lat"], l["lon"]), 1)
    return sorted(lojas, key=lambda l: l["km"])[:n]
