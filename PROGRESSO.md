# Estado da sessão — Ofertas SP

Última atualização: 2026-11-13 (America/Sao_Paulo)

Este arquivo existe para a sessão poder ser compactada sem perder o fio. Se você (ou outra
sessão) retomar este trabalho, leia isto primeiro e continue daqui.

---

## Segunda coleta no dia, 13/11/2026 (Claude)

Pedido do dono. A IA (Gemini grátis) lê em média 16 páginas novas por dia e deixa uns 5 folhetos
pendentes por coleta, quase sempre por demora ("timed out") ou 503. O `publicar.yml` ganhou um segundo
horário: 15:00 de São Paulo (`0 18 * * *`), além do das 06:00. O dono preferiu ficar só no Google e não
quis, por ora, mais modelos na fila nem nova tentativa em caso de demora.
Backup: `backups/2026-11-13-segunda-coleta/`.

## Mercado 3M (folheto), 13/11/2026 (Claude)

Pedido do dono. O Supermercado 3M tem duas lojas na zona sul de SP (R. Alberto Borges Soveral, 9 e
R. Feitiço da Vila, 36) e não tem loja online: entra só por folheto, na região São Paulo.
- `folhetos_3m` (coletores/folhetos.py): lê https://www.supermercado3m.com.br/jornal (site do Wix) e
  pega as imagens grandes e em pé, no arquivo original. A página não dá validade.
- "3M" em `REGIOES["sp"]["folhetos"]`, em `todos_folhetos`, na lista do app.py, em `CORES` e em
  `NOME_NO_MAPA` (rota) do index.html. sw.js v7. Teste `test_folhetos_3m_pega_so_as_paginas_do_jornal`.
- O Instagram (3m_supermercado) não é coletado: precisa de login.
Backup: `backups/2026-11-13-mercado-3m/`.

## Aviso falso do Extra na busca ao vivo, 13/11/2026 (Claude)

Na busca "arroz 5 kg" o site mostrava "Não responderam agora: Extra". O Extra tinha respondido 404
"Products not found" (loja sem o produto). O Python já tratava isso (`buscar_gpa`); faltava o site.
`pedir` agora guarda o código e o corpo do erro (`erro.status`, `erro.corpo`) e `gpa` devolve lista
vazia nesse caso; os outros erros continuam como falha. sw.js v6.
Backup: `backups/2026-11-13-extra404-site/`.

## Design em seis áreas, 13/11/2026 (Claude)

Pedido do dono, com prévia de antes e depois aprovada:

- **Comparar** deixou de abrir vazia: "Destaques de hoje" (6 ofertas com desconto de 15% a 60%, com foto,
  uma de cada mercado), "Buscas recentes" (`ofertas-buscas` no aparelho) e "Seus favoritos que baixaram".
  Funções `desenharInicio`, `destaquesDoDia`, `Recentes`.
- **Ofertas:** filtros numa linha que rola de lado (`.filtros`); produto sem foto (folheto, ou foto que
  não carrega) vira um quadrado com a cor e a inicial do mercado (`.sem-foto`).
- **Desconto falso de -90%:** folheto com preço "a cada 100g" trazia o preço do quilo como "de". A regra
  fica em `Produto.finalizar` (coletores/base.py) e espelhada em `finalizar` do index.html: sem desconto,
  e o preço por quilo passa a aparecer. A mesma regra tira o desconto falso de parcela ("3x sem juros").
- **Favoritos e Lista vazios:** desenho, explicação e botão (`telaVazia`). Na aba Favoritos cada item
  ganhou "Tirar dos favoritos".
- **Mais:** atalhos em cima; mercados recolhidos em "Meus mercados" (`<details id="grupoMercados">`).
- **Folhetos em PDF:** a coleta desenha a primeira página (`capas_dos_pdfs` em gerar_site.py, com PyMuPDF,
  instalado no workflow) e grava em `dados/capas/`; o folheto leva o campo `capa`. Sem a biblioteca, ou
  se o PDF falhar, o site mostra um cartão com a cor do mercado.
- **Topo e sugestões:** CEP virou uma pílula com alfinete e seta; sugestões com lupa, maiúscula e espaço
  antes da unidade ("Arroz 5 kg"; a busca continua usando "arroz 5kg"); selo "Ao vivo" no aviso.
  Plurais ("1 favorito"), validade como "até 14/11".
