# Ofertas SP

App local que junta preços e folhetos das grandes redes de São Paulo e transforma tudo em **produto + preço**, para comparar.

## Como abrir

Dê dois cliques em **`Abrir Ofertas SP.bat`** ou rode:

```
py app.py
```

O navegador abre em http://localhost:8765. Não precisa instalar nada além do Python.

## Versão online (sem PC ligado)

**https://peccinato.github.io/ofertas-sp/**

- **Qualquer CEP, a qualquer hora:** toque em 📍 e digite o CEP. A busca acontece ao vivo nas 11 lojas online, com os preços e a disponibilidade da sua região, e o Assaí mais perto é escolhido automaticamente. O CEP fica salvo no aparelho.
- **Folhetos viram preços:** todo dia às 6h, um robô do GitHub (`.github/workflows/publicar.yml`) baixa os folhetos do Assaí, Roldão, Akki, Lopes e Max e o Gemini lê os produtos e preços. Para atualizar na hora: aba **Actions** do repositório > **Publicar site** > **Run workflow**.
- Favoritos e lista ficam salvos no aparelho (no navegador do celular ou do PC).
- O GitHub pausa tarefas agendadas de repositórios sem nenhuma atividade por 60 dias. Se o site parar de atualizar, é só rodar o workflow manualmente uma vez.

### Como funciona por trás

| Peça | Para quê | Custo |
|---|---|---|
| GitHub Pages | hospeda o site | grátis |
| GitHub Actions | coleta diária de ofertas e folhetos | grátis (repositório público) |
| Cloudflare Worker (`worker/`) | intermediário (proxy) que deixa o site consultar as lojas com o seu CEP; roda na região de São Paulo porque o Assaí só aceita acessos do Brasil | grátis até 100 mil requisições/dia (cada busca usa ~11) |
| Gemini (Google) | lê as imagens dos folhetos | grátis, com cota diária |

**Cota do Gemini:** o plano grátis permite poucas leituras por dia em cada modelo (cerca de 20 no modelo principal). O programa usa o "flash" mais novo e, quando a cota acaba, passa para o "flash-lite". Cada página é lida uma vez só; se a cota acabar, o restante fica para o dia seguinte. Os mercados são intercalados para todos receberem leituras.

**Configurações** (no repositório: Settings > Secrets and variables > Actions):
- Variável `OFERTAS_PROXY`: endereço do proxy (já configurado).
- Variável `OFERTAS_CEP` (opcional): CEP usado só para a aba **Ofertas** e quando o proxy estiver fora do ar. Padrão: 01310-100.
- Segredo `GEMINI_API_KEY`: chave grátis em https://aistudio.google.com/apikey (já configurado).
- Segredo `ANTHROPIC_API_KEY` (opcional): usa o Claude no lugar do Gemini (pago, alguns centavos por página).

**Atualizar o proxy** depois de mudar `worker/proxy.js`: na pasta `worker`, rode `npx.cmd wrangler deploy`.

## Usar no celular (pelo PC)

1. No PC, dê dois cliques em **`Abrir no celular.bat`** e deixe a janela aberta.
2. A janela mostra um endereço como `http://192.168.0.109:8765`. Abra esse endereço no navegador do celular, que precisa estar no mesmo Wi-Fi do PC.
3. Na primeira vez, o Windows pergunta se o Python pode usar a rede: marque **Redes privadas** e clique em **Permitir**. Se a sua rede estiver como "Pública", mude para "Privada" em Configurações > Rede e Internet > Wi-Fi > (sua rede) > Tipo de perfil de rede.

Dica: no celular, use "Adicionar à tela inicial" para ter um ícone de app.

O app fica visível só dentro da sua rede de casa, não na internet.

## O que tem

