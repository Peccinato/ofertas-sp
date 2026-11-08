"""Alertas de preço: confere os alvos da família depois da coleta e avisa no Telegram.

Configuração (variáveis de ambiente, ou .env lido pelo servidor.py):
    ALERTAS_TELEGRAM   "1" liga o envio pelo Telegram. Desligado por padrão.
    TELEGRAM_TOKEN     token do bot, criado no @BotFather
    TELEGRAM_CHAT      chat padrão que recebe os avisos (o seu, ou o do grupo da família)

O Telegram está DESLIGADO por decisão do dono (2026-11-08). A função continua inteira no código:
para ligar, defina ALERTAS_TELEGRAM=1 junto com o token e o chat, e reinicie o serviço. Os alertas
continuam sendo criados e conferidos normalmente enquanto isso; só não sai mensagem.

Cada alerta pode ter o próprio `telegram_chat`, então cada pessoa da casa recebe o seu.

Regra de ouro: um alerta só dispara de novo depois de `DIAS_SILENCIO` dias, ou se o preço cair
outros 5% abaixo do último aviso. Sem isso o Telegram vira spam e a família desliga as notificações,
que é o pior resultado possível.
"""
import json
import os
import time
import urllib.parse
import urllib.request

import db
import historico

DIAS_SILENCIO = float(os.environ.get("ALERTA_SILENCIO_DIAS") or "3")
QUEDA_EXTRA = 0.05   # 5% mais barato que o último aviso fura o silêncio

# Liga/desliga o envio. Desligado por padrão: o app funciona sem Telegram nenhum.
TELEGRAM_LIGADO = os.environ.get("ALERTAS_TELEGRAM", "").strip().lower() in ("1", "true", "sim", "on")


def _brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def telegram_configurado():
    """Só é verdadeiro com a chave ligada E as credenciais presentes."""
    return TELEGRAM_LIGADO and bool(os.environ.get("TELEGRAM_TOKEN"))