- `sw.js` foi para v5.

Testes: 78, todos passando. Backup em `backups/2026-11-13-design-6-areas/`.

## Extra 404 e loja mais perto no mapa, 13/11/2026 (Claude)

- **Extra: "1 falhas, HTTP Error 404" em toda coleta.** Era sempre a busca "pizza congelada": a loja
  do Extra da região (2180) não tem o produto e a API do GPA responde 404 "Products not found" em vez
  de lista vazia. `buscar_gpa` agora trata esse 404 como "nenhum produto"; qualquer outro erro
  (500, 404 sem essa mensagem) continua contando como falha.
- **Rota não pegava o Roldão mais perto.** O Roldão da Av. General Ataliba Leonel (8 km da Paulista)
  está no OpenStreetMap como `building/retail`, não como `shop`. `lojasOsm` passou a aceitar também
  `building` quando o nome bate com a rede (praça e rua com o mesmo nome continuam de fora).
  O cache das lojas no aparelho mudou de nome (`ofertas-lojas2`) para não ficar 30 dias com a loja
  antiga; `sw.js` foi para v4.
- **Limite que continua:** o mapa tem só 3 Roldão perto da capital; a rede tem 37 lojas no estado
  (`roldao.com.br/wp-json/wp/v2/lojas-contato` dá os nomes, mas não os endereços).

Testes: 72, todos passando. Backup em `backups/2026-11-13-extra404-roldao/`.

## Correções de 12/11/2026 (Claude)

O site ficou parado nos dados de 09/11 e o histórico nunca passou de 1 ponto por produto. Corrigido:

- **Histórico não acumulava.** `exportar_historico` descartava os dias já publicados sempre que o
  produto aparecia na coleta do dia (ou seja, sempre). Agora soma dia a dia; no mesmo dia vale o
  banco. O teto de 6.000 produtos dá preferência às séries mais longas e reparte entre os mercados.
- **Coleta cancelada aos 60 min** (10 e 11/11). A leitura dos folhetos com IA esperava até 180 s por
  página. Agora: 25 s para baixar a imagem, 100 s para a IA, e a leitura para aos 40 min de coleta
  (`OFERTAS_MINUTOS_IA`); o que falta fica para o dia seguinte. Limite do Actions subiu para 90 min.
- **Pague Menos dava 404 em tudo.** A loja trocou a plataforma para VTEX; passou a usar `buscar_vtex`.
  A busca VTEX ganhou `allowRedirect=false` (sem isso "arroz" voltava vazio).
- **Gemini recusava imagens "binary/octet-stream".** O tipo agora sai da extensão do arquivo.
- A seção "O que ainda NÃO foi feito", mais abaixo, é de antes da publicação: os itens 1 e 2 já não valem.

Testes: 62, todos passando. Backup em `backups/antes-correcao-2026-11-12-0509/`.

## Design novo de 12/11/2026 (Claude)

`static/index.html` ganhou visual novo, sem mudar as buscas nem os dados:

- Abas embaixo no celular (Comparar, Ofertas, Favoritos, Lista, Mais) e barra lateral no computador.
  Folhetos e Família abrem a partir de "Mais". Tudo passa por `abrirAba()`.
- Produtos em linhas compactas. Tocar no produto abre o detalhe: gráfico do histórico, favoritar,
  link da loja e o mesmo produto em outros mercados (pelo código de barras).
- **Meus mercados** (tela Mais): o que o usuário desliga fica em `localStorage["ofertas-mercados-off"]`
  e sai de tudo por `Regiao.tem()`.
- **Lista dividida em até 2 mercados**: `planoLista()` e `melhorDupla()` escolhem a dupla que cobre
  mais itens e, no empate, a mais barata. O modo fica em `localStorage["ofertas-lista-modo"]`.
- A janela do CEP não abre mais sozinha na primeira visita (cada região já tem CEP padrão).
- `sw.js` passou para `ofertas-sp-v2`, para o app instalado trocar a casca antiga.

Backup em `backups/antes-design-2026-11-12-2207/`.

## Histórico de todos os produtos, 13/11/2026 (Claude)

O `historico.json` cobria 6.000 dos 42 mil produtos, então o gráfico quase nunca aparecia. Agora cobre todos:

