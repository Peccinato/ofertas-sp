#!/usr/bin/env python3
"""Servidor de produção do Ofertas SP, pensado para rodar num Debian (VPS, mini PC, Raspberry).

Diferenças em relação ao `app.py`:
  - escuta em 0.0.0.0 e atrás de um proxy (nginx/Caddy), respeitando X-Forwarded-For;
  - roda a coleta sozinho todo dia no horário configurado, sem depender de cron;
  - registra cada execução no banco (é o que o /api/saude lê para dizer se a coleta falhou);
  - dispara os alertas de preço e o resumo semanal depois da coleta;
  - desliga limpo no SIGTERM (systemd e Docker mandam esse sinal).

Uso:
    python3 servidor.py                  # porta 8765, coleta às 06:00
    python3 servidor.py --porta 8080 --hora 5
    python3 servidor.py --sem-agendador  # só serve o app (coleta por cron externo)

Variáveis de ambiente (ou arquivo .env ao lado deste arquivo):
    OFERTAS_PORTA, OFERTAS_HORA, OFERTAS_HOST
    OFERTAS_CEP, OFERTAS_PROXY, GEMINI_API_KEY, ANTHROPIC_API_KEY
    TELEGRAM_TOKEN, TELEGRAM_CHAT
    OFERTAS_FAMILIA          código da família que recebe o resumo semanal
    OFERTAS_ADMIN_TOKEN      se definido, /api/saude e /api/alertas/checar exigem ?token=
"""
import argparse
import os
import signal
import sys
import threading
import time
import traceback

PASTA = os.path.dirname(os.path.abspath(__file__))
os.chdir(PASTA)
sys.path.insert(0, PASTA)


def carregar_env():
    """Lê um .env simples (CHAVE=valor), sem sobrescrever o que já veio do ambiente."""
    caminho = os.path.join(PASTA, ".env")
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env()

import alertas                      # noqa: E402
import db                           # noqa: E402
import historico                    # noqa: E402
from http.server import ThreadingHTTPServer   # noqa: E402

parado = threading.Event()
ultima_coleta = {"quando": 0.0, "ok": None, "detalhe": ""}


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def coletar(completo=True):
    """Roda a coleta inteira e registra o resultado. Devolve True/False."""
    import app as appmod

    id_exec = db.execucao_iniciar("coleta")
    inicio = time.time()
    log("coleta iniciada")
    try:
        erros = appmod.atualizar_folhetos() or {}
        log(f"folhetos: {len(db.listar_folhetos())} páginas, {len(erros)} falhas")

        falhas = {}
        for i, termo in enumerate(appmod.CESTA, 1):
            if parado.is_set():
                raise RuntimeError("interrompido")
            for mercado, erro in appmod.buscar_ao_vivo(termo, n=40).items():
                falhas.setdefault(mercado, []).append(erro)
            if i % 10 == 0:
                log(f"  {i}/{len(appmod.CESTA)} termos")
        log(f"preços: {sum(c['n'] for c in db.contagens())} no banco, {len(falhas)} redes com falha")

        # leitura dos folhetos novos, se houver chave de IA
        if appmod.extrator_ia.disponivel()[0]:
            lidos = 0
            for f in db.listar_folhetos():
                if f["status"] != "lido" and not parado.is_set():
                    try:
                        appmod.ler_folheto(f["imagem"])
                        lidos += 1
                    except Exception as e:   # noqa: BLE001
                        log(f"  folheto {f['imagem'][-40:]}: {str(e)[:120]}")
            log(f"folhetos lidos com IA: {lidos}")

        # o histórico é podado uma vez por dia, depois de gravar
        removidos = historico.podar()
        if removidos:
            log(f"histórico: {removidos} linhas antigas removidas")

        # alertas: só faz sentido conferir depois de ter preço novo
        try:
            r = alertas.checar_alertas()
            log(f"alertas: {len(r['disparos'])} aviso(s), {r['silenciados']} em silêncio, "
                f"{r['sem_preco']} sem preço")
        except Exception as e:   # noqa: BLE001
            log(f"  alertas falharam: {str(e)[:160]}")

        dur = time.time() - inicio
        detalhe = f"{sum(c['n'] for c in db.contagens())} preços em {dur:.0f}s"
        db.execucao_terminar(id_exec, True, detalhe)
        ultima_coleta.update(quando=time.time(), ok=True, detalhe=detalhe)
        log(f"coleta concluída em {dur:.0f}s")
        return True
    except Exception as e:   # noqa: BLE001
        detalhe = f"{type(e).__name__}: {str(e)[:300]}"
        db.execucao_terminar(id_exec, False, detalhe)
        ultima_coleta.update(quando=time.time(), ok=False, detalhe=detalhe)
        log(f"COLETA FALHOU: {detalhe}")
        traceback.print_exc()
        # avisa no Telegram: uma coleta que falha em silêncio é pior que uma que avisa
        try:
            alertas.enviar_telegram(f"⚠️ <b>Ofertas SP</b>: a coleta de hoje falhou.\n<code>{detalhe}</code>")
        except Exception:   # noqa: BLE001
            pass
        return False


