"""Testa se cada rede responde a partir desta máquina (usado no GitHub Actions)."""
import sys
import time

from coletores.folhetos import folhetos_akki, folhetos_assai, folhetos_lopes, folhetos_max, folhetos_roldao
from coletores.sites import fontes

sys.stdout.reconfigure(encoding="utf-8")
ok = 0
linhas = ["| Rede | Resultado | Exemplo |", "|---|---|---|"]
for nome, f in fontes():
    t = time.time()
    try:
        r = f("arroz 5kg", 10)
        ex = f"{r[0].nome[:40]} — R$ {r[0].preco:.2f}" if r else ""
        linhas.append(f"| {nome} | ✅ {len(r)} produtos ({time.time() - t:.1f}s) | {ex} |")
        ok += bool(r)
    except Exception as e:
        linhas.append(f"| {nome} | ❌ {type(e).__name__}: {str(e)[:80]} | |")
FOLHETOS = (("Assaí (folhetos)", lambda: folhetos_assai("Mooca")), ("Roldão (folhetos)", folhetos_roldao),
            ("Akki (folhetos)", folhetos_akki), ("Lopes (folhetos)", folhetos_lopes),
            ("Max Atacadista (folhetos)", folhetos_max))
for nome, f in FOLHETOS:
    try:
        r = f()
        linhas.append(f"| {nome} | ✅ {len(r)} páginas | {r[0]['validade'] if r else ''} |")
        ok += bool(r)
    except Exception as e:
        linhas.append(f"| {nome} | ❌ {type(e).__name__}: {str(e)[:80]} | |")

print("\n".join(linhas))
print(f"\n{ok} de {len(fontes()) + len(FOLHETOS)} fontes funcionando")