- A série guarda só as mudanças: o primeiro e o último dia de cada preço seguido, com o dia em dias desde 1970
  (`_comprimir_serie` / `_expandir_serie` em `gerar_site.py`, `expandirSerie` em `static/index.html`).
- O formato antigo (segundos) continua sendo lido. Janela de 90 dias, a mesma do veredito da oferta.
- O site carrega o histórico depois de abrir, sem atrasar a primeira tela.
- Tamanho hoje: cerca de 3 MB. Projeção com 90 dias de dados: 8 a 10 MB antes da compactação do servidor.

Backup em `backups/antes-historico-completo-2026-11-13/`.

## Rota casa, mercados, casa: 13/11/2026 (Claude)

Na aba Lista, o cartão "Rota" usa os mercados do plano da lista (um só ou a dupla) e monta o caminho de ida e volta.
Tudo no navegador (`Rota` e `desenharRota` em `static/index.html`), com serviços grátis e sem chave:

- **Lojas**: pontos de retirada das redes VTEX (`/api/checkout/pub/pickup-points`, pelo proxy), a lista de lojas do
  Assaí e, para as demais, a busca por nome do OpenStreetMap (Nominatim), em caixas de 8, 22 e 55 km em volta de casa.
  A loja achada fica guardada no aparelho por 30 dias (`ofertas-lojas`).
- **Ordem, km e tempo**: OSRM (`router.project-osrm.org`), com `routing.openstreetmap.de` de reserva e, sem nenhum
  dos dois, estimativa em linha reta.
- **Navegação**: link do Google Maps com as paradas e link do Waze por parada.
- **Combustível**: consumo e preço ficam em `ofertas-carro`; com a lista dividida em 2, mostra se ainda compensa.
- **Partida**: o centro do CEP, ou a localização do aparelho se o usuário pedir (`ofertas-casa`, só no aparelho).
- O Overpass foi testado e descartado: em São Paulo passava de 45 s e caía. Toda chamada tem limite de tempo (`comPrazo`).

Junto: o `sw.js` (v3) passou a buscar a rede primeiro. Antes ele entregava a página e os preços da visita anterior
e só atualizava por trás, então cada mudança demorava uma visita para aparecer.

Backup em `backups/antes-rota-2026-11-13/`.

## O que foi pedido

O usuário listou 7 ideias para o Ofertas SP e pediu: fazer o que eu achasse melhor, incluir
histórico de preço, propor ideias novas, e no fim poder **hospedar o programa num Linux Debian**.

## Situação agora: publicado

Commit `b87d147` no `main`, enviado ao GitHub. Workflow "Publicar site" disparado à mão
(run `42536668861`). Antes disso foi feito backup em `backups/antes-publicar-2026-11-08-1641/`
(33 arquivos, 30,3 MB, os dois bancos com `integrity_check` = ok).

## Decisão do dono: Telegram desligado

O envio pelo Telegram está **desligado por padrão** (`ALERTAS_TELEGRAM=0`). A função continua
inteira no código e documentada no LEIAME, seção "Alertas de preço". O que mudou:

- `alertas.TELEGRAM_LIGADO` é a chave. Sem ela em `1`, `enviar_telegram` recusa antes de qualquer rede.
- `checar_alertas` continua rodando: atualiza preços, confere alvos e devolve `bateram` (o que teria
  sido avisado) além de `disparos`.
- Na tela, o painel mostra "Telegram desligado" com a instrução de como religar, o botão "Testar
  Telegram" fica oculto, e "Conferir agora" lista quem bateu o alvo.

## Correção importante antes de publicar

O GitHub Actions roda em máquina limpa, **sem `historico.db`**. Do jeito que estava, o
`historico.json` publicado sairia vazio todo dia e o histórico nunca acumularia — o gráfico nunca
passaria de um ponto. Agora `exportar_historico(anteriores=...)` lê o `historico.json` do site
publicado (mesmo padrão que o `folhetos-lidos.json` já usava) e mescla: o dia novo manda, o passado
é preservado. O site publicado é o arquivo de longo prazo. Tem teste cobrindo os três casos.

---

## O que existe e funciona (verificado com dados reais)

### Histórico de preços — `historico.py`

