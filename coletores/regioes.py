"""Regiões do app: cada uma tem seu CEP padrão e suas redes."""

REGIOES = {
    "sp": {
        "nome": "SP - São Paulo",
        "cep": "01310100",
        "online": ["Pão de Açúcar", "Extra", "Carrefour", "Tenda Atacado", "Sonda", "Atacadão", "Sam's Club", "Mambo",
                   "Oba Hortifruti", "Coop", "Savegnago", "Zaffari", "Swift"],
        "folhetos": ["Assaí", "Roldão", "Akki", "Lopes", "Max Atacadista", "Barbosa"],
    },
    "paulinia": {
        "nome": "SP - Paulínia",
        "cep": "13140320",
        "online": ["Pague Menos", "BOA", "Covabra"],
        "folhetos": ["Assaí"],   # o Poupe Real só divulga ofertas no app e no Instagram
    },
}


def regiao_do_mercado(mercado):
    for rid, r in REGIOES.items():
        if mercado in r["online"] or mercado in r["folhetos"]:
            return rid
    return "sp"
