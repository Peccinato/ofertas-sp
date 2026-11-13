"""Testes do Ofertas SP.

Roda sem rede e sem tocar nos bancos de verdade: cada teste usa um diretório temporário.
    py -m unittest -v test_ofertas
    py test_ofertas.py
"""
import json
import os
import shutil
import tempfile
import time
import unittest


class BaseComBancos(unittest.TestCase):
    """Cada teste ganha seus próprios bancos, num diretório temporário.

    db.py e historico.py resolvem o caminho do banco no import (constante ARQUIVO), então
    trocar a variável de ambiente depois não adianta: aqui o ARQUIVO é apontado à mão.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ofertas-teste-")
        import db
        import historico
        self.db = db
        self.historico = historico

        self._antes = (db.ARQUIVO, historico.ARQUIVO)
        db.ARQUIVO = os.path.join(self.tmp, "ofertas.db")
        historico.ARQUIVO = os.path.join(self.tmp, "historico.db")

        db.criar()
        historico.criar()

    def tearDown(self):
        self.db.ARQUIVO, self.historico.ARQUIVO = self._antes
        shutil.rmtree(self.tmp, ignore_errors=True)

    def nova_familia(self, dados=None):
        """Cria família do mesmo jeito que o app: código novo + familia_gravar."""
        import app
        codigo = app._novo_codigo()
        self.db.familia_gravar(codigo, dados if dados is not None else {"favoritos": [], "lista": []})
        return codigo

    def produto(self, mercado="Covabra", nome="Café Pilão 500g", preco=17.9, **extra):
        p = {"mercado": mercado, "nome": nome, "preco": preco, "preco_de": None,
             "marca": "Pilão", "imagem": "", "url": "", "origem": "site",
             "validade": "", "extra": "", "unidade": "un", "preco_unidade": preco,
             "desconto": 0, "ean": ""}
        p.update(extra)
        return p

    def serie(self, mercado, nome, precos, dias_atras=None):
        """Grava uma série de preços, um por dia, terminando ontem."""
        n = len(precos)
        dias_atras = dias_atras or list(range(n, 0, -1))
        for preco, d in zip(precos, dias_atras):
            dia = time.strftime("%Y-%m-%d", time.localtime(time.time() - d * 86400))
            self.historico.registrar(
                [{"mercado": mercado, "nome": nome, "preco": preco, "origem": "site"}], dia=dia)


class TestHistorico(BaseComBancos):

    def test_grava_e_le_serie(self):
        self.serie("Covabra", "Café", [10.0, 11.0, 12.0])
        s = self.historico.serie("Covabra", "Café")
        self.assertEqual(len(s), 3)
        self.assertEqual([p["preco"] for p in s], [10.0, 11.0, 12.0])

    def test_serie_ignora_outro_mercado(self):
        self.serie("Covabra", "Café", [10.0])
        self.serie("Assaí", "Café", [99.0])
        s = self.historico.serie("Covabra", "Café")
        self.assertEqual([p["preco"] for p in s], [10.0])

    def test_regravar_o_mesmo_dia_nao_duplica(self):
        dia = time.strftime("%Y-%m-%d")
        for preco in (10.0, 10.0, 10.0):
            self.historico.registrar(
                [{"mercado": "Covabra", "nome": "Café", "preco": preco, "origem": "site"}], dia=dia)
        self.assertEqual(len(self.historico.serie("Covabra", "Café")), 1)

    def test_resumo_calcula_mediana_e_extremos(self):
        self.serie("Covabra", "Café", [10.0, 20.0, 30.0, 40.0])
        r = self.historico.resumo("Covabra", "Café")
        self.assertEqual(r["dias"], 4)
        self.assertEqual(r["minimo"], 10.0)
        self.assertEqual(r["maximo"], 40.0)
        self.assertEqual(r["mediana"], 25.0)

    def test_sem_historico_quando_poucos_dias(self):
        self.serie("Covabra", "Café", [10.0] * 5)
        av = self.historico.avaliar_oferta("Covabra", "Café", 9.0)
        self.assertEqual(av["veredito"], "sem_historico")

    def test_veredito_boa(self):
        # mediana 20, oferta a 15 = 25% abaixo
        self.serie("Covabra", "Café", [20.0] * 20)
        av = self.historico.avaliar_oferta("Covabra", "Café", 15.0)
        self.assertEqual(av["veredito"], "boa")
        self.assertGreaterEqual(av["desconto_real_pct"], 15)

    def test_veredito_inflada_quando_o_de_esta_acima_da_mediana(self):
        # produto custa ~20, anunciam "de 30 por 19" -> o "de" é mentira
        self.serie("Covabra", "Café", [20.0] * 20)
        av = self.historico.avaliar_oferta("Covabra", "Café", 19.0, preco_de=30.0)
        self.assertEqual(av["veredito"], "inflada")
        self.assertIn("acima do que este produto costuma custar", av["motivo"])

    def test_veredito_cara(self):
        self.serie("Covabra", "Café", [20.0] * 20)
        av = self.historico.avaliar_oferta("Covabra", "Café", 25.0)
        self.assertEqual(av["veredito"], "cara")

    def test_veredito_normal(self):
        self.serie("Covabra", "Café", [20.0] * 20)
        av = self.historico.avaliar_oferta("Covabra", "Café", 20.5)
        self.assertEqual(av["veredito"], "normal")

    def test_menor_preco_registrado_aparece_no_motivo(self):
        self.serie("Covabra", "Café", [30.0] * 10 + [20.0] * 10)
        av = self.historico.avaliar_oferta("Covabra", "Café", 19.0)
        self.assertEqual(av["veredito"], "boa")
        self.assertIn("menor preço", av["motivo"])

    def test_quedas_bruscas(self):
        """queda é medida contra a mediana dos 90 dias, não contra o dia anterior."""
        self.serie("Covabra", "Café", [20.0] * 20)          # mediana 20
        hoje = time.strftime("%Y-%m-%d")
        self.historico.registrar(
            [{"mercado": "Covabra", "nome": "Café", "preco": 12.0, "origem": "site"}], dia=hoje)
        q = self.historico.quedas_bruscas(pct=40)
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["preco"], 12.0)
        self.assertEqual(q[0]["mediana"], 20.0)
        self.assertEqual(q[0]["queda_pct"], 40.0)

    def test_queda_pequena_nao_entra(self):
        self.serie("Covabra", "Café", [20.0] * 20)
        hoje = time.strftime("%Y-%m-%d")
        self.historico.registrar(
            [{"mercado": "Covabra", "nome": "Café", "preco": 18.0, "origem": "site"}], dia=hoje)
        self.assertEqual(self.historico.quedas_bruscas(pct=40), [])

    def test_contagens(self):
        self.serie("Covabra", "Café", [10.0, 11.0])
        self.serie("Assaí", "Arroz", [20.0])
        c = self.historico.contagens()
        self.assertEqual(c["n"], 3)
        self.assertEqual(c["p"], 2)
        self.assertEqual(c["d"], 2)


class TestBanco(BaseComBancos):

    def test_salvar_grava_historico_sozinho(self):
        self.db.salvar_produtos([self.produto()], fonte="teste")
        self.assertEqual(self.historico.contagens()["n"], 1)

    def test_salvar_duas_vezes_nao_duplica_produto(self):
        self.db.salvar_produtos([self.produto()], fonte="teste")
        self.db.salvar_produtos([self.produto(preco=16.5)], fonte="teste")
        todos = self.db.consultar("café", limite=50)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["preco"], 16.5)

    def test_consultar_acha_por_palavra(self):
        self.db.salvar_produtos([self.produto(nome="Café Pilão 500g", marca="Pilão"),
                                 self.produto(nome="Arroz Camil 5kg", marca="Camil")], fonte="teste")
        achados = self.db.consultar("pilão", limite=50)
        self.assertEqual([p["nome"] for p in achados], ["Café Pilão 500g"])

    def test_busca_acha_pela_marca(self):
        """nome_busca = nome + marca: buscar pela marca é intencional."""
        self.db.salvar_produtos([self.produto(nome="Torrada Integral 200g", marca="Bauducco")], fonte="teste")
        self.assertEqual(len(self.db.consultar("bauducco", limite=50)), 1)

    def test_consultar_sem_acento_acha_com_acento(self):
        self.db.salvar_produtos([self.produto(nome="Café Pilão 500g")], fonte="teste")
        self.assertEqual(len(self.db.consultar("cafe", limite=50)), 1)

    def test_ean_gravado_e_encontrado(self):
        self.db.salvar_produtos([
            self.produto(mercado="Covabra", ean="7891234567890"),
            self.produto(mercado="Assaí", ean="7891234567890", preco=15.0),
        ], fonte="teste")
        por_ean = self.db.por_ean("7891234567890")
        self.assertEqual(len(por_ean), 2)
        self.assertEqual({p["mercado"] for p in por_ean}, {"Covabra", "Assaí"})

    def test_familia_cria_e_le(self):
        codigo = self.nova_familia()
        self.assertEqual(len(codigo), 12)
        f = self.db.familia_ler(codigo)
        self.assertEqual(f["versao"], 1)
        self.assertEqual(f["dados"]["lista"], [])

    def test_familia_codigo_sem_caracteres_ambiguos(self):
        for _ in range(30):
            codigo = self.nova_familia({"x": 1})
            self.assertFalse(set(codigo) & set("0O1IL"), codigo)

    def test_familia_grava_sobe_versao(self):
        codigo = self.nova_familia({"lista": []})
        r = self.db.familia_gravar(codigo, {"lista": [1]}, versao=1)
        self.assertFalse(r.get("conflito"))
        self.assertEqual(self.db.familia_ler(codigo)["versao"], 2)

    def test_familia_conflito_nao_sobrescreve(self):
        codigo = self.nova_familia({"lista": ["original"]})
        r = self.db.familia_gravar(codigo, {"lista": ["outro"]}, versao=99)
        self.assertTrue(r.get("conflito"))
        self.assertEqual(self.db.familia_ler(codigo)["dados"]["lista"], ["original"])

    def test_familia_codigo_inexistente(self):
        self.assertIsNone(self.db.familia_ler("AAAAAAAAAAAA"))

    def test_alertas_criar_listar_apagar(self):
        codigo = self.nova_familia({"lista": []})
        self.db.alerta_criar(codigo, "Café Pilão", 15.0, mercado="Covabra")
        lista = self.db.alertas_listar(codigo)
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["alvo"], 15.0)
        self.db.alerta_apagar(lista[0]["id"])
        self.assertEqual(self.db.alertas_listar(codigo), [])

    def test_alerta_nao_duplica_mesmo_produto(self):
        codigo = self.nova_familia({"lista": []})
        self.db.alerta_criar(codigo, "Café Pilão", 15.0)
        self.db.alerta_criar(codigo, "Café Pilão", 12.0)
        self.assertEqual(len(self.db.alertas_listar(codigo)), 1)

    def test_execucao_registrada(self):
        i = self.db.execucao_iniciar("coleta")
        self.db.execucao_terminar(i, True, "100 produtos")
        ultima = self.db.ultima_execucao_ok("coleta")
        self.assertIsNotNone(ultima)


class TestMigracao(BaseComBancos):

    def test_banco_antigo_sem_ean_abre_e_migra(self):
        """O bug que derrubou o app: banco antigo não tinha a coluna ean."""
        import sqlite3
        # banco antigo num caminho novo: não precisa apagar o que o setUp criou
        caminho = os.path.join(self.tmp, "antigo.db")
        self.db.ARQUIVO = caminho
        con = sqlite3.connect(caminho)
        # esquema real de antes da coluna ean (nome_busca já existia)
        con.executescript("""
            CREATE TABLE produtos (
                id INTEGER PRIMARY KEY,
                mercado TEXT, nome TEXT, nome_busca TEXT, preco REAL, preco_de REAL, marca TEXT,
                imagem TEXT, url TEXT, origem TEXT, validade TEXT, extra TEXT, unidade TEXT,
                preco_unidade REAL, desconto REAL, fonte TEXT, atualizado_em REAL,
                UNIQUE (mercado, nome, origem)
            );
            CREATE TABLE buscas (termo TEXT PRIMARY KEY, feita_em REAL);
            CREATE TABLE folhetos (
                imagem TEXT PRIMARY KEY, mercado TEXT, loja TEXT, titulo TEXT, pagina INTEGER,
                validade TEXT, inicio TEXT, fim TEXT, status TEXT DEFAULT 'pendente', erro TEXT,
                n_itens INTEGER DEFAULT 0, atualizado_em REAL
            );
            CREATE TABLE config (chave TEXT PRIMARY KEY, valor TEXT);
        """)
        con.execute("""INSERT INTO produtos (mercado, nome, nome_busca, preco, origem, atualizado_em)
                       VALUES ('Covabra','Café','cafe ',10.0,'site',0)""")
        con.commit()
        con.close()

        self.db.criar()   # não pode estourar "no such column: ean"
        self.db.salvar_produtos([self.produto(ean="7891234567890")], fonte="teste")
        self.assertEqual(len(self.db.por_ean("7891234567890")), 1)


class TestAlertas(BaseComBancos):

    def test_checar_avisa_quando_abaixo_do_alvo(self):
        import alertas
        codigo = self.nova_familia({"lista": []})
        self.db.alerta_criar(codigo, "Café Pilão 500g", 15.0)
        self.db.salvar_produtos([self.produto(preco=14.0)], fonte="teste")
        enviados = []
        r = alertas.checar_alertas(avisar=lambda texto, chat=None: (enviados.append(texto), (True, "ok"))[1])
        self.assertEqual(len(r["disparos"]), 1)
        self.assertEqual(len(enviados), 1)
        self.assertIn("Café", enviados[0])

    def test_nao_avisa_acima_do_alvo(self):
        import alertas
        codigo = self.nova_familia({"lista": []})
        self.db.alerta_criar(codigo, "Café Pilão 500g", 15.0)
        self.db.salvar_produtos([self.produto(preco=19.0)], fonte="teste")
        enviados = []
        r = alertas.checar_alertas(avisar=lambda texto, chat=None: (enviados.append(texto), (True, "ok"))[1])
        self.assertEqual(r["disparos"], [])
        self.assertEqual(enviados, [])

    def test_silencio_evita_avisar_todo_dia(self):
        import alertas
        codigo = self.nova_familia({"lista": []})
        self.db.alerta_criar(codigo, "Café Pilão 500g", 15.0)
        self.db.salvar_produtos([self.produto(preco=14.0)], fonte="teste")
        enviados = []
        alertas.checar_alertas(avisar=lambda texto, chat=None: (enviados.append(texto), (True, "ok"))[1])
        alertas.checar_alertas(avisar=lambda texto, chat=None: (enviados.append(texto), (True, "ok"))[1])
        self.assertEqual(len(enviados), 1, "não pode avisar de novo no mesmo dia")

    def test_avisa_de_novo_se_cair_bem_mais(self):
        import alertas
        codigo = self.nova_familia({"lista": []})
        self.db.alerta_criar(codigo, "Café Pilão 500g", 15.0)
        self.db.salvar_produtos([self.produto(preco=14.0)], fonte="teste")
        enviados = []
        alertas.checar_alertas(avisar=lambda texto, chat=None: (enviados.append(texto), (True, "ok"))[1])
        self.db.salvar_produtos([self.produto(preco=11.0)], fonte="teste")
        alertas.checar_alertas(avisar=lambda texto, chat=None: (enviados.append(texto), (True, "ok"))[1])
        self.assertEqual(len(enviados), 2, "queda forte merece novo aviso")

    def test_telegram_desligado_nao_envia_mas_registra_quem_bateu(self):
        """Decisão do dono: Telegram desligado. A conferência continua, só não sai mensagem."""
        import alertas
        codigo = self.nova_familia()
        self.db.alerta_criar(codigo, "Café Pilão 500g", 15.0)
        self.db.salvar_produtos([self.produto(preco=14.0)], fonte="teste")
        # sem enviador injetado: usa o caminho real, que é o que precisa recusar
        r = alertas.checar_alertas()
        self.assertFalse(r["telegram"], "com a chave desligada, telegram deve ser False")
        self.assertEqual(len(r["bateram"]), 1, "quem bateu o alvo tem que aparecer no relatório")
        self.assertEqual(r["bateram"][0]["preco"], 14.0)
        self.assertEqual(r["disparos"], [], "nada pode ser enviado com o Telegram desligado")

    def test_enviar_telegram_recusa_quando_desligado(self):
        import alertas
        ok, detalhe = alertas.enviar_telegram("teste")
        self.assertFalse(ok)
        self.assertIn("desligado", detalhe.lower())

    def test_telegram_configurado_exige_chave_e_token(self):
        import alertas
        antes_chave, antes_token = alertas.TELEGRAM_LIGADO, os.environ.get("TELEGRAM_TOKEN")
        try:
            alertas.TELEGRAM_LIGADO = False
            os.environ["TELEGRAM_TOKEN"] = "123:abc"
            self.assertFalse(alertas.telegram_configurado(), "token sozinho não liga")
            alertas.TELEGRAM_LIGADO = True
            self.assertTrue(alertas.telegram_configurado())
            os.environ.pop("TELEGRAM_TOKEN")
            self.assertFalse(alertas.telegram_configurado(), "chave sozinha não liga")
        finally:
            alertas.TELEGRAM_LIGADO = antes_chave
            if antes_token is None:
                os.environ.pop("TELEGRAM_TOKEN", None)
            else:
                os.environ["TELEGRAM_TOKEN"] = antes_token

    def test_alerta_desligado_nao_avisa(self):
        import alertas
        codigo = self.nova_familia({"lista": []})
        self.db.alerta_criar(codigo, "Café Pilão 500g", 15.0)
        a = self.db.alertas_listar(codigo)[0]
        self.db.alerta_atualizar(a["id"], ativo=0)
        self.db.salvar_produtos([self.produto(preco=14.0)], fonte="teste")
        enviados = []
        alertas.checar_alertas(avisar=lambda texto, chat=None: (enviados.append(texto), (True, "ok"))[1])
        self.assertEqual(enviados, [])


class TestSaude(BaseComBancos):

    def test_saude_conta_so_os_alertas_da_familia(self):
        """O painel fica na aba Família: o número tem que casar com a lista que está ali."""
        import app
        f1 = self.nova_familia()
        f2 = self.nova_familia()
        self.db.alerta_criar(f1, "Café", 10.0)
        self.db.alerta_criar(f1, "Arroz", 20.0)
        self.db.alerta_criar(f2, "Leite", 5.0)
        self.assertEqual(app.saude(f1)["alertas_ativos"], 2)
        self.assertEqual(app.saude(f2)["alertas_ativos"], 1)
        self.assertEqual(app.saude()["alertas_ativos"], 3, "sem família, conta todos")

    def test_saude_avisa_sem_coleta(self):
        import app
        s = app.saude()
        self.assertFalse(s["ok"])
        self.assertIn("nenhuma coleta registrada ainda", s["avisos"])

    def test_saude_ok_depois_de_coleta(self):
        import app
        self.serie("Covabra", "Café", [10.0, 11.0])
        i = self.db.execucao_iniciar("coleta")
        self.db.execucao_terminar(i, True, "ok")
        s = app.saude()
        self.assertTrue(s["ok"], s["avisos"])
        self.assertEqual(s["avisos"], [])


class TestExportacao(BaseComBancos):

    def test_exportar_historico_formato_compacto(self):
        import gerar_site
        self.serie("Covabra", "Café", [10.0, 11.0, 12.0])
        h = gerar_site.exportar_historico()
        self.assertIn("Covabra|Café", h)
        pontos = h["Covabra|Café"]
        self.assertEqual(len(pontos), 3)
        self.assertEqual(len(pontos[0]), 2)
        self.assertIsInstance(pontos[0][0], int)   # epoch
        self.assertIsInstance(pontos[0][1], float)

    def test_exportar_respeita_limite_de_produtos(self):
        import gerar_site
        for i in range(10):
            self.serie("Covabra", f"Produto {i}", [10.0, 11.0])
        h = gerar_site.exportar_historico(max_produtos=3)
        self.assertEqual(len(h), 3)

    def test_exportar_sem_historico_devolve_vazio(self):
        import gerar_site
        self.assertEqual(gerar_site.exportar_historico(), {})

    @staticmethod
    def _dias_atras(n, preco):
        """Ponto no formato publicado: [dia (dias desde 1970) de n dias atrás, preço]."""
        import calendar
        import time
        dia = time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))
        return [calendar.timegm(time.strptime(dia, "%Y-%m-%d")) // 86400, preco]

    def test_preco_parado_ocupa_dois_pontos(self):
        """Todo o catálogo só cabe porque a série guarda as mudanças, não todos os dias."""
        import gerar_site
        self.serie("Covabra", "Café", [10.0] * 30 + [12.0] * 5)
        pontos = gerar_site.exportar_historico()["Covabra|Café"]
        self.assertEqual([p[1] for p in pontos], [10.0, 10.0, 12.0, 12.0])
        self.assertEqual(pontos[1][0] - pontos[0][0], 29)
        self.assertEqual(len(gerar_site._expandir_serie(pontos)), 35, "expandir devolve um preço por dia")

    def test_serie_compacta_continua_no_dia_seguinte(self):
        """O publicado já vem compacto; o dia novo estica o fim do preço ou abre um preço novo."""
        import gerar_site
        anterior = {"Covabra|Café": [self._dias_atras(9, 10.0), self._dias_atras(1, 10.0)]}
        self.serie("Covabra", "Café", [10.0], dias_atras=[0])
        mesmo = gerar_site.exportar_historico(anteriores=anterior)["Covabra|Café"]
        self.assertEqual(mesmo, [self._dias_atras(9, 10.0), self._dias_atras(0, 10.0)])
        self.serie("Covabra", "Chá", [8.0], dias_atras=[0])
        mudou = gerar_site.exportar_historico(
            anteriores={"Covabra|Chá": [self._dias_atras(9, 7.0), self._dias_atras(1, 7.0)]})["Covabra|Chá"]
        self.assertEqual([p[1] for p in mudou], [7.0, 7.0, 8.0])

    def test_aceita_o_formato_antigo_em_segundos(self):
        import gerar_site
        dia = self._dias_atras(1, 0)[0]
        h = gerar_site.exportar_historico(anteriores={"Assaí|Arroz": [[dia * 86400, 20.0]]})
        self.assertEqual(h, {"Assaí|Arroz": [[dia, 20.0]]})

    def test_historico_entra_para_o_catalogo_inteiro(self):
        import gerar_site
        import inspect
        padrao = inspect.signature(gerar_site.exportar_historico).parameters["max_produtos"].default
        self.assertGreaterEqual(padrao, 100000)

    def test_exportar_herda_historico_do_site_publicado(self):
        """O Actions roda sem banco: o publicado é o arquivo de longo prazo."""
        import gerar_site
        self.serie("Covabra", "Café", [10.0, 11.0])
        anterior = {"Assaí|Arroz": [self._dias_atras(3, 20.0), self._dias_atras(2, 21.0)]}
        h = gerar_site.exportar_historico(anteriores=anterior)
        self.assertIn("Covabra|Café", h, "o dia novo tem que entrar")
        self.assertIn("Assaí|Arroz", h, "o passado publicado tem que ser preservado")
        self.assertEqual(h["Assaí|Arroz"], anterior["Assaí|Arroz"])

    def test_exportar_sem_banco_mas_com_anterior_nao_perde_nada(self):
        """Banco vazio, só o publicado. Não pode devolver vazio."""
        import gerar_site
        anterior = {"Assaí|Arroz": [self._dias_atras(3, 20.0), self._dias_atras(2, 21.0)]}
        h = gerar_site.exportar_historico(anteriores=anterior)
        self.assertEqual(h, anterior)

    def test_dia_novo_soma_aos_dias_publicados(self):
        """O caso real do Actions: o banco só tem hoje e o site publicado tem os dias de antes.
        Era aqui que o histórico parava em 1 ponto: os dias publicados eram jogados fora."""
        import gerar_site
        self.serie("Covabra", "Café", [12.0], dias_atras=[0])                      # só o dia de hoje
        anterior = {"Covabra|Café": [self._dias_atras(2, 10.0), self._dias_atras(1, 11.0)]}
        h = gerar_site.exportar_historico(anteriores=anterior)
        self.assertEqual([p[1] for p in h["Covabra|Café"]], [10.0, 11.0, 12.0])
        # e no dia seguinte continua crescendo, mesmo partindo de um publicado com 1 ponto só
        h2 = gerar_site.exportar_historico(anteriores={"Covabra|Café": [self._dias_atras(1, 11.0)]})
        self.assertEqual([p[1] for p in h2["Covabra|Café"]], [11.0, 12.0])

    def test_mesmo_dia_vale_o_banco(self):
        """Coleta repetida no mesmo dia não duplica o ponto: fica o preço do banco."""
        import gerar_site
        self.serie("Covabra", "Café", [12.0], dias_atras=[0])
        h = gerar_site.exportar_historico(anteriores={"Covabra|Café": [self._dias_atras(0, 99.0)]})
        self.assertEqual([p[1] for p in h["Covabra|Café"]], [12.0])

    def test_pontos_velhos_ou_quebrados_saem(self):
        import gerar_site
        anterior = {"Assaí|Arroz": [[1700000000, 20.0], self._dias_atras(2, 21.0), ["x", 1], [5]],
                    "Assaí|Feijão": [[1700000000, 8.0]], "Assaí|Lixo": "não é lista"}
        h = gerar_site.exportar_historico(anteriores=anterior)
        self.assertEqual(h, {"Assaí|Arroz": [self._dias_atras(2, 21.0)]})

    def test_teto_prefere_quem_tem_mais_dias_e_reparte_entre_mercados(self):
        import gerar_site
        anterior = {f"Akki|Item {i}": [self._dias_atras(1, 5.0)] for i in range(5)}
        anterior["Zaffari|Leite"] = [self._dias_atras(1, 6.0)]
        anterior["Zaffari|Café"] = [self._dias_atras(3, 9.0), self._dias_atras(2, 9.5), self._dias_atras(1, 9.0)]
        h = gerar_site.exportar_historico(max_produtos=3, anteriores=anterior)
        self.assertEqual(len(h), 3)
        self.assertIn("Zaffari|Café", h, "a série mais longa não pode ser cortada")
        self.assertIn("Zaffari|Leite", h, "o último mercado da ordem alfabética também entra")


class TestLeitorDeFolhetos(unittest.TestCase):

    def test_tipo_da_imagem_aceito_pelo_gemini(self):
        from coletores.extrator_ia import _tipo_da_imagem as t
        self.assertEqual(t("https://x/campanha-50023-pagina-1.jpeg", "binary/octet-stream"), "image/jpeg")
        self.assertEqual(t("https://x/a.png?v=2", "application/octet-stream"), "image/png")
        self.assertEqual(t("https://x/a.webp", "text/plain"), "image/webp")
        self.assertEqual(t("https://x/TABLOIDE.PDF", "image/jpeg"), "application/pdf")
        self.assertEqual(t("https://x/sem-extensao", "image/png"), "image/png")
        self.assertEqual(t("https://x/sem-extensao", ""), "image/jpeg")


class TestColetores(unittest.TestCase):

    def test_pague_menos_usa_a_busca_vtex(self):
        """Em 11/2026 a loja trocou de plataforma e a busca antiga passou a dar 404."""
        from coletores import sites
        self.assertEqual(sites.VTEX.get("Pague Menos"), "www.superpaguemenos.com.br")
        self.assertIn("Pague Menos", dict(sites.fontes("paulinia")))

    def test_busca_vtex_nao_aceita_redirecionamento(self):
        """Sem allowRedirect=false, "arroz" volta com zero produtos e um redirecionamento."""
        from coletores import sites
        vistos = []
        original = sites.http_json
        sites.http_json = lambda url, *a, **k: vistos.append(url) or {"products": []}
        try:
            sites.buscar_vtex("Pague Menos", "www.superpaguemenos.com.br", "arroz")
        finally:
            sites.http_json = original
        self.assertIn("allowRedirect=false", vistos[0])


class TestInterface(unittest.TestCase):
    """O index.html é um arquivo só: estes testes pegam erro de sintaxe e peça faltando."""

    @classmethod
    def setUpClass(cls):
        cls.raiz = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(cls.raiz, "static", "index.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def test_tem_manifest_e_service_worker(self):
        self.assertIn('rel="manifest"', self.html)
        self.assertIn("serviceWorker", self.html)

    def test_tem_as_abas(self):
        for aba in ("Favoritos", "Lista", "Família", "Folhetos"):
            self.assertIn(aba, self.html, f"aba {aba} sumiu")

    def test_abas_embaixo_e_tela_mais(self):
        """Cinco abas na barra; Folhetos e Família abrem a partir de Mais."""
        for aba in ("comparar", "ofertas", "favoritos", "lista", "mais"):
            self.assertIn(f'data-aba="{aba}"', self.html, f"aba {aba} sumiu da barra")
        for destino in ("folhetos", "familia"):
            self.assertIn(f'data-ir="{destino}"', self.html, f"falta o caminho para {destino}")
        self.assertIn("function abrirAba(", self.html)

    def test_meus_mercados_e_lista_dividida(self):
        self.assertIn('id="meusMercados"', self.html)
        self.assertIn("ofertas-mercados-off", self.html, "a escolha dos mercados tem que ficar salva")
        self.assertIn("!this.desligados.has(m)", self.html, "mercado desligado não pode entrar em Regiao.tem")
        self.assertIn('data-modo="dois"', self.html)
        self.assertIn("function melhorDupla(", self.html)

    def test_veredito_local_espelha_o_python(self):
        """Se a regra mudar num lado e não no outro, o site e o app discordam."""
        for pedaco in ("MIN_DIAS_JULGAR = 14", 'veredito: "inflada"', 'veredito: "boa"',
                       'veredito: "cara"', 'veredito: "normal"', 'veredito: "sem_historico"'):
            self.assertIn(pedaco, self.html, f"regra {pedaco} não está no index.html")

    def test_le_historico_json_no_modo_estatico(self):
        self.assertIn('json("historico.json"', self.html)
        self.assertIn("this.historico", self.html)

    def test_arquivos_do_pwa_existem(self):
        for nome in ("manifest.json", "sw.js", "icone-192.png", "icone-512.png"):
            caminho = os.path.join(self.raiz, "static", nome)
            self.assertTrue(os.path.exists(caminho), f"falta static/{nome}")

    def test_manifest_valido(self):
        with open(os.path.join(self.raiz, "static", "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["lang"], "pt-BR")
        self.assertEqual(len(m["icons"]), 3)


class TestDeploy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raiz = os.path.dirname(os.path.abspath(__file__))

    def test_arquivos_de_deploy_existem(self):
        for nome in ("instalar.sh", "entrada.sh", "nginx-ofertas.conf"):
            self.assertTrue(os.path.exists(os.path.join(self.raiz, "deploy", nome)), nome)

    def test_instalador_cria_servico_systemd(self):
        with open(os.path.join(self.raiz, "deploy", "instalar.sh"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn("systemd", s)
        self.assertIn("servidor.py", s)
        self.assertIn("/var/lib/ofertas-sp", s)

    def test_dockerfile_roda_servidor(self):
        with open(os.path.join(self.raiz, "Dockerfile"), encoding="utf-8") as f:
            d = f.read()
        self.assertIn("servidor.py", d)
        self.assertIn("EXPOSE", d)

    def test_compose_tem_volume_e_healthcheck(self):
        with open(os.path.join(self.raiz, "docker-compose.yml"), encoding="utf-8") as f:
            c = f.read()
        self.assertIn("volumes", c)
        self.assertIn("healthcheck", c)
        self.assertIn("/api/saude", c)

    def test_servidor_nao_escuta_so_localhost(self):
        with open(os.path.join(self.raiz, "servidor.py"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn("0.0.0.0", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