Banco separado `historico.db`, append-only, fora do alcance da limpeza diária do `gerar_site.py`.
`db.salvar_produtos` grava sozinho em toda coleta; falha no histórico nunca derruba a coleta.

Funções: `registrar`, `serie`, `serie_ean`, `resumo`, `avaliar_oferta`, `melhor_dia`,
`indice_cesta`, `quedas_bruscas`, `podar`, `contagens`.

### Detector de promoção falsa — `historico.avaliar_oferta`

| veredito | regra |
|---|---|
| `boa` | ≥15% abaixo da mediana dos últimos 90 dias |
| `inflada` | o preço "de" anunciado está >5% acima da mediana (o truque clássico) |
| `cara` | ≥10% acima da mediana |
| `normal` | na faixa de sempre |
| `sem_historico` | menos de 14 dias observados |

A **mesma regra** existe em JS no `index.html` (`avaliarLocal`), para o site estático dar o mesmo
veredito sem servidor. Há teste garantindo que as duas não divergem.

### Código de barras (EAN)

Campo `ean` no dataclass, nos coletores VTEX, no banco (com migração) e `/api/historico/ean`.
**Limite:** a API do GPA (Pão de Açúcar, Extra) não devolve EAN na busca — ~11% da base segue por nome.

### Lista compartilhada da família — sem login

Código de 12 caracteres, alfabeto sem `0/O/1/I/L`, ~10^18 combinações. Controle de conflito por
`versao`: quem grava com versão velha recebe a versão da outra pessoa em vez de sobrescrever.
**Não tem senha.** Quem tem o código, entra. Para revogar, crie família nova.

### Alertas no Telegram — `alertas.py`

Um alerta por (família, produto, mercado). `alerta_criar` **atualiza o alvo** em vez de duplicar
quando o produto já tem alerta ativo. Silêncio de 3 dias, com exceção para queda extra de 5%.
A mensagem carrega o veredito do histórico.

### PWA

`manifest.json`, `sw.js` (cache-first na casca, network-first em `/api`, fila offline para POST),
ícones PNG gerados por código. O `gerar_site.py` **copia os arquivos do PWA** para o site publicado.

### Servidor Debian — `servidor.py`

Escuta em `0.0.0.0`, agendador embutido, desligamento limpo no SIGTERM, registro em `execucoes`,
aviso no Telegram quando a coleta falha. Flags: `--porta`, `--host`, `--hora`, `--minuto`,
`--sem-agendador`, `--coletar-agora`.

### Saúde — `/api/saude?familia=CODIGO`

Responde "a coleta de hoje rodou". Com `familia`, conta só os alertas daquela família, para o
painel casar com a lista logo abaixo. Sem `familia`, conta todos (uso em monitoramento externo).

### Site estático (GitHub Pages)

`gerar_site.py` exporta `historico.json` (formato compacto `{chave: [[epoch, preco], ...]}`,
442 KB para 6.000 produtos) e o `index.html` lê esse arquivo quando não há servidor. O gráfico
funciona no site publicado. Família e alertas mostram aviso explicando que precisam do servidor.

### Deploy

`deploy/instalar.sh` (systemd, dados em `/var/lib/ofertas-sp`), `Dockerfile`,
`docker-compose.yml` (volume + healthcheck), `deploy/nginx-ofertas.conf` (com `auth_basic` comentado).

---

## Bugs encontrados e corrigidos

1. **`no such column: ean`** — `CREATE INDEX ix_prod_ean` rodava antes do `ALTER TABLE` que cria a
   coluna. Em banco novo passava; num `ofertas.db` existente o app não abria. Índice movido para
   dentro do `_migrar()`, depois da migração. Tem teste de regressão.
2. **Alerta duplicado** — `alerta_criar` inseria sempre. Tocar duas vezes em "Criar alerta" gerava
   dois avisos do mesmo produto. Agora atualiza o alvo do alerta existente.
3. **Painel dizia "2 alertas", lista mostrava 1** — `saude()` contava alertas de todas as famílias.
   Agora aceita `?familia=` e o frontend passa o código.

## Falsos alarmes (não eram bugs)

- `UnicodeEncodeError` com 🛒: console do Windows (cp1252) ao **imprimir** emoji. A API estava certa.
  Rodar com `PYTHONIOENCODING=utf-8`.