| Aba | O que faz |
|---|---|
| **Comparar preços** | Busca um produto (ex.: "café 500g") em todas as redes ao mesmo tempo e ordena pelo menor preço por kg/L ou pelo menor preço. Clique numa rede para esconder ou mostrar. |
| **Ofertas** | Junta tudo que está em promoção: preço "de/por", "leve 3 pague 2", preço de atacado e os itens lidos dos folhetos. "Atualizar ofertas" percorre uma cesta de ~40 itens básicos (leva de 1 a 3 min). |
| **★ Favoritos** | Toque na ☆ de qualquer produto para acompanhá-lo. Mostra o preço atual, se subiu ou caiu desde que você favoritou e um produto parecido mais barato em outra rede. |
| **🛒 Lista** | Monte sua lista com quantidades (digitando ou pelo 🛒 de um produto). O app mostra onde cada item sai mais barato e quanto a compra toda sai em cada mercado. |
| **Folhetos** | Mostra os tabloides vigentes do Assaí (escolha sua loja) e do Roldão. Com a IA ligada, "Ler folhetos com IA" transforma cada página em lista de produtos e preços, que passam a aparecer nas outras abas. |

## Redes cobertas

- **Lojas online, com preço exato:** Pão de Açúcar, Extra, Carrefour, Sonda, Tenda Atacado, Atacadão, Sam's Club, Mambo, Oba Hortifruti, Coop, Savegnago, Zaffari e Swift.
- **Folhetos, lidos com IA:** Assaí (todas as lojas de SP), Roldão, Akki (PDF), Lopes, Max Atacadista e Barbosa.

**Não entraram:**
- **Busca de produtos do Barbosa:** a API do site é criptografada de propósito contra robôs; o Barbosa entra pelos tabloides.
- **Carrefour:** só a busca do site (15 produtos por busca, sem ajuste por CEP); a API deles bloqueia robôs.
- **Cercadão:** a página de jornal de ofertas está vazia no momento.
- **Dia, St Marche, Nagumo e Hirota:** não encontrei uma fonte pública de preços.

## Regiões

No topo do app há um seletor de região. Cada região tem suas redes e seu CEP padrão, e guarda o próprio CEP quando você digita outro:

| Região | Lojas online (busca ao vivo) | Folhetos |
|---|---|---|
| **SP - São Paulo** | Pão de Açúcar, Extra, Carrefour, Tenda, Sonda, Atacadão, Sam's Club, Mambo, Oba, Coop, Savegnago, Zaffari, Swift | Assaí, Roldão, Akki, Lopes, Max Atacadista, Barbosa |
| **SP - Paulínia** | Pague Menos, BOA, Covabra | Assaí (loja Paulínia) |

O **Poupe Real** ficou de fora: o site não publica ofertas (elas saem só no app "Clube Poupeiros" e no Instagram).

### Como adicionar uma região

1. Abra `coletores/regioes.py` e copie um dos blocos, por exemplo:
   ```python
   "campinas": {
       "nome": "SP - Campinas",
       "cep": "13010000",            # um CEP real da cidade (só números)
       "online": ["Atacadão", "Covabra", "Pague Menos"],
       "folhetos": ["Assaí"],
   },
   ```
2. Use nos campos `online` e `folhetos` os nomes das redes que o app já conhece (os mesmos que aparecem no site). O Assaí escolhe sozinho a loja mais perto do CEP.
3. Se a rede for **nova**:
   - **Loja VTEX** (a maioria das redes grandes): acrescente uma linha no dicionário `VTEX` em `coletores/sites.py` e em `VTEX_LOJAS` no `static/index.html`, e libere o domínio em `worker/proxy.js`.
   - **Outra plataforma**: precisa de um coletor novo, em Python (`coletores/sites.py` ou `coletores/folhetos.py`) e, para a busca ao vivo, em JavaScript (`AoVivo` no `static/index.html`).
4. Envie para o GitHub. A próxima coleta já inclui a região, e o botão aparece sozinho no site.

## CEP

Clique em **📍** no topo e informe seu CEP. Com ele:
- Pão de Açúcar, Extra, Atacadão, Sam's Club, Mambo, Oba, Coop, Savegnago, Zaffari e Swift mostram o preço e a disponibilidade da sua região. Produto que não é entregue no seu CEP some da lista.
- O Assaí mais próximo é escolhido automaticamente para os folhetos.

Ao trocar de CEP, os preços online salvos são apagados e buscados de novo.

## Ligar a leitura de folhetos com IA (opcional)