def enviar_telegram(texto, chat=None, silencioso=False):
    """Manda uma mensagem. Devolve (ok, detalhe). Nunca levanta exceção."""
    if not TELEGRAM_LIGADO:
        return False, "Telegram desligado (ALERTAS_TELEGRAM não está em 1)"
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = (chat or os.environ.get("TELEGRAM_CHAT", "")).strip()
    if not token:
        return False, "TELEGRAM_TOKEN não configurado"
    if not chat:
        return False, "nenhum chat de destino"
    dados = urllib.parse.urlencode({
        "chat_id": chat, "text": texto, "parse_mode": "HTML",
        "disable_notification": "true" if silencioso else "false",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=dados)
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
        if resp.get("ok"):
            return True, "enviado"
        return False, resp.get("description", "erro do Telegram")
    except Exception as e:   # noqa: BLE001
        return False, str(e)[:200]


def _melhor_preco(nome, termo="", mercado=""):
    """Menor preço atual do produto, entre os mercados da base (prefere o mercado do alerta, se houver)."""
    candidatos = db.consultar(termo or nome, limite=400, max_idade_h=24 * 10)
    if mercado:
        proprios = [p for p in candidatos if p["mercado"] == mercado]
        if proprios:
            candidatos = proprios
    if not candidatos:
        return None
    # compara por kg/L quando os dois têm a mesma unidade; senão pelo preço da embalagem
    return min(candidatos, key=lambda p: p.get("preco_unidade") or p["preco"])


def _mensagem(alerta, p, avaliacao):
    linhas = [
        f"🔔 <b>{alerta['nome']}</b>",
        f"<b>{_brl(p['preco'])}</b> no <b>{p['mercado']}</b>"
        + (f" ({_brl(p['preco_unidade'])}/{p['unidade']})" if p.get("preco_unidade") else ""),
        f"Seu alvo era {_brl(alerta['alvo'])}.",
    ]
    v = avaliacao.get("veredito")
    if v == "boa":
        linhas.append(f"✅ Promoção de verdade: {avaliacao['motivo']}.")
    elif v == "inflada":
        linhas.append(f"⚠️ Cuidado: {avaliacao['motivo']}.")
    elif v == "cara":
        linhas.append(f"📈 Ainda está {avaliacao['motivo']}.")
    elif v == "normal":
        linhas.append(f"➖ Preço {avaliacao['motivo']}.")
    if p.get("url"):
        linhas.append(f'<a href="{p["url"]}">Ver no site</a>')
    return "\n".join(linhas)


def checar_alertas(dia=None, avisar=None):
    """Percorre os alertas ligados e avisa quem bateu o alvo. Devolve o relatório da rodada.

    Com o Telegram desligado, nada é enviado, mas a rodada continua acontecendo: os preços são
    atualizados, os alvos são conferidos e o relatório volta com `telegram: False` e a lista de
    `bateram` (o que teria sido avisado). Assim, no dia em que o Telegram for ligado, o histórico
    de preços e os alvos já estão em dia.
    """
    avisar = avisar or enviar_telegram
    alertas = db.alertas_ativos()
    agora = time.time()
    disparos, silenciados, sem_preco, bateram = [], 0, 0, []

    for a in alertas:
        p = _melhor_preco(a["nome"], a.get("termo") or a["nome"], a.get("mercado") or "")
        if not p:
            sem_preco += 1
            continue
        db.alerta_atualizar(a["id"], ultimo_preco=p["preco"])
        if p["preco"] > a["alvo"]:
            continue

        # silêncio: não repetir o mesmo aviso todo dia
        ultimo = a.get("ultimo_aviso_em") or 0
        recente = (agora - ultimo) < DIAS_SILENCIO * 86400
        caiu_mais = a.get("ultimo_preco") and p["preco"] <= a["ultimo_preco"] * (1 - QUEDA_EXTRA)
        if recente and not caiu_mais:
            silenciados += 1
            continue

        av = historico.avaliar_oferta(p["mercado"], p["nome"], p["preco"], p.get("preco_de"))
        bateram.append({"alerta": a["id"], "nome": a["nome"], "mercado": p["mercado"],
                        "preco": p["preco"], "alvo": a["alvo"], "veredito": av.get("veredito")})
        ok, detalhe = avisar(_mensagem(a, p, av), a.get("telegram_chat") or None)
        if ok:
            db.alerta_atualizar(a["id"], ultimo_aviso_em=agora, ultimo_preco=p["preco"])
            disparos.append({"alerta": a["id"], "nome": a["nome"], "mercado": p["mercado"],
                             "preco": p["preco"], "alvo": a["alvo"], "veredito": av.get("veredito")})
        elif TELEGRAM_LIGADO:
            disparos.append({"alerta": a["id"], "nome": a["nome"], "erro": detalhe})

    return {"alertas": len(alertas), "disparos": disparos, "bateram": bateram,
            "silenciados": silenciados, "sem_preco": sem_preco,
            "telegram": telegram_configurado()}


def resumo_semanal(familia, dias=7):
    """As melhores ofertas da semana entre os itens que a família costuma comprar.

    A lista de compras compartilhada é o retrato do que a casa consome, então é ela que define
    o que entra no resumo.
    """
    fam = db.familia_ler(familia)
    if not fam:
        return None, "família não encontrada"
    itens = (fam["dados"].get("lista") or []) + (fam["dados"].get("favoritos") or [])
    termos = sorted({(i.get("texto") or i.get("nome") or "").strip() for i in itens} - {""})
    if not termos:
        return None, "lista vazia"

    ofertas = []
    for t in termos:
        for p in db.consultar(t, limite=60, max_idade_h=24 * dias):
            av = historico.avaliar_oferta(p["mercado"], p["nome"], p["preco"], p.get("preco_de"))
            if av.get("veredito") == "boa":
                ofertas.append({"nome": p["nome"], "mercado": p["mercado"], "preco": p["preco"],
                                "motivo": av.get("motivo"), "desconto_real_pct": av.get("desconto_real_pct"),
                                "url": p.get("url", "")})
    ofertas.sort(key=lambda x: -(x["desconto_real_pct"] or 0))
    return {"itens": len(termos), "ofertas": ofertas[:15]}, None


def texto_resumo_semanal(familia):
    r, erro = resumo_semanal(familia)
    if erro:
        return None
    if not r["ofertas"]:
        return ("🛒 <b>Resumo da semana</b>\nNenhuma promoção de verdade entre os itens de casa "
                "esta semana. Vale a pena esperar.")
    linhas = ["🛒 <b>Resumo da semana</b>", f"Promoções reais entre os {r['itens']} itens da sua lista:", ""]
    for o in r["ofertas"]:
        linhas.append(f"• <b>{o['nome']}</b> — {_brl(o['preco'])} no {o['mercado']} ({o['motivo']})")
    return "\n".join(linhas)
