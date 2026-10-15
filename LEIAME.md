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

- **Lojas online, com preço exato:** Pão de Açúcar, Carrefour, Sonda, Tenda Atacado, Atacadão, Sam's Club, Mambo, Oba Hortifruti, Coop, Savegnago, Zaffari e Swift.
- **Folhetos, lidos com IA:** Assaí (todas as lojas de SP), Roldão, Akki (PDF), Lopes, Max Atacadista e Barbosa.

**Não entraram:**
- **Busca de produtos do Barbosa:** a API do site é criptografada de propósito contra robôs; o Barbosa entra pelos tabloides.
- **Carrefour:** só a busca do site (15 produtos por busca, sem ajuste por CEP); a API deles bloqueia robôs.
- **Cercadão:** a página de jornal de ofertas está vazia no momento.
- **Dia, St Marche, Nagumo e Hirota:** não encontrei uma fonte pública de preços.

## CEP

Clique em **📍** no topo e informe seu CEP. Com ele:
- Pão de Açúcar, Atacadão, Sam's Club, Mambo, Oba, Coop, Savegnago, Zaffari e Swift mostram o preço e a disponibilidade da sua região. Produto que não é entregue no seu CEP some da lista.
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

## Arquivos

- `app.py`: servidor e API
- `db.py`: banco local (`ofertas.db`)
- `coletores/sites.py`: lojas online
- `coletores/folhetos.py`: tabloides do Assaí e do Roldão
- `coletores/extrator_ia.py`: leitura dos folhetos com IA
- `static/index.html`: interface

Para adicionar outra rede que use a plataforma VTEX, basta incluir uma linha no dicionário `VTEX` em `coletores/sites.py`.