def agendador(hora, minuto, resumo_dia=6):
    """Roda a coleta todo dia no horário pedido, e o resumo semanal nos domingos."""
    log(f"agendador ligado: coleta diária às {hora:02d}:{minuto:02d} (horário local)")
    while not parado.is_set():
        agora = time.localtime()
        alvo = time.mktime((agora.tm_year, agora.tm_mon, agora.tm_mday, hora, minuto, 0, 0, 0, -1))
        if alvo <= time.time():
            alvo += 86400
        espera = alvo - time.time()
        log(f"próxima coleta em {espera / 3600:.1f}h")
        if parado.wait(espera):
            return
        if parado.is_set():
            return
        coletar()
        # domingo: resumo da semana para a família
        familia = os.environ.get("OFERTAS_FAMILIA", "").strip().upper()
        if familia and time.localtime().tm_wday == resumo_dia:
            texto = alertas.texto_resumo_semanal(familia)
            if texto:
                ok, det = alertas.enviar_telegram(texto)
                log(f"resumo semanal: {det}")


def main():
    ap = argparse.ArgumentParser(description="Ofertas SP - servidor de produção")
    ap.add_argument("--porta", type=int, default=int(os.environ.get("OFERTAS_PORTA") or 8765))
    ap.add_argument("--host", default=os.environ.get("OFERTAS_HOST") or "0.0.0.0")
    ap.add_argument("--hora", type=int, default=int(os.environ.get("OFERTAS_HORA") or 6))
    ap.add_argument("--minuto", type=int, default=int(os.environ.get("OFERTAS_MINUTO") or 0))
    ap.add_argument("--sem-agendador", action="store_true", help="não coleta sozinho (use cron)")
    ap.add_argument("--coletar-agora", action="store_true", help="coleta uma vez e continua servindo")
    args = ap.parse_args()

    db.criar()
    historico.criar()
    import app as appmod
    import json
    appmod.local.aplicar(json.loads(db.config("regiao", "null") or "null"))

    if args.coletar_agora:
        threading.Thread(target=coletar, daemon=True).start()
    elif not args.sem_agendador:
        threading.Thread(target=agendador, args=(args.hora, args.minuto), daemon=True).start()

    ThreadingHTTPServer.allow_reuse_address = True
    try:
        srv = ThreadingHTTPServer((args.host, args.porta), appmod.Handler)
    except OSError as e:
        sys.exit(f"não consegui abrir a porta {args.porta}: {e}")

    def encerrar(signum, frame):
        log(f"sinal {signum} recebido, encerrando")
        parado.set()
        threading.Thread(target=srv.shutdown, daemon=True).start()

    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, encerrar)
        except (ValueError, OSError):
            pass

    h = historico.contagens()
    log(f"servindo em http://{args.host}:{args.porta}")
    log(f"histórico: {h['n']} preços em {h['d']} dia(s) ({h['ini']} a {h['fim']})")
    log(f"telegram: {'ligado' if alertas.telegram_configurado() else 'desligado (sem TELEGRAM_TOKEN)'}")
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        log("encerrado")


if __name__ == "__main__":
    main()