1. Crie uma chave em https://console.anthropic.com (é paga por uso, alguns centavos por página de folheto).
2. Instale o pacote com `py -m pip install anthropic`.
3. Defina a chave e abra o app:
   ```
   setx ANTHROPIC_API_KEY "sua-chave-aqui"
   ```
   Depois feche e abra o terminal (ou o .bat) de novo.

Por padrão o modelo é o `claude-opus-5-5`. Para trocar, defina a variável `OFERTAS_MODELO`.

## Atualizar sozinho todo dia

`py app.py --atualizar` coleta tudo sem abrir o navegador. Para agendar no Windows, use o Agendador de Tarefas. Por exemplo, todo dia às 7h:

```
schtasks /create /tn "Ofertas SP" /sc daily /st 07:00 /tr "py \"%CD%\app.py\" --atualizar"
```

## Histórico de preços

Todo dia, quando a coleta termina, cada preço é gravado num banco separado (`historico.db`). Ele fica
**fora** do banco de produtos de propósito: o `gerar_site.py` apaga e recria o `ofertas.db` a cada
execução, e o histórico não pode ir junto.

Com duas semanas de dados o app começa a responder perguntas que antes eram impossíveis:

- **o desconto é de verdade?** o preço de hoje é comparado com a mediana dos últimos 90 dias.
  Se o "de R$ 24,90" anunciado está acima do que o produto costuma custar, o app marca
  **desconto inflado** em vez de comemorar;
- **gráfico de 60 a 120 dias** em cada produto, com a linha da mediana;
- **quedas bruscas**: produtos que caíram 20% ou mais desde a coleta anterior;
- **melhor dia da semana** para comprar cada produto;
- **índice da cesta**: quanto custa a mesma cesta de compras ao longo do tempo.

Os vereditos são: `boa` (15% ou mais abaixo da mediana), `inflada` (o "de" anunciado está acima da
mediana), `cara` (10% ou mais acima), `normal`, e `sem_historico` (menos de 14 dias observados).

Para podar o histórico antigo, defina `OFERTAS_HIST_DIAS` (padrão: 400 dias).

## Lista compartilhada da família (sem login)

Na aba **Família**, toque em "Criar nova". O app gera um código de 12 caracteres (ex.:
`K7M2QX9PBR4T`) e a partir daí favoritos e lista de compras vão para o servidor. Quem tiver o código
entra e vê a mesma lista.

O código usa um alfabeto sem `0/O/1/I/L` justamente para poder ser lido em voz alta ou por mensagem
sem confusão. Se duas pessoas editarem ao mesmo tempo, a segunda recebe um aviso de conflito com a
versão da outra em vez de sobrescrever.

**Não tem senha.** Quem tem o código, entra. Para revogar o acesso de alguém, crie uma família nova
e passe o código novo para quem deve continuar.

## Alertas de preço

Os alertas funcionam **sem Telegram**. Você define produto + preço-alvo na aba Família, o app
confere todo dia depois da coleta, e o que bateu o alvo aparece na própria tela (botão
"Conferir agora").

### Ligar o envio pelo Telegram (opcional, desligado por padrão)

O envio está desligado por decisão do dono em 2026-11-08. A função continua inteira no código; só
não sai mensagem. Para ligar:

