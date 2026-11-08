#!/bin/sh
# Entrada do contêiner: garante que a pasta de dados existe e tem dono, depois sobe o servidor.
set -e

mkdir -p /dados 2>/dev/null || true

# se o volume foi montado como root, o usuário `ofertas` não consegue escrever
if [ ! -w /dados ]; then
  echo "aviso: /dados não é gravável pelo usuário ofertas; rode com -v nome:/dados (volume nomeado)" >&2
fi

exec /app/venv/bin/python /app/servidor.py "$@"
