# Imagem do Ofertas SP para Debian slim.
#
#   docker build -t ofertas-sp .
#   docker run -d --name ofertas-sp -p 8765:8765 \
#     -v ofertas-dados:/dados \
#     -e OFERTAS_CEP=01310-100 \
#     -e TELEGRAM_TOKEN=... -e TELEGRAM_CHAT=... \
#     ofertas-sp
#
# O volume /dados guarda o banco de produtos, o histórico e as listas da família.
# Sem ele, cada `docker run` novo começa do zero (e o histórico, que é o ativo, se perde).

FROM debian:bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo \
    OFERTAS_DB=/dados/ofertas.db \
    OFERTAS_HIST=/dados/historico.db \
    OFERTAS_HOST=0.0.0.0 \
    OFERTAS_PORTA=8765

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# dependências primeiro: a camada fica em cache quando só o código muda
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /app/venv \
 && /app/venv/bin/pip install --quiet --upgrade pip \
 && /app/venv/bin/pip install --quiet -r /app/requirements.txt \
 && rm -f /app/requirements.txt

COPY app.py servidor.py db.py historico.py alertas.py gerar_site.py /app/
COPY coletores /app/coletores
COPY static /app/static
COPY deploy/entrada.sh /app/entrada.sh
RUN chmod +x /app/entrada.sh \
 && mkdir -p /dados \
 && useradd --system --home /dados --shell /usr/sbin/nologin ofertas \
 && chown -R ofertas:ofertas /app /dados

USER ofertas
VOLUME ["/dados"]
EXPOSE 8765

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/saude', timeout=8).status==200 else 1)"

ENTRYPOINT ["/app/entrada.sh"]
