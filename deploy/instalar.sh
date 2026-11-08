#!/usr/bin/env bash
# Instala o Ofertas SP num Debian/Ubuntu, como serviço do systemd.
#
#   sudo bash instalar.sh
#
# O que ele faz:
#   1. instala python3 e as dependências do sistema;
#   2. cria o usuário de serviço `ofertas` (sem login, sem shell);
#   3. copia o programa para /opt/ofertas-sp e os dados para /var/lib/ofertas-sp;
#   4. cria o serviço systemd `ofertas-sp`, que sobe no boot e reinicia sozinho;
#   5. deixa o .env pronto para você preencher (Telegram, chave de IA).
#
# Rodar de novo é seguro: atualiza o código e mantém os dados.

set -euo pipefail

APP_DIR=/opt/ofertas-sp
DADOS_DIR=/var/lib/ofertas-sp
USUARIO=ofertas
PORTA=${OFERTAS_PORTA:-8765}
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode com sudo: sudo bash instalar.sh" >&2
  exit 1
fi

echo "==> Dependências do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ca-certificates curl >/dev/null

echo "==> Usuário de serviço"
if ! id "$USUARIO" >/dev/null 2>&1; then
  useradd --system --home "$DADOS_DIR" --shell /usr/sbin/nologin "$USUARIO"
fi

echo "==> Pastas"
mkdir -p "$APP_DIR" "$DADOS_DIR"
# os dados ficam fora do código: atualizar o programa nunca apaga histórico nem listas
if [ -f "$APP_DIR/ofertas.db" ] && [ ! -f "$DADOS_DIR/ofertas.db" ]; then
  mv "$APP_DIR/ofertas.db" "$DADOS_DIR/ofertas.db"
fi
if [ -f "$APP_DIR/historico.db" ] && [ ! -f "$DADOS_DIR/historico.db" ]; then
  mv "$APP_DIR/historico.db" "$DADOS_DIR/historico.db"
fi

echo "==> Código"
for item in app.py servidor.py db.py historico.py alertas.py gerar_site.py coletores static; do
  rm -rf "${APP_DIR:?}/$item"
  cp -r "$ORIGEM/$item" "$APP_DIR/"
done

echo "==> Ambiente Python"
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
# o leitor de folhetos com IA é opcional: sem a chave, o app funciona, só não lê as imagens
"$APP_DIR/venv/bin/pip" install --quiet anthropic || echo "   (anthropic não instalou; leitura de folhetos com IA fica desligada)"

echo "==> Arquivo de configuração"
if [ ! -f "$APP_DIR/.env" ]; then
  cat > "$APP_DIR/.env" <<EOF
# Configuração do Ofertas SP. Depois de editar, reinicie: systemctl restart ofertas-sp

# Onde o app escuta. Deixe 127.0.0.1 se for usar nginx/Caddy na frente.
OFERTAS_HOST=0.0.0.0
OFERTAS_PORTA=$PORTA

# Horário da coleta diária (horário de Brasília)
OFERTAS_HORA=6
OFERTAS_MINUTO=0

# CEP usado para regionalizar os preços
OFERTAS_CEP=01310-100

# Endereço do proxy no Cloudflare (o mesmo que o site já usa)
OFERTAS_PROXY=

# Leitura dos folhetos com IA (opcional)
GEMINI_API_KEY=
# ANTHROPIC_API_KEY=

# Alertas no Telegram: DESLIGADO por padrão. Para ligar, ponha ALERTAS_TELEGRAM=1 e preencha
# o token (bot no @BotFather) e o chat_id (fale com @userinfobot). Sem a chave em 1, nada é enviado.
ALERTAS_TELEGRAM=0
TELEGRAM_TOKEN=
TELEGRAM_CHAT=

# Código da família que recebe o resumo semanal (aparece na aba Família)
OFERTAS_FAMILIA=
EOF
  chmod 600 "$APP_DIR/.env"
  echo "   criado $APP_DIR/.env — preencha depois"
else
  echo "   mantido o .env existente"
fi

echo "==> Serviço systemd"
cat > /etc/systemd/system/ofertas-sp.service <<EOF
[Unit]
Description=Ofertas SP - comparador de precos dos mercados
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USUARIO
Group=$USUARIO
WorkingDirectory=$APP_DIR
Environment="OFERTAS_DB=$DADOS_DIR/ofertas.db"
Environment="OFERTAS_HIST=$DADOS_DIR/historico.db"
Environment="TZ=America/Sao_Paulo"
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=-$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/servidor.py
Restart=always
RestartSec=10
# a coleta mexe em rede e escreve em disco; o resto pode ficar preso
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$DADOS_DIR $APP_DIR

[Install]
WantedBy=multi-user.target
EOF

chown -R "$USUARIO:$USUARIO" "$APP_DIR" "$DADOS_DIR"
systemctl daemon-reload
systemctl enable ofertas-sp >/dev/null
systemctl restart ofertas-sp
sleep 2

echo
if systemctl is-active --quiet ofertas-sp; then
  echo "Pronto. Ofertas SP está rodando."
else
  echo "O serviço não subiu. Veja o motivo com:  journalctl -u ofertas-sp -n 50 --no-pager"
  exit 1
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<EOF

  Endereço local:   http://${IP:-127.0.0.1}:$PORTA
  Configuração:     $APP_DIR/.env
  Dados (backup):   $DADOS_DIR
  Logs:             journalctl -u ofertas-sp -f

  Comandos úteis:
    systemctl restart ofertas-sp      reinicia depois de mexer no .env
    systemctl status ofertas-sp       estado atual
    journalctl -u ofertas-sp -n 100   últimas linhas do log

  Próximos passos:
    1. Edite $APP_DIR/.env (CEP, proxy, Telegram) e reinicie.
    2. Coloque um nginx ou Caddy na frente com HTTPS se for abrir para a internet.
       O app não tem login: quem chega, entra. Para uso da família, prefira
       Cloudflare Tunnel ou Tailscale em vez de expor a porta.
    3. A primeira coleta roda no horário configurado. Para não esperar:
       sudo -u $USUARIO $APP_DIR/venv/bin/python $APP_DIR/servidor.py --coletar-agora --sem-agendador
EOF
