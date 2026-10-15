"""Coletores que buscam preços direto nas lojas online das redes."""
import html
import re
from urllib.parse import quote

from .base import Produto, http, http_json

# Lojas na plataforma VTEX (mesma API pública de busca)
VTEX = {
    "Atacadão": "www.atacadao.com.br",
    "Sam's Club": "www.samsclub.com.br",
    "Mambo": "www.mambo.com.br",
    "Oba Hortifruti": "www.obahortifruti.com.br",
    "Coop": "www.coopsupermercado.com.br",
    "Savegnago": "www.savegnago.com.br",
    "Zaffari": "www.zaffari.com.br",
    "Swift": "www.swift.com.br",
}


# Região do usuário (definida pelo CEP em coletores/local.py): host VTEX -> regionId, loja do Pão de Açúcar
REGIAO = {"vtex": {}, "gpa_loja": None}


def buscar_vtex(mercado, host, termo, n=24):
    url = f"https://{host}/api/io/_v/api/intelligent-search/product_search/?query={quote(termo)}&count={n}&locale=pt-BR"
    if REGIAO["vtex"].get(host):
        url += "&regionId=" + quote(REGIAO["vtex"][host])
    d = http_json(url)
    out = []
    for p in d.get("products", []):
        try:
            item = p["items"][0]
            oferta = item["sellers"][0]["commertialOffer"]
        except (KeyError, IndexError):
            continue
        preco = oferta.get("Price") or 0
        if not preco or not oferta.get("AvailableQuantity", 1):
            continue
        img = (item.get("images") or [{}])[0].get("imageUrl", "")
        out.append(Produto(
            mercado=mercado, nome=p.get("productName", ""), preco=preco,
            preco_de=oferta.get("ListPrice"), marca=p.get("brand", ""), imagem=img,
            url=f"https://{host}/{p.get('linkText', '')}/p",
        ).finalizar())
    return out


def buscar_pao_de_acucar(termo, n=24):
    body = {"terms": termo, "page": 1, "sortBy": "relevance", "resultsPerPage": n, "allowRedirect": False,
            "storeId": REGIAO["gpa_loja"] or 461, "department": "ecom", "customerPlus": True, "partner": "linx"}
    d = http_json("https://api.vendas.gpa.digital/pa/search/search", body)
    out = []
    for p in d.get("products", []):
        if not p.get("stock") or not p.get("price"):
            continue
        extra = ""
        promo = p.get("productPromotion") or {}
        if promo.get("promotionQuantityBuy") and promo.get("promotionQuantityPayFor"):
            extra = f"leve {promo['promotionQuantityBuy']} pague {promo['promotionQuantityPayFor']}"
        img = (p.get("productImages") or [""])[0]
        if img.startswith("/"):
            img = "https://static.paodeacucar.com" + img
        out.append(Produto(
            mercado="Pão de Açúcar", nome=p.get("name", ""), preco=p["price"], preco_de=p.get("priceFrom"),
            marca=p.get("brand", ""), imagem=img, url=p.get("urlDetails", ""), extra=extra,
            validade=(promo.get("endDate") or "")[:10],
        ).finalizar())
    return out


def buscar_tenda(termo, n=24):
    d = http_json(f"https://api.tendaatacado.com.br/api/public/store/search?query={quote(termo)}&page=1&order=relevance&save=true")
    out = []
    for p in d.get("products", [])[:n]:
        if p.get("availability") != "in_stock" or not p.get("price"):
            continue
        preco, preco_de, extra, validade = p["price"], None, "", ""
        # promoção sem restrição de app/cartão vale como preço; as demais viram observação
        for pr in p.get("promotions") or []:
            titulo = (pr.get("restriction") or {}).get("title", "")
            if pr.get("price") and pr["price"] < preco:
                extra = f"R$ {pr['price']:.2f} ({titulo})".replace(".", ",") if titulo else extra
        atacado = p.get("wholesalePrices") or []
        if atacado:
            a = min(atacado, key=lambda w: w.get("price", 1e9))
            if a.get("price") and a.get("minQuantity"):
                extra = (extra + "; " if extra else "") + f"a partir de {a['minQuantity']} un: R$ {a['price']:.2f}".replace(".", ",")
        out.append(Produto(
            mercado="Tenda Atacado", nome=p.get("name", ""), preco=preco, preco_de=preco_de,
            marca=p.get("brand", ""), imagem=p.get("thumbnail", ""), url=p.get("url", ""),
            extra=extra, validade=validade,
        ).finalizar())
    return out


_SONDA_ITEM = re.compile(
    r'item_id:\s*"(\d+)",\s*item_name:\s*"(.*?)",.*?discount:\s*([\d.]+),.*?price:\s*([\d.]+)', re.S)


def buscar_sonda(termo, n=24):
    base = "https://www.sondadelivery.com.br"
    h = http(f"{base}/delivery/busca/{quote(termo)}", timeout=30)
    # a lista de produtos da busca vem num evento do Google Analytics embutido no HTML
    i = h.find('"view_item_list"')
    lista = h[i: h.find("</script>", i)] if i >= 0 else ""
    out = []
    for pid, nome, desconto, preco in _SONDA_ITEM.findall(lista)[:n]:
        preco, desconto = float(preco), float(desconto)
        link = re.search(rf'href="(/delivery/produto/[^"]+/{pid})"', h)
        img = ""
        if link:
            m = re.search(r'(?:data-srcset|data-src|src)="(https?://[^"]+\.(?:jpe?g|png|webp)[^"]*)"', h[link.end(): link.end() + 3000], re.I)
            img = m.group(1) if m else ""
        out.append(Produto(
            mercado="Sonda", nome=html.unescape(nome), preco=preco,
            preco_de=round(preco + desconto, 2) if desconto else None, imagem=img,
            url=base + link.group(1) if link else f"{base}/delivery/busca/{quote(termo)}",
        ).finalizar())
    return out


def fontes():
    """Lista de (nome do mercado, função de busca)."""
    lista = [("Pão de Açúcar", buscar_pao_de_acucar), ("Tenda Atacado", buscar_tenda), ("Sonda", buscar_sonda)]
    for nome, host in VTEX.items():
        lista.append((nome, lambda termo, n=24, _m=nome, _h=host: buscar_vtex(_m, _h, termo, n)))
    return lista