1. No Telegram, fale com o `@BotFather`, mande `/newbot` e guarde o token.
2. Mande uma mensagem para o seu bot e descubra seu chat em `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. No `.env` do servidor (ou nas variáveis de ambiente), defina as três:
   ```
   ALERTAS_TELEGRAM=1
   TELEGRAM_TOKEN=123456:ABC...
   TELEGRAM_CHAT=987654321
   ```
4. Reinicie o serviço: `sudo systemctl restart ofertas-sp`.

A chave `ALERTAS_TELEGRAM` é o que manda. Sem ela em `1`, o app nem tenta enviar, mesmo com o token
preenchido. Isso evita disparo acidental por um token esquecido no ambiente.

Depois da coleta de cada dia o app confere os alertas. Ele só avisa se passaram 3 dias desde o
último aviso daquele produto, ou se o preço caiu mais 5% abaixo do último aviso. Sem isso, um produto
parado no alvo mandaria mensagem todo dia e você desligaria o alerta na segunda semana.

A mensagem inclui o veredito do histórico: "promoção de verdade" ou "cuidado, o desconto é inflado".

## Virar app no celular (PWA)

O app é um PWA: abra no celular e use "Adicionar à tela de início". Ele ganha ícone, abre em tela
cheia e funciona sem sinal no mercado.

O que funciona offline: a lista de compras, os favoritos e o último preço visto. O catálogo inteiro
(11 MB, 38 mil preços) **não** é guardado no aparelho de propósito: seria lento e desnecessário.
Marcar item na lista sem sinal entra numa fila e é enviado quando a conexão volta.

## Hospedar num Debian

### Opção 1: instalação direta (recomendada)

```bash
sudo bash deploy/instalar.sh
sudo nano /opt/ofertas-sp/.env     # CEP, proxy, Telegram
sudo systemctl restart ofertas-sp
sudo systemctl status ofertas-sp
```

O instalador cria o serviço systemd, o usuário `ofertas`, e guarda os dados em
`/var/lib/ofertas-sp` (fora do código, então atualizar o app não apaga o histórico).

Comandos úteis:

```bash
sudo systemctl status ofertas-sp       # está rodando?
sudo journalctl -u ofertas-sp -f       # ver o log ao vivo
curl localhost:8770/api/saude          # a coleta de hoje rodou?
```

### Opção 2: Docker

```bash
docker compose up -d
docker compose logs -f
```

Os dados ficam no volume `ofertas-dados`. O container tem healthcheck no `/api/saude`.

### Nginx na frente (opcional, mas recomendado)

```bash
sudo cp deploy/nginx-ofertas.conf /etc/nginx/sites-available/ofertas-sp
sudo ln -s /etc/nginx/sites-available/ofertas-sp /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

O arquivo já vem com `auth_basic` comentado, caso você queira proteger com senha.

### Variáveis de ambiente

| variável | para que serve |
|---|---|
| `OFERTAS_CEP` | CEP usado na coleta |
| `OFERTAS_PORTA` | porta do servidor (padrão 8770) |
| `OFERTAS_HORA` / `OFERTAS_MINUTO` | horário da coleta diária |
| `OFERTAS_DB` | caminho do banco de produtos |
| `OFERTAS_HIST` | caminho do banco de histórico |
| `OFERTAS_HIST_DIAS` | quantos dias de histórico guardar (padrão 400) |
| `OFERTAS_PROXY` | proxy para acessar as lojas |
| `ALERTAS_TELEGRAM` | `1` liga o envio pelo Telegram (desligado por padrão) |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT` | credenciais do bot, só usadas com a chave acima em `1` |
| `ANTHROPIC_API_KEY` | leitura de folhetos com IA (opcional) |

## Saúde do serviço

`GET /api/saude` responde a pergunta que importa: **a coleta de hoje rodou?** Devolve aviso quando a
última coleta bem-sucedida tem mais de 36 horas ou quando o histórico está vazio. Se a coleta falhar,
o app avisa no Telegram (se estiver ligado): coleta que falha em silêncio é pior que app fora do ar.

## Arquivos

- `app.py`: servidor e API
- `servidor.py`: servidor de produção para Debian (agendador embutido)
- `db.py`: banco local (`ofertas.db`): produtos, famílias, alertas, execuções
- `historico.py`: banco de histórico (`historico.db`), vereditos e séries
- `alertas.py`: conferência de preço-alvo e envio no Telegram
- `coletores/sites.py`: lojas online
- `coletores/folhetos.py`: tabloides do Assaí e do Roldão
- `coletores/extrator_ia.py`: leitura dos folhetos com IA
- `static/index.html`: interface
- `static/sw.js` e `static/manifest.json`: o que faz virar app no celular
- `deploy/`: instalação em Debian, nginx e entrada do container
- `Dockerfile` e `docker-compose.yml`: a outra forma de hospedar

Para adicionar outra rede que use a plataforma VTEX, basta incluir uma linha no dicionário `VTEX` em `coletores/sites.py`.