- `Invoke-WebRequest` falhando: modo NonInteractive do PowerShell. Usar `urllib` no teste.

---

## Testes — `test_ofertas.py`

**50 testes, todos passando** (`py -m unittest test_ofertas`, exit 0, ~3 s).

Cobrem: histórico (série, mediana, os 5 vereditos, quedas, podar), banco (upsert, busca com e sem
acento, busca por marca, EAN, famílias, conflito de versão, alertas), migração do banco antigo,
alertas (disparo, silêncio, queda extra, alerta desligado), saúde (contagem por família),
exportação do histórico, interface (abas, PWA, regra do veredito em JS espelhando o Python) e
deploy (systemd, Dockerfile, compose, nginx).

Cada teste usa bancos próprios num diretório temporário, apontando `db.ARQUIVO` e
`historico.ARQUIVO` à mão — os módulos resolvem o caminho no import, então trocar a variável de
ambiente depois não adianta.

---

## Verificação feita (evidência)

- 38.313 preços reais importados do site publicado para o `ofertas.db` local.
- Histórico gravou sozinho: 38.573 preços, 41 dias (2026-09-29 a 2026-11-08), 35.251 produtos.
- Servidor real (`servidor.py --porta 8774 --sem-agendador`): todas as rotas responderam.
- Alerta: criar duas vezes o mesmo produto pela interface → 1 alerta, alvo atualizado.
- Saúde: família 1 → 1 alerta, família 2 → 1 alerta, sem família → 5 (todas). Painel casa com a lista.
- Site estático montado e servido: gráfico de 41 dias renderizado, mediana R$ 18,96, veredito igual
  ao do Python nos três casos testados.
- Sintaxe: `ast.parse` em todos os .py, `node --check` no `sw.js`, manifest válido.

## O que ainda NÃO foi feito

1. **Nada foi publicado.** O site no GitHub Pages continua com a versão antiga (sem histórico,
   sem PWA, sem EAN). Publicar é `py gerar_site.py` e subir a pasta `site/`.
2. **Nenhuma coleta real rodou ainda.** O histórico tem 41 dias porque eu simulei 40 dias em 3
   produtos para testar o gráfico. Os outros 35 mil produtos têm 1 dia. `ofertas/reais` e `quedas`
   ficam vazios até haver ~14 dias reais — é o comportamento correto, não bug.
3. **Telegram não configurado.** Sem `TELEGRAM_TOKEN` e `TELEGRAM_CHAT`, os alertas não saem.
4. **EAN no GPA** não resolvido (~11% da base).
5. **`ofertas.db` e `historico.db` locais têm dados de teste** (os 40 dias simulados). Se for
   publicar, vale limpar o histórico simulado antes.

## Arquivos tocados

Novos: `historico.py`, `alertas.py`, `servidor.py`, `test_ofertas.py`, `requirements.txt`,
`Dockerfile`, `docker-compose.yml`, `deploy/instalar.sh`, `deploy/entrada.sh`,
`deploy/nginx-ofertas.conf`, `static/manifest.json`, `static/sw.js`, `static/icone-192.png`,
`static/icone-512.png`, `PROGRESSO.md`.

Modificados: `db.py` (ean, famílias, alertas com dedupe, execuções, migração), `app.py` (rotas
novas, `saude(familia)`, `_novo_codigo`), `coletores/base.py` (campo ean), `coletores/sites.py`
(lê ean), `gerar_site.py` (`exportar_historico`, cópia do PWA), `static/index.html` (aba Família,
gráfico, veredito em JS, modo mercado, WhatsApp, PWA), `LEIAME.md` (documentação completa),
`.gitignore` (historico.db, .env, log*.txt).

## Como rodar

```powershell
# Windows, desenvolvimento
py app.py                          # localhost:8765

# servidor de produção (Debian)
sudo bash deploy/instalar.sh
sudo nano /opt/ofertas-sp/.env     # CEP, proxy, Telegram
sudo systemctl restart ofertas-sp

# Docker
docker compose up -d

# testes
py -m unittest test_ofertas
```

## Próximo passo recomendado

Publicar (`py gerar_site.py`) e deixar coletando. O histórico só vira ativo real depois de 60 dias:
cada dia sem gravar é um dia perdido para sempre.
