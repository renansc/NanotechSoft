import unittest
from unittest import mock
from pathlib import Path
import tempfile
import datetime

import tools.riob_agent_web as agent_web


class _FakeCursor:
    def __init__(self, handlers):
        self._handlers = handlers
        self._index = -1
        self._current = None

    def execute(self, query, params=None):
        self._index += 1
        self._current = self._handlers[self._index](query, params)

    def fetchone(self):
        if isinstance(self._current, list):
            return self._current[0] if self._current else None
        return self._current

    def fetchall(self):
        if isinstance(self._current, list):
            return self._current
        if self._current is None:
            return []
        return [self._current]

    def close(self):
        return None


class _FakeConnection:
    def __init__(self, handlers):
        self._handlers = handlers

    def cursor(self, dictionary=True):
        return _FakeCursor(self._handlers)

    def close(self):
        return None


class RioBrancoAgentWebTests(unittest.TestCase):
    def test_handle_chat_uses_llm_reply_when_available(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value='{"type":"reply","reply":"Oi"}'), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "oi", "history": []})

        self.assertEqual(result["reply"], "Oi")

    def test_handle_chat_uses_llm_action(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value='{"type":"action","action":"status"}'), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True), \
            mock.patch.object(agent_web, "run_agent", return_value={"reply": "Status concluido"}):
            result = agent_web.handle_chat({"message": "ver status", "history": []})

        self.assertTrue(result["reply"].startswith("Status concluido"))
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_falls_back_to_legacy_logic(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=False), \
            mock.patch.object(agent_web, "list_fretes_response", return_value={"reply": "Lista local"}):
            result = agent_web.handle_chat({"message": "listar cargas"})

        self.assertEqual(result["reply"], "Lista local")

    def test_handle_chat_adds_suggested_actions_for_reply_only(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value='{"type":"reply","reply":"Posso ajudar com deploy."}'), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "o que faz deploy?", "history": []})

        self.assertTrue(result["reply"].startswith("Posso ajudar com deploy."))
        self.assertIn("Fontes:", result["reply"])
        self.assertTrue(any(action["name"] == "deploy" for action in result.get("actions", [])))

    def test_handle_chat_uses_local_context_for_ip_questions(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual meu ip interno?", "history": []})

        self.assertIn("O IP interno do ambiente", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_local_context_for_cnpj_questions(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual o cnpj da empresa?", "history": []})

        self.assertIn("20.984.401/0001-30", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_local_context_for_storage_questions(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual o diretorio das fotos de devolucao?", "history": []})

        self.assertIn("FotosDevolucoes", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_devolucao_lookup_for_vehicle(self):
        devolucoes = [
            {
                "id": 21,
                "frete_id": 137,
                "veiculo_id": 14,
                "veiculo_nome": "14",
                "frete_nome": "Campina da Lagoa",
                "conferente_nome": "Joao",
                "c24": 2,
                "pet2l": 1,
                "fotos": ["devolucao_21/1.jpg"],
                "tem_fotos": True,
            }
        ]
        with mock.patch.object(agent_web, "system_api", return_value=devolucoes), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "o que tem de lancamento de devolucao para o caminhao 14", "history": []})

        self.assertIn("caminhao 14", result["reply"].lower())
        self.assertIn("#21", result["reply"])
        self.assertIn("c24=2", result["reply"])
        self.assertIn("pet2l=1", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_lists_fretes_without_devolucao(self):
        devolucoes = [
            {
                "id": 21,
                "frete_id": 137,
                "veiculo_id": 14,
                "veiculo_nome": "14",
                "frete_nome": "Campina da Lagoa",
                "conferente_nome": "Joao",
            }
        ]
        fretes = [
            {
                "id": 138,
                "status": "entregando",
                "veiculo_nome": "13",
                "veiculo_placa": "ABC1D23",
                "carga_nome": "Jaguapita",
            },
            {
                "id": 137,
                "status": "carregado",
                "veiculo_nome": "14",
                "veiculo_placa": "DEF4G56",
                "carga_nome": "Campina da Lagoa",
            },
        ]

        def fake_system_api(method, path, payload=None, timeout=20):
            if path == "/api/devolucoes":
                return devolucoes
            if path == "/api/fretes":
                return fretes
            raise AssertionError(f"rota inesperada: {path}")

        with mock.patch.object(agent_web, "system_api", side_effect=fake_system_api), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual caminhao nao tem devolucao lancada?", "history": []})

        self.assertIn("sem devolucao lancada", result["reply"].lower())
        self.assertIn("Frete #138", result["reply"])
        self.assertIn("Caminhao 13", result["reply"])
        self.assertNotIn("Frete #137", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_says_when_all_current_fretes_have_devolucao(self):
        devolucoes = [
            {
                "id": 21,
                "frete_id": 137,
                "veiculo_id": 14,
                "veiculo_nome": "14",
                "frete_nome": "Campina da Lagoa",
                "conferente_nome": "Joao",
            }
        ]
        fretes = [
            {
                "id": 137,
                "status": "carregado",
                "veiculo_nome": "14",
                "veiculo_placa": "DEF4G56",
                "carga_nome": "Campina da Lagoa",
            }
        ]

        def fake_system_api(method, path, payload=None, timeout=20):
            if path == "/api/devolucoes":
                return devolucoes
            if path == "/api/fretes":
                return fretes
            raise AssertionError(f"rota inesperada: {path}")

        with mock.patch.object(agent_web, "system_api", side_effect=fake_system_api), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual caminhao nao tem devolucao lancada?", "history": []})

        self.assertIn("nao encontrei caminhao sem devolucao lancada", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_frete_card_lookup_by_exact_km(self):
        cards = [
            {
                "id": 138,
                "vehicle": "13",
                "plate": "ABC1D23",
                "load": "Jaguapita",
                "status_label": "Entregando",
                "raw": {
                    "km_atual": 120500,
                    "peso": 18500.0,
                    "carga_peso_total": 18500.0,
                },
            },
            {
                "id": 139,
                "vehicle": "14",
                "plate": "DEF4G56",
                "load": "Campina da Lagoa",
                "status_label": "Carregado",
                "raw": {
                    "km_atual": 98000,
                    "peso": 21000.0,
                    "carga_peso_total": 21000.0,
                },
            },
        ]

        with mock.patch.object(agent_web, "list_fretes", return_value=cards), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual caminhao esta com km atual 120500?", "history": []})

        self.assertIn("KM atual 120500", result["reply"])
        self.assertIn("Frete #138", result["reply"])
        self.assertIn("Caminhao 13", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_frete_card_lookup_by_weight(self):
        cards = [
            {
                "id": 138,
                "vehicle": "13",
                "plate": "ABC1D23",
                "load": "Jaguapita",
                "status_label": "Entregando",
                "raw": {
                    "km_atual": 120500,
                    "peso": 18500.0,
                    "carga_peso_total": 18500.0,
                    "qtd_entregas": 24,
                },
            },
            {
                "id": 139,
                "vehicle": "14",
                "plate": "DEF4G56",
                "load": "Campina da Lagoa",
                "status_label": "Carregado",
                "raw": {
                    "km_atual": 98000,
                    "peso": 21000.0,
                    "carga_peso_total": 21000.0,
                    "qtd_entregas": 37,
                },
            },
        ]

        with mock.patch.object(agent_web, "list_fretes", return_value=cards), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual caminhao esta com peso 21.000?", "history": []})

        self.assertIn("peso 21.000", result["reply"])
        self.assertIn("Frete #139", result["reply"])
        self.assertIn("Caminhao 14", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_frete_card_lookup_by_delivery_count(self):
        cards = [
            {
                "id": 138,
                "vehicle": "13",
                "plate": "ABC1D23",
                "load": "Jaguapita",
                "status_label": "Entregando",
                "deliveries": 24,
                "raw": {
                    "km_atual": 120500,
                    "peso": 18500.0,
                    "carga_peso_total": 18500.0,
                    "qtd_entregas": 24,
                },
            },
            {
                "id": 139,
                "vehicle": "14",
                "plate": "DEF4G56",
                "load": "Campina da Lagoa",
                "status_label": "Carregado",
                "deliveries": 37,
                "raw": {
                    "km_atual": 98000,
                    "peso": 21000.0,
                    "carga_peso_total": 21000.0,
                    "qtd_entregas": 37,
                },
            },
        ]

        with mock.patch.object(agent_web, "list_fretes", return_value=cards), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual caminhao que tem entregas 37?", "history": []})

        self.assertIn("Entregas 37", result["reply"])
        self.assertIn("Frete #139", result["reply"])
        self.assertIn("Caminhao 14", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_parse_devolucao_mentions_accepts_written_number_and_reversed_pet2l(self):
        parsed = agent_web.parse_devolucao_mentions("lancar devolucao frete 97 oito pacote 2l pet")

        self.assertEqual(parsed["items"]["pet2l"], 8)

    def test_parse_devolucao_mentions_accepts_pet2_short_alias(self):
        parsed = agent_web.parse_devolucao_mentions("lancar devolucao frete 97 pet 2 3")

        self.assertEqual(parsed["items"]["pet2l"], 3)

    def test_parse_devolucao_mentions_accepts_other_items_and_inline_observations(self):
        parsed = agent_web.parse_devolucao_mentions(
            "lancar devolucao frete 97 quatro 24 caixa molhada tres 600 pet avariado duas agua sem gas furada"
        )

        self.assertEqual(parsed["items"]["c24"], 4)
        self.assertEqual(parsed["obs"]["obs_c24"], "molhada")
        self.assertEqual(parsed["items"]["pet600"], 3)
        self.assertEqual(parsed["obs"]["obs_pet600"], "avariado")
        self.assertEqual(parsed["items"]["agua_sem_gas"], 2)
        self.assertEqual(parsed["obs"]["obs_agua_sem_gas"], "furada")

    def test_parse_devolucao_mentions_accepts_operational_synonyms_and_obs_marker(self):
        parsed = agent_web.parse_devolucao_mentions(
            "lancar devolucao frete 97 duas garrafa 200 obs riscada tres fardo 48 obs molhado uma cg estourada"
        )

        self.assertEqual(parsed["items"]["pet200"], 2)
        self.assertEqual(parsed["obs"]["obs_pet200"], "riscada")
        self.assertEqual(parsed["items"]["c48"], 3)
        self.assertEqual(parsed["obs"]["obs_c48"], "molhado")
        self.assertEqual(parsed["items"]["agua_com_gas"], 1)
        self.assertEqual(parsed["obs"]["obs_agua_com_gas"], "estourada")

    def test_handle_chat_uses_environment_context_for_os_and_db(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual o sistema operacional e o banco de dados?", "history": []})

        self.assertIn("runtime", result["reply"].lower())
        self.assertIn("MariaDB", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_environment_context_for_container_names(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual o nome dos containers que rodam a aplicacao?", "history": []})

        self.assertIn("riobranco-app", result["reply"])
        self.assertIn("riobranco-proxy", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_database_lookup_for_vehicle_count(self):
        fake_cursor = mock.Mock()
        fake_cursor.fetchone.return_value = {"total": 7}
        fake_conn = mock.Mock()
        fake_conn.cursor.return_value = fake_cursor

        with mock.patch.object(agent_web.mysql.connector, "connect", return_value=fake_conn), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quantos caminhões tem cadastrado?", "history": []})

        self.assertIn("7", result["reply"])
        self.assertIn("veiculo", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_database_lookup_for_loading_freight_route(self):
        fake_cursor = mock.Mock()
        fake_cursor.fetchall.return_value = [
            {
                "id": 42,
                "status": "carregando",
                "veiculo_nome_resolvido": "13",
                "veiculo_placa_resolvida": "ABC1D23",
                "carga_nome": "Carga Jaguapita",
                "carga_rota": "Jaguapita",
                "cidade": "Jaguapita",
            }
        ]
        fake_conn = mock.Mock()
        fake_conn.cursor.return_value = fake_cursor

        with mock.patch.object(agent_web.mysql.connector, "connect", return_value=fake_conn), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual caminhao esta carregando para rota de jaguapita?", "history": []})

        self.assertIn("Jaguapita", result["reply"])
        self.assertIn("carregando", result["reply"].lower())
        self.assertIn("Caminhao 13", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_matches_route_with_removed_stopwords(self):
        fake_cursor = mock.Mock()
        fake_cursor.fetchall.return_value = [
            {
                "id": 55,
                "status": "carregado",
                "veiculo_nome_resolvido": "55",
                "veiculo_placa_resolvida": "DEF5G67",
                "carga_nome": "Carga Campina da Lagoa",
                "carga_rota": "Campina da Lagoa",
                "cidade": "Campina da Lagoa",
            }
        ]
        fake_conn = mock.Mock()
        fake_conn.cursor.return_value = fake_cursor

        with mock.patch.object(agent_web.mysql.connector, "connect", return_value=fake_conn), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual caminhao esta carregado para campina da lagoa?", "history": []})

        self.assertIn("Campina da Lagoa", result["reply"])
        self.assertIn("carregado", result["reply"].lower())
        self.assertIn("Caminhao 55", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_counts_freight_trucks_by_status(self):
        fake_cursor = mock.Mock()
        fake_cursor.fetchone.return_value = {"total": 5}
        fake_conn = mock.Mock()
        fake_conn.cursor.return_value = fake_cursor

        with mock.patch.object(agent_web.mysql.connector, "connect", return_value=fake_conn), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quantos caminhões estão liberados para carregar?", "history": []})

        self.assertIn("5", result["reply"])
        self.assertIn("liberados para carregar", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_stock_lookup_for_current_balance(self):
        estoque_payload = {
            "rows": [
                {"nome_produto": "Agua 20L", "quantidade_atual": 120.0, "quantidade_comprometida": 20.0},
                {"nome_produto": "Agua 10L", "quantidade_atual": 80.0, "quantidade_comprometida": 10.0},
            ],
            "meta": {"data_referencia": "2025-01-10"},
        }
        with mock.patch.object(agent_web, "system_api", return_value=estoque_payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quanto tenho em estoque no momento?", "history": [], "chat_mode": "ia"})

        self.assertIn("200.000", result["reply"])
        self.assertIn("estoque consolidado", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_stock_lookup_for_highest_balance_product(self):
        estoque_payload = {
            "rows": [
                {"nome_produto": "Agua 20L", "quantidade_atual": 120.0, "quantidade_comprometida": 20.0},
                {"nome_produto": "Agua 10L", "quantidade_atual": 80.0, "quantidade_comprometida": 10.0},
                {"nome_produto": "Refri 2L", "quantidade_atual": 150.0, "quantidade_comprometida": 5.0},
            ],
            "meta": {"data_referencia": "2025-01-10"},
        }
        with mock.patch.object(agent_web, "system_api", return_value=estoque_payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual produto tem mais estoque agora?", "history": [], "chat_mode": "ia"})

        self.assertIn("maior saldo", result["reply"].lower())
        self.assertIn("Refri 2L", result["reply"])
        self.assertIn("150.000", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_frota_summary_for_overdue_maintenance(self):
        frota_rows = [
            {
                "id": 9,
                "nome": "Caminhao 9",
                "placa": "AIO-7875",
                "km_atual": 154000,
                "falta_manut_km": -250,
                "falta_oleo_km": 1200,
            },
            {
                "id": 10,
                "nome": "Caminhao 10",
                "placa": "BBB-1234",
                "km_atual": 89000,
                "falta_manut_km": 800,
                "falta_oleo_km": -50,
            },
        ]
        with mock.patch.object(agent_web, "system_api", return_value=frota_rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "na minha frota, tem algum veiculo com manutencao atrasada ou troca de oleo vencida?", "history": []})

        self.assertIn("Caminhao 9", result["reply"])
        self.assertIn("troca de oleo vencida", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_broad_system_read_for_sip_config(self):
        sip_payload = {
            "habilitado": True,
            "modo_ativo": "freepbx",
            "freepbx": {"host": "pbx.local", "usuario": "100"},
        }
        with mock.patch.object(agent_web, "system_api", return_value=sip_payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual a configuracao sip atual?", "history": []})

        self.assertIn("configuracao SIP", result["reply"])
        self.assertIn("modo_ativo", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_broad_system_read_for_abastecimentos(self):
        abastecimentos = [
            {
                "id": 15,
                "veiculo_nome": "Caminhao 5",
                "placa": "ABC-1234",
                "km": 120500,
                "posto": "Posto Central",
                "combustivel_tipo": "diesel",
                "status": "abastecido",
            }
        ]
        with mock.patch.object(agent_web, "system_api", return_value=abastecimentos), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "listar abastecimentos recentes", "history": []})

        self.assertIn("abastecimentos", result["reply"])
        self.assertIn("Caminhao 5", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_time_window_for_stock_movements(self):
        now = datetime.datetime.now()
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": now.strftime("%Y-%m-%d %H:%M:%S")},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": (now - datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": (now - datetime.timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque dos ultimos 7 dias", "history": []})

        self.assertIn("ultimos 7 dias", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_explicit_date_range_for_stock_movements(self):
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": "2025-03-02 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": "2025-03-12 10:00:00"},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": "2025-03-18 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque de 01/03/2025 a 15/03/2025", "history": []})

        self.assertIn("de 01/03/2025 a 15/03/2025", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_natural_month_range_for_stock_movements(self):
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": "2025-03-02 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": "2025-03-12 10:00:00"},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": "2025-03-18 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque de 1 a 15 de marco de 2025", "history": []})

        self.assertIn("de 01/03/2025 a 15/03/2025", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_first_fortnight_for_stock_movements(self):
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": "2025-03-02 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": "2025-03-14 10:00:00"},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": "2025-03-20 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque da primeira quinzena de marco de 2025", "history": []})

        self.assertIn("primeira quinzena de marco/2025", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_start_of_month_for_stock_movements(self):
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": "2025-03-02 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": "2025-03-09 10:00:00"},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": "2025-03-14 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque do inicio de marco de 2025", "history": []})

        self.assertIn("inicio de marco/2025", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_first_semester_for_stock_movements(self):
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": "2025-02-02 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": "2025-06-09 10:00:00"},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": "2025-08-14 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque do primeiro semestre de 2025", "history": []})

        self.assertIn("primeiro semestre de 2025", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_second_semester_for_stock_movements(self):
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": "2025-02-02 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": "2025-07-09 10:00:00"},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": "2025-11-14 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque do segundo semestre de 2025", "history": []})

        self.assertIn("segundo semestre de 2025", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_last_week_for_stock_movements(self):
        today = datetime.date.today()
        start_current_week = today - datetime.timedelta(days=today.weekday())
        last_week_day = start_current_week - datetime.timedelta(days=2)
        older_day = start_current_week - datetime.timedelta(days=10)
        current_week_day = start_current_week + datetime.timedelta(days=1)
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": f"{last_week_day:%Y-%m-%d} 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": f"{older_day:%Y-%m-%d} 10:00:00"},
            {"id": 3, "nome_produto": "Suco 1L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": f"{current_week_day:%Y-%m-%d} 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque da semana passada", "history": []})

        self.assertIn("semana passada", result["reply"])
        self.assertIn("1 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_week_before_last_for_stock_movements(self):
        today = datetime.date.today()
        start_current_week = today - datetime.timedelta(days=today.weekday())
        week_before_last_day = start_current_week - datetime.timedelta(days=9)
        last_week_day = start_current_week - datetime.timedelta(days=2)
        current_week_day = start_current_week + datetime.timedelta(days=1)
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": f"{week_before_last_day:%Y-%m-%d} 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": f"{last_week_day:%Y-%m-%d} 10:00:00"},
            {"id": 3, "nome_produto": "Suco 1L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": f"{current_week_day:%Y-%m-%d} 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque da semana retrasada", "history": []})

        self.assertIn("semana retrasada", result["reply"])
        self.assertIn("1 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_end_of_last_month_for_stock_movements(self):
        today = datetime.date.today()
        last_month_start = datetime.date(today.year - 1, 12, 1) if today.month == 1 else datetime.date(today.year, today.month - 1, 1)
        this_month_start = datetime.date(today.year, today.month, 1)
        inside_a = max(last_month_start, this_month_start - datetime.timedelta(days=3))
        inside_b = max(last_month_start, this_month_start - datetime.timedelta(days=8))
        outside = max(last_month_start, this_month_start - datetime.timedelta(days=15))
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": f"{inside_a:%Y-%m-%d} 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": f"{inside_b:%Y-%m-%d} 10:00:00"},
            {"id": 3, "nome_produto": "Suco 1L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": f"{outside:%Y-%m-%d} 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque do fim do mes passado", "history": []})

        self.assertIn("fim do mes passado", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_business_days_for_stock_movements(self):
        today = datetime.date.today()
        selected_days = []
        cursor = today
        while len(selected_days) < 5:
            if cursor.weekday() < 5:
                selected_days.append(cursor)
            cursor -= datetime.timedelta(days=1)
        saturday = None
        cursor = today
        while saturday is None:
            if cursor.weekday() == 5:
                saturday = cursor
            cursor -= datetime.timedelta(days=1)
        rows = [
            {"id": index + 1, "nome_produto": f"Produto {index + 1}", "quantidade": 1.0, "tipo_movimento": "entrada", "data_registro": f"{day:%Y-%m-%d} 09:00:00"}
            for index, day in enumerate(selected_days)
        ]
        rows.append({"id": 99, "nome_produto": "Produto Sabado", "quantidade": 1.0, "tipo_movimento": "saida", "data_registro": f"{saturday:%Y-%m-%d} 10:00:00"})
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque dos ultimos 5 dias uteis", "history": []})

        self.assertIn("ultimos 5 dias uteis", result["reply"])
        self.assertIn("5 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_rolling_days_comparison_for_stock_movements(self):
        today = datetime.date.today()
        rows = [
            {"id": 1, "nome_produto": "Produto A", "quantidade": 1.0, "tipo_movimento": "entrada", "data_registro": f"{today:%Y-%m-%d} 09:00:00"},
            {"id": 2, "nome_produto": "Produto B", "quantidade": 1.0, "tipo_movimento": "saida", "data_registro": f"{(today - datetime.timedelta(days=10)):%Y-%m-%d} 10:00:00"},
            {"id": 3, "nome_produto": "Produto C", "quantidade": 1.0, "tipo_movimento": "entrada", "data_registro": f"{(today - datetime.timedelta(days=40)):%Y-%m-%d} 11:00:00"},
            {"id": 4, "nome_produto": "Produto D", "quantidade": 1.0, "tipo_movimento": "saida", "data_registro": f"{(today - datetime.timedelta(days=50)):%Y-%m-%d} 12:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "comparar ultimos 30 dias vs 30 dias anteriores nos movimentos de estoque", "history": []})

        self.assertIn("Comparativo temporal", result["reply"])
        self.assertIn("ultimos 30 dias", result["reply"])
        self.assertIn("30 dias anteriores", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_product_drop_business_comparison(self):
        today = datetime.date.today()
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 2.0, "tipo_movimento": "saida", "data_registro": f"{today:%Y-%m-%d} 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 4.0, "tipo_movimento": "saida", "data_registro": f"{today:%Y-%m-%d} 10:00:00"},
            {"id": 3, "nome_produto": "Agua 20L", "quantidade": 8.0, "tipo_movimento": "entrada", "data_registro": f"{(today - datetime.timedelta(days=35)):%Y-%m-%d} 11:00:00"},
            {"id": 4, "nome_produto": "Refri 2L", "quantidade": 1.0, "tipo_movimento": "entrada", "data_registro": f"{(today - datetime.timedelta(days=40)):%Y-%m-%d} 12:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual produto mais caiu nos ultimos 30 dias vs 30 dias anteriores nos movimentos de estoque?", "history": []})

        self.assertIn("produto que mais caiu", result["reply"].lower())
        self.assertIn("Agua 20L", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_last_quarter_for_stock_movements(self):
        now = datetime.datetime.now()
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": (now - datetime.timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": (now - datetime.timedelta(days=70)).strftime("%Y-%m-%d %H:%M:%S")},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": (now - datetime.timedelta(days=110)).strftime("%Y-%m-%d %H:%M:%S")},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar movimentos de estoque do ultimo trimestre", "history": []})

        self.assertIn("ultimo trimestre", result["reply"])
        self.assertIn("2 registro(s)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_year_comparison_for_stock_movements(self):
        today = datetime.date.today()
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": f"{today.year}-02-10 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": f"{today.year}-04-12 10:00:00"},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": f"{today.year - 1}-03-18 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "comparar este ano vs ano passado nos movimentos de estoque", "history": []})

        self.assertIn("Comparativo temporal", result["reply"])
        self.assertIn("este ano", result["reply"].lower())
        self.assertIn("ano passado", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_same_period_last_year_for_stock_movements(self):
        today = datetime.date.today()
        rows = [
            {"id": 1, "nome_produto": "Agua 20L", "quantidade": 10.0, "tipo_movimento": "entrada", "data_registro": f"{today.year}-{today.month:02d}-02 09:00:00"},
            {"id": 2, "nome_produto": "Refri 2L", "quantidade": 5.0, "tipo_movimento": "saida", "data_registro": f"{today.year}-{today.month:02d}-10 10:00:00"},
            {"id": 3, "nome_produto": "Agua 10L", "quantidade": 7.0, "tipo_movimento": "entrada", "data_registro": f"{today.year - 1}-{today.month:02d}-03 11:00:00"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=rows), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "comparar este mes vs mesmo periodo do ano passado nos movimentos de estoque", "history": []})

        self.assertIn("Comparativo temporal", result["reply"])
        self.assertIn("este mes", result["reply"].lower())
        self.assertIn("mesmo periodo do ano passado", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_analytics_for_abastecimentos_summary(self):
        abastecimentos = [
            {
                "id": 15,
                "veiculo_nome": "Caminhao 5",
                "placa": "ABC-1234",
                "km": 120500,
                "posto": "Posto Central",
                "combustivel_tipo": "diesel",
                "status": "abastecido",
            },
            {
                "id": 16,
                "veiculo_nome": "Caminhao 8",
                "placa": "DEF-5678",
                "km": 95400,
                "posto": "Posto Central",
                "combustivel_tipo": "diesel",
                "status": "abastecido",
            },
            {
                "id": 17,
                "veiculo_nome": "Caminhao 9",
                "placa": "GHI-9012",
                "km": 88400,
                "posto": "Posto Sul",
                "combustivel_tipo": "gasolina",
                "status": "pendente",
            },
        ]
        with mock.patch.object(agent_web, "system_api", return_value=abastecimentos), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quero um resumo estatistico dos abastecimentos", "history": []})

        self.assertIn("Resumo estatistico de abastecimentos", result["reply"])
        self.assertIn("total de registros: 3", result["reply"])
        self.assertIn("Posto Central (2)", result["reply"])
        self.assertIn("abastecido (2)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_comparison_for_abastecimentos_posto(self):
        abastecimentos = [
            {"id": 15, "veiculo_nome": "Caminhao 5", "posto": "Posto Central", "combustivel_tipo": "diesel", "status": "abastecido"},
            {"id": 16, "veiculo_nome": "Caminhao 8", "posto": "Posto Central", "combustivel_tipo": "diesel", "status": "abastecido"},
            {"id": 17, "veiculo_nome": "Caminhao 9", "posto": "Posto Sul", "combustivel_tipo": "gasolina", "status": "pendente"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=abastecimentos), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual posto mais abasteceu?", "history": []})

        self.assertIn("posto com mais ocorrencias", result["reply"].lower())
        self.assertIn("Posto Central", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_route_worsened_business_comparison(self):
        today = datetime.date.today()
        pontos_venda = [
            {"id": 1, "vendedor": "Carlos", "cliente": "Mercado A", "rota": "Centro", "visita_periodicidade": "Semanal", "dia_semana": "Segunda", "data_base": f"{today:%Y-%m-%d}"},
            {"id": 2, "vendedor": "Carlos", "cliente": "Mercado B", "rota": "Bairro Alto", "visita_periodicidade": "Semanal", "dia_semana": "Terca", "data_base": f"{today:%Y-%m-%d}"},
            {"id": 3, "vendedor": "Carlos", "cliente": "Mercado C", "rota": "Centro", "visita_periodicidade": "Semanal", "dia_semana": "Quarta", "data_base": f"{(today - datetime.timedelta(days=35)):%Y-%m-%d}"},
            {"id": 4, "vendedor": "Ana", "cliente": "Mercado D", "rota": "Centro", "visita_periodicidade": "Semanal", "dia_semana": "Quinta", "data_base": f"{(today - datetime.timedelta(days=38)):%Y-%m-%d}"},
            {"id": 5, "vendedor": "Ana", "cliente": "Mercado E", "rota": "Centro", "visita_periodicidade": "Semanal", "dia_semana": "Sexta", "data_base": f"{(today - datetime.timedelta(days=41)):%Y-%m-%d}"},
            {"id": 6, "vendedor": "Ana", "cliente": "Mercado F", "rota": "Bairro Alto", "visita_periodicidade": "Semanal", "dia_semana": "Segunda", "data_base": f"{(today - datetime.timedelta(days=45)):%Y-%m-%d}"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=pontos_venda), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual rota piorou nos ultimos 30 dias em relacao ao periodo anterior nas visitas da rota?", "history": []})

        self.assertIn("rota que mais piorou", result["reply"].lower())
        self.assertIn("Centro", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_analytics_for_pontos_venda(self):
        pontos_venda = [
            {
                "id": 1,
                "vendedor": "Carlos",
                "cliente": "Mercado A",
                "rota": "Centro",
                "visita_periodicidade": "Semanal",
                "dia_semana": "Segunda",
            },
            {
                "id": 2,
                "vendedor": "Carlos",
                "cliente": "Mercado B",
                "rota": "Centro",
                "visita_periodicidade": "Quinzenal",
                "dia_semana": "Terca",
            },
            {
                "id": 3,
                "vendedor": "Ana",
                "cliente": "Mercado C",
                "rota": "Industrial",
                "visita_periodicidade": "Semanal",
                "dia_semana": "Segunda",
            },
        ]
        with mock.patch.object(agent_web, "system_api", return_value=pontos_venda), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "me mostre a estatistica dos pontos de venda", "history": []})

        self.assertIn("Resumo estatistico de pontos de venda", result["reply"])
        self.assertIn("total de registros: 3", result["reply"])
        self.assertIn("Centro (2)", result["reply"])
        self.assertIn("Carlos (2)", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_comparison_for_pontos_venda_route(self):
        pontos_venda = [
            {"id": 1, "vendedor": "Carlos", "cliente": "Mercado A", "rota": "Centro", "visita_periodicidade": "Semanal", "dia_semana": "Segunda"},
            {"id": 2, "vendedor": "Carlos", "cliente": "Mercado B", "rota": "Centro", "visita_periodicidade": "Quinzenal", "dia_semana": "Terca"},
            {"id": 3, "vendedor": "Ana", "cliente": "Mercado C", "rota": "Industrial", "visita_periodicidade": "Semanal", "dia_semana": "Segunda"},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=pontos_venda), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual rota teve mais visitas?", "history": []})

        self.assertIn("rota com mais ocorrencias", result["reply"].lower())
        self.assertIn("Centro", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_comissao_report_summary(self):
        payload = {
            "resumo_geral": {
                "total_lancamentos": 4,
                "base_vendedor_total": 12500.0,
                "comissao_vendedor_total": 820.0,
                "comissao_entregador_total": 610.0,
            },
            "total_vendedores": [
                {"codigo": 10, "nome": "Carlos", "base_total": 7000.0, "comissao_total": 500.0},
                {"codigo": 11, "nome": "Ana", "base_total": 5500.0, "comissao_total": 320.0},
            ],
            "total_entregadores": [
                {"nome": "Joao", "volume_total": 200.0, "comissao_total": 410.0},
                {"nome": "Maria", "volume_total": 180.0, "comissao_total": 200.0},
            ],
            "total_refugo": [
                {"entregador": "Joao", "dev_gf": 5.0, "dev_pet": 3.0},
            ],
            "total_acucar": [
                {"usina": "Usina Norte", "qtd": 12.0, "comissao": 90.0},
            ],
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quero o relatorio de comissao com resumo estatistico", "history": []})

        self.assertIn("Resumo estatistico dos relatorios de comissao", result["reply"])
        self.assertIn("total de lancamentos: 4", result["reply"])
        self.assertIn("Carlos", result["reply"])
        self.assertIn("Joao", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_comissao_report_top_refugo_entregador(self):
        payload = {
            "resumo_geral": {"total_lancamentos": 4},
            "total_vendedores": [],
            "total_entregadores": [],
            "total_refugo": [
                {"entregador": "Joao", "dev_gf": 5.0, "dev_pet": 3.0},
                {"entregador": "Maria", "dev_gf": 2.0, "dev_pet": 1.0},
            ],
            "total_acucar": [],
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual entregador teve maior refugo na comissao?", "history": []})

        self.assertIn("entregador com maior refugo", result["reply"].lower())
        self.assertIn("Joao", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_vendas_dashboard_summary(self):
        payload = {
            "meses_disponiveis": ["2025-01", "2025-02"],
            "mes_atual": "2025-02",
            "mes_anterior": "2025-01",
            "resumo_geral": {
                "vendedores": 2,
                "meses": 2,
                "valor_atual": 45000.0,
                "valor_anterior": 42000.0,
                "variacao_valor": 3000.0,
                "variacao_percentual": 7.14,
                "cresceu": 1,
                "caiu": 1,
                "estavel": 0,
            },
            "vendedores": [
                {"nome": "Carlos", "ultimo_valor_liquido": 28000.0, "total_valor_liquido": 50000.0},
                {"nome": "Ana", "ultimo_valor_liquido": 17000.0, "total_valor_liquido": 33000.0},
            ],
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar dashboard de vendas com resumo", "history": []})

        self.assertIn("Resumo estatistico do dashboard de vendas", result["reply"])
        self.assertIn("valor atual: R$ 45000.00", result["reply"])
        self.assertIn("Carlos", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_vendas_dashboard_top_growth(self):
        payload = {
            "meses_disponiveis": ["2025-01", "2025-02"],
            "mes_atual": "2025-02",
            "mes_anterior": "2025-01",
            "resumo_geral": {"vendedores": 2, "meses": 2},
            "vendedores": [
                {"nome": "Carlos", "ultimo_valor_liquido": 28000.0, "total_valor_liquido": 50000.0, "delta_ultimo_mes": 6000.0},
                {"nome": "Ana", "ultimo_valor_liquido": 17000.0, "total_valor_liquido": 33000.0, "delta_ultimo_mes": -2000.0},
            ],
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual vendedor mais cresceu nas vendas?", "history": []})

        self.assertIn("mais cresceu", result["reply"].lower())
        self.assertIn("Carlos", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_vendas_dashboard_top_value_loss(self):
        payload = {
            "meses_disponiveis": ["2025-01", "2025-02"],
            "mes_atual": "2025-02",
            "mes_anterior": "2025-01",
            "resumo_geral": {"vendedores": 2, "meses": 2},
            "vendedores": [
                {"nome": "Carlos", "ultimo_valor_liquido": 28000.0, "total_valor_liquido": 50000.0, "delta_ultimo_mes": -1500.0},
                {"nome": "Ana", "ultimo_valor_liquido": 17000.0, "total_valor_liquido": 33000.0, "delta_ultimo_mes": -4500.0},
            ],
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual vendedor mais perdeu valor nas vendas?", "history": []})

        self.assertIn("mais perdeu valor", result["reply"].lower())
        self.assertIn("Ana", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_vendas_dashboard_client_value_loss(self):
        payload = {
            "meses_disponiveis": ["2025-01", "2025-02"],
            "mes_atual": "2025-02",
            "mes_anterior": "2025-01",
            "resumo_geral": {"clientes": 2, "meses": 2},
            "vendedores": [],
            "top_clientes": [
                {"cliente": "Mercado A", "delta_ultimo_mes": -1200.0},
                {"cliente": "Mercado B", "delta_ultimo_mes": -3400.0},
            ],
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual cliente mais perdeu valor nas vendas?", "history": []})

        self.assertIn("cliente que mais perdeu valor", result["reply"].lower())
        self.assertIn("Mercado B", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_vendas_dashboard_month_comparison(self):
        payload = {
            "mes_atual": "2025-02",
            "mes_anterior": "2025-01",
            "resumo_geral": {
                "valor_atual": 45000.0,
                "valor_anterior": 42000.0,
                "variacao_valor": 3000.0,
                "variacao_percentual": 7.14,
            },
            "vendedores": [],
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "comparar este mes vs mes passado nas vendas", "history": []})

        self.assertIn("Comparativo de vendas", result["reply"])
        self.assertIn("este mes", result["reply"].lower())
        self.assertIn("mes passado", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_vendas_painel_summary(self):
        payload = {
            "dashboard_tipo": "vendas",
            "bonificacoes": {
                "totais": {"valor_venda": 50000.0, "bonificacao": 2500.0, "valor_liquido": 46000.0},
            },
            "variacao_preco": {
                "resumo_geral": {"quantidade_variacoes": 12},
            },
            "mensal": {
                "resumo_geral": {"valor_venda": 50000.0, "valor_liquido": 46000.0},
            },
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar painel consolidado de vendas", "history": []})

        self.assertIn("Resumo estatistico do painel consolidado de vendas", result["reply"])
        self.assertIn("bonificacao/financeiro", result["reply"])
        self.assertIn("variacao de preco: 12", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_vendas_report_summary(self):
        payload = {
            "relatorio_tipo": "bonificacoes",
            "totais": {
                "vendedores": 2,
                "clientes": 8,
                "notas": 14,
                "itens": 20,
                "valor_venda": 60000.0,
                "valor_devolvido": 3000.0,
                "bonificacao": 2500.0,
                "valor_liquido": 54500.0,
            },
            "vendedores": [
                {"nome": "Carlos", "valor_liquido": 32000.0},
                {"nome": "Ana", "valor_liquido": 22500.0},
            ],
            "resumo_grupos": [
                {"grupo": "refrigerante", "valor_liquido": 28000.0},
            ],
        }
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar relatorio de vendas bonificacoes", "history": []})

        self.assertIn("Resumo estatistico do relatorio de vendas", result["reply"])
        self.assertIn("Carlos", result["reply"])
        self.assertIn("refrigerante", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_sales_lookup_for_top_seller_by_product_month(self):
        rows = [
            {
                "vendedor_nome": "Carlos",
                "vendedor_key": "CARLOS",
                "produto": "Refrigerante PET 6X2 Cola",
                "grupo_norm": "001004 Pet2L",
                "quantidade": 10.0,
                "caixa_fisica": 0.0,
                "caixas": 0.0,
                "litros": 20.0,
                "valor_devolvido": 0.0,
                "quantidade_devolvida": 0.0,
                "litro_devolvido": 0.0,
                "caixa_devolvida": 0.0,
                "tipo_operacao": "VENDA",
                "condicao": "A",
                "tab_venda": 1,
            },
            {
                "vendedor_nome": "Ana",
                "vendedor_key": "ANA",
                "produto": "Refrigerante PET 6X2 Laranja",
                "grupo_norm": "001004 Pet2L",
                "quantidade": 25.0,
                "caixa_fisica": 0.0,
                "caixas": 0.0,
                "litros": 50.0,
                "valor_devolvido": 0.0,
                "quantidade_devolvida": 0.0,
                "litro_devolvido": 0.0,
                "caixa_devolvida": 0.0,
                "tipo_operacao": "VENDA",
                "condicao": "A",
                "tab_venda": 1,
            },
            {
                "vendedor_nome": "Bruno",
                "vendedor_key": "BRUNO",
                "produto": "Refrigerante PET 600ML Uva",
                "grupo_norm": "001005 Pet600Ml",
                "quantidade": 40.0,
                "caixa_fisica": 0.0,
                "caixas": 0.0,
                "litros": 24.0,
                "valor_devolvido": 0.0,
                "quantidade_devolvida": 0.0,
                "litro_devolvido": 0.0,
                "caixa_devolvida": 0.0,
                "tipo_operacao": "VENDA",
                "condicao": "A",
                "tab_venda": 1,
            },
        ]
        handlers = [
            lambda query, params: {"id": "cache-1"},
            lambda query, params: {"ano": 2025},
            lambda query, params: rows,
        ]

        with mock.patch.object(agent_web, "_agent_db_connect", return_value=_FakeConnection(handlers)), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual vendedor mais vendeu pet 2 l em janeiro?", "history": []})

        self.assertIn("PET 2L", result["reply"])
        self.assertIn("01/2025", result["reply"])
        self.assertIn("Ana", result["reply"])
        self.assertIn("25.000", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_sales_lookup_for_group_code_and_month(self):
        rows = [
            {
                "vendedor_nome": "Carlos",
                "vendedor_key": "CARLOS",
                "produto": "007000-GUARANA RIO BRANCO PET 6X2",
                "grupo_norm": "001004 Pet2L",
                "quantidade": 100.0,
                "caixa_fisica": 100.0,
                "caixas": 0.0,
                "litros": 1200.0,
                "valor_devolvido": 0.0,
                "quantidade_devolvida": 0.0,
                "litro_devolvido": 0.0,
                "caixa_devolvida": 0.0,
                "tipo_operacao": "VEN",
                "condicao": "A",
                "tab_venda": 1,
            },
            {
                "vendedor_nome": "Ana",
                "vendedor_key": "ANA",
                "produto": "007400-TUBARIO RIO BRANCO PET 6X2",
                "grupo_norm": "001004 Pet2L",
                "quantidade": 150.0,
                "caixa_fisica": 150.0,
                "caixas": 0.0,
                "litros": 1800.0,
                "valor_devolvido": 0.0,
                "quantidade_devolvida": 0.0,
                "litro_devolvido": 0.0,
                "caixa_devolvida": 0.0,
                "tipo_operacao": "VEN",
                "condicao": "P",
                "tab_venda": 2,
            },
        ]
        handlers = [
            lambda query, params: {"id": "cache-1"},
            lambda query, params: {"ano": 2026},
            lambda query, params: rows,
        ]

        with mock.patch.object(agent_web, "_agent_db_connect", return_value=_FakeConnection(handlers)), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual vendedor mais vendeu o grupo 001004 Pet2L no mes de janeiro", "history": []})

        self.assertIn("Ana", result["reply"])
        self.assertIn("01/2026", result["reply"])
        self.assertIn("150.000", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_sales_lookup_reports_no_sales_for_month(self):
        handlers = [
            lambda query, params: {"id": "cache-1"},
            lambda query, params: {"ano": 2025},
            lambda query, params: [],
        ]

        with mock.patch.object(agent_web, "_agent_db_connect", return_value=_FakeConnection(handlers)), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual vendedor mais vendeu pet 2 l em janeiro?", "history": []})

        self.assertIn("Nao encontrei vendas de PET 2L em 01/2025", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_frota_resumo_summary(self):
        payload = [
            {
                "id": 1,
                "nome": "Caminhao 5",
                "placa": "AAA-1111",
                "km_atual": 120500,
                "custo_total": 18000.0,
                "falta_manut_km": -100,
                "falta_oleo_km": 500,
            },
            {
                "id": 2,
                "nome": "Caminhao 8",
                "placa": "BBB-2222",
                "km_atual": 98000,
                "custo_total": 9000.0,
                "falta_manut_km": 1200,
                "falta_oleo_km": -50,
            },
        ]
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quero um resumo da frota", "history": []})

        self.assertIn("Resumo estatistico da frota", result["reply"])
        self.assertIn("total de veiculos: 2", result["reply"])
        self.assertIn("manutencao no limite ou vencida: 1", result["reply"])
        self.assertIn("Caminhao 5", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_frota_resumo_for_most_overdue_maintenance(self):
        payload = [
            {"id": 1, "nome": "Caminhao 5", "placa": "AAA-1111", "km_atual": 120500, "custo_total": 18000.0, "falta_manut_km": -100, "falta_oleo_km": 500},
            {"id": 2, "nome": "Caminhao 8", "placa": "BBB-2222", "km_atual": 98000, "custo_total": 9000.0, "falta_manut_km": -350, "falta_oleo_km": -50},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual veiculo esta mais atrasado na manutencao?", "history": []})

        self.assertIn("manutencao mais critica", result["reply"].lower())
        self.assertIn("Caminhao 8", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_frota_resumo_for_worst_cost_per_km(self):
        payload = [
            {"id": 1, "nome": "Caminhao 5", "placa": "AAA-1111", "km_atual": 120000, "custo_total": 18000.0, "falta_manut_km": -100, "falta_oleo_km": 500},
            {"id": 2, "nome": "Caminhao 8", "placa": "BBB-2222", "km_atual": 60000, "custo_total": 15000.0, "falta_manut_km": 50, "falta_oleo_km": -50},
        ]
        with mock.patch.object(agent_web, "system_api", return_value=payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual veiculo piorou mais em custo por km na frota?", "history": []})

        self.assertIn("pior custo por km", result["reply"].lower())
        self.assertIn("Caminhao 8", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_status_api_for_system_health(self):
        status_payload = {
            "api": True,
            "database": True,
            "esxi": {"host": "192.168.200.198", "online": True},
            "cameras": [{"online": True}, {"online": False}],
            "usuario_logado": {"nome": "Renan", "login": "renan"},
        }
        with mock.patch.object(agent_web, "system_api", return_value=status_payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual o status do sistema agora?", "history": []})

        self.assertIn("Status geral do sistema", result["reply"])
        self.assertIn("API: ok", result["reply"])
        self.assertIn("Banco: ok", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_status_api_with_monitor_summary(self):
        status_payload = {
            "api": True,
            "database": True,
            "esxi": {"host": "192.168.200.198", "online": True},
            "monitor_apps": {
                "cameras": {"running": True, "port": 8889},
                "esxi": {"running": False, "port": 5500},
            },
            "cameras": [{"online": True}, {"online": False}, {"online": True}],
            "sip": {"habilitado": True},
            "nfe": {"habilitado": False},
            "usuario_logado": {"nome": "Renan", "login": "renan"},
        }
        with mock.patch.object(agent_web, "system_api", return_value=status_payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "me de um resumo do status do sistema", "history": []})

        self.assertIn("Apps de monitor: 1/2 ativas", result["reply"])
        self.assertIn("Cameras: 2/3 online", result["reply"])
        self.assertIn("SIP: habilitado", result["reply"])
        self.assertIn("NF-e: desabilitado", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_local_backup_context_for_latest_backup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            backup_path = Path(tmp_dir) / "backup_20250110_101500.sql"
            backup_path.write_text("ok", encoding="utf-8")
            with mock.patch.object(agent_web, "_agent_backup_dir", return_value=Path(tmp_dir)), \
                mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
                mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
                result = agent_web.handle_chat({"message": "qual foi o ultimo backup salvo?", "history": []})

        self.assertIn("backup_20250110_101500.sql", result["reply"])
        self.assertIn("Diretorio configurado", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_devolucao_lookup_does_not_fall_into_storage_reply(self):
        devolucoes = [
            {
                "id": 22,
                "frete_id": 138,
                "veiculo_id": 14,
                "veiculo_nome": "Caminhao 14",
                "frete_nome": "Jaguapita",
                "conferente_nome": "Maria",
                "c48": 3,
                "fotos": [],
                "tem_fotos": False,
            }
        ]
        with mock.patch.object(agent_web, "system_api", return_value=devolucoes), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "tem devolucao para o caminhao 14?", "history": []})

        self.assertNotIn("FotosDevolucoes", result["reply"])
        self.assertIn("#22", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_logged_user_endpoint(self):
        me_payload = {
            "ok": True,
            "usuario": {"id": 7, "nome": "Renan", "login": "renan"},
        }
        with mock.patch.object(agent_web, "system_api", return_value=me_payload), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quem esta logado agora?", "history": []})

        self.assertIn("Usuario logado atual", result["reply"])
        self.assertIn("Renan", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_routes_dashboard_frota_before_maintenance_summary(self):
        dashboard_rows = [
            {
                "veiculo_id": 9,
                "veiculo_nome": "Caminhao 55",
                "placa": "AAA-1234",
                "frete_status": "carregado",
                "falta_manut_km": -120,
                "falta_oleo_km": 800,
                "alerta": True,
            }
        ]

        def fake_system_api(method, path, payload=None, timeout=20):
            self.assertEqual(path, "/api/dashboard_frota")
            return dashboard_rows

        with mock.patch.object(agent_web, "system_api", side_effect=fake_system_api), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar dashboard da frota", "history": []})

        self.assertIn("dashboard da frota", result["reply"].lower())
        self.assertIn("Caminhao 55", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_frota_historico_for_specific_vehicle(self):
        def fake_system_api(method, path, payload=None, timeout=20):
            if path == "/api/dashboard_frota":
                return [{"veiculo_id": 9, "veiculo_nome": "Caminhao 55", "placa": "AAA-1234", "modelo": "Volvo"}]
            if path == "/api/frota_historico/9":
                return {
                    "veiculo": {"id": 9, "nome": "Caminhao 55", "placa": "AAA-1234"},
                    "frete_atual": {"status": "carregado", "carga_nome": "Campina da Lagoa"},
                    "resumo": {"km_atual": 155000, "falta_manut_km": 300, "falta_oleo_km": -50, "manut_count": 4, "abastecimentos_count": 12},
                    "historico": {
                        "manutencoes": [{"tipo": "freio", "km": 150000}],
                        "trocas_oleo": [{"tipo": "15w40", "km": 149000}],
                    },
                }
            raise AssertionError(f"rota inesperada: {path}")

        with mock.patch.object(agent_web, "system_api", side_effect=fake_system_api), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar historico do caminhao 55", "history": []})

        self.assertIn("Historico da frota", result["reply"])
        self.assertIn("Caminhao 55", result["reply"])
        self.assertIn("Campina da Lagoa", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_chat_conversa_for_specific_contact(self):
        conversa_rows = [
            {
                "id": 1,
                "remetente_nome": "Joao",
                "destinatario_nome": "Renan",
                "mensagem": "Carga saiu agora",
                "data_envio": "2025-01-10 08:00:00",
            },
            {
                "id": 2,
                "remetente_nome": "Renan",
                "destinatario_nome": "Joao",
                "mensagem": "Ok",
                "data_envio": "2025-01-10 08:01:00",
            },
        ]

        def fake_system_api(method, path, payload=None, timeout=20):
            self.assertEqual(path, "/api/chat/conversa?usuario_id=1&contato_id=9&limit=50")
            return conversa_rows

        with mock.patch.object(agent_web, "system_api", side_effect=fake_system_api), \
            mock.patch.object(agent_web, "get_logged_usuario", return_value={"id": 1, "nome": "Renan", "login": "renan"}), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "mostrar conversa com usuario 9", "history": []})

        self.assertIn("conversa", result["reply"].lower())
        self.assertIn("Carga saiu agora", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_chat_conversa_temporal_comparison(self):
        now = datetime.datetime.now()
        conversa_rows = [
            {
                "id": 1,
                "remetente_nome": "Joao",
                "destinatario_nome": "Renan",
                "mensagem": "Carga saiu agora",
                "data_envio": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
            {
                "id": 2,
                "remetente_nome": "Renan",
                "destinatario_nome": "Joao",
                "mensagem": "Ok",
                "data_envio": (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            },
        ]

        def fake_system_api(method, path, payload=None, timeout=20):
            self.assertEqual(path, "/api/chat/conversa?usuario_id=1&contato_id=9&limit=50")
            return conversa_rows

        with mock.patch.object(agent_web, "system_api", side_effect=fake_system_api), \
            mock.patch.object(agent_web, "get_logged_usuario", return_value={"id": 1, "nome": "Renan", "login": "renan"}), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "hoje vs ontem na conversa com usuario 9", "history": []})

        self.assertIn("Comparativo temporal da conversa", result["reply"])
        self.assertIn("hoje", result["reply"].lower())
        self.assertIn("ontem", result["reply"].lower())
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_devolucao_client_top_in_period(self):
        now = datetime.datetime.now()
        devolucoes = [
            {
                "id": 21,
                "frete_id": 137,
                "cliente": "Mercado A",
                "frete_nome": "Rota A",
                "conferente_nome": "Joao",
                "c24": 4,
                "pet2l": 2,
                "data_registro": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
            {
                "id": 22,
                "frete_id": 138,
                "cliente": "Mercado B",
                "frete_nome": "Rota B",
                "conferente_nome": "Maria",
                "c24": 1,
                "pet2l": 0,
                "data_registro": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
            {
                "id": 23,
                "frete_id": 139,
                "cliente": "Mercado A",
                "frete_nome": "Rota C",
                "conferente_nome": "Joao",
                "c24": 3,
                "pet2l": 1,
                "data_registro": (now - datetime.timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S"),
            },
        ]
        with mock.patch.object(agent_web, "system_api", return_value=devolucoes), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "qual cliente teve mais devolucao nos ultimos 30 dias?", "history": []})

        self.assertIn("cliente com mais devolucao", result["reply"].lower())
        self.assertIn("Mercado A", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_uses_chat_unread_summary(self):
        unread_payload = {
            "total": 6,
            "total_mensagens_nao_lidas": 6,
            "total_conversas_com_nao_lidas": 2,
            "por_contato": [
                {"remetente_id": 9, "remetente_nome": "Joao", "total": 4},
                {"remetente_id": 11, "remetente_nome": "Maria", "total": 2},
            ],
        }

        with mock.patch.object(agent_web, "system_api", return_value=unread_payload), \
            mock.patch.object(agent_web, "get_logged_usuario", return_value={"id": 1, "nome": "Renan", "login": "renan"}), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quantas mensagens nao lidas eu tenho no chat?", "history": []})

        self.assertIn("Resumo de mensagens nao lidas do chat", result["reply"])
        self.assertIn("total de mensagens nao lidas: 6", result["reply"])
        self.assertIn("Joao", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_detect_doc_technologies_includes_project_dependencies(self):
        techs = agent_web._agent_detect_doc_technologies("consultar documentacao do reportlab e onnxruntime")
        labels = {item["label"] for item in techs}

        self.assertIn("ReportLab", labels)
        self.assertIn("ONNX Runtime", labels)

    def test_legacy_chat_checks_local_context_before_generic_menu(self):
        fake_cursor = mock.Mock()
        fake_cursor.fetchone.return_value = {"total": 3}
        fake_conn = mock.Mock()
        fake_conn.cursor.return_value = fake_cursor

        with mock.patch.object(agent_web.mysql.connector, "connect", return_value=fake_conn):
            result = agent_web._handle_chat_legacy({"message": "quantos caminhões tenho cadastrado?"})

        self.assertIn("3", result["reply"])
        self.assertNotIn("Ainda nao entendi qual rotina", result["reply"])

    def test_handle_chat_ia_mode_does_not_fall_back_to_legacy_menu(self):
        with mock.patch.object(agent_web, "_agent_local_context_reply", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=False):
            result = agent_web.handle_chat({"message": "pergunta aberta sem match", "history": [], "chat_mode": "ia"})

        self.assertNotIn("Ainda nao entendi qual rotina", result["reply"])
        self.assertIn("Nao encontrei", result["reply"])

    def test_handle_chat_ia_mode_can_use_web_lookup(self):
        with mock.patch.object(agent_web, "_agent_local_context_reply", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=False), \
            mock.patch.object(agent_web, "_agent_web_lookup_reply", return_value={"reply": "Na web encontrei a documentacao.\n\nFontes web: https://exemplo.local/docs"}):
            result = agent_web.handle_chat({"message": "consulte na internet a documentacao do flask", "history": [], "chat_mode": "ia"})

        self.assertIn("documentacao", result["reply"].lower())
        self.assertIn("Fontes web:", result["reply"])

    def test_handle_chat_ia_mode_prioritizes_web_docs_over_llm_action(self):
        with mock.patch.object(agent_web, "_agent_local_context_reply", return_value=None), \
            mock.patch.object(agent_web, "_agent_web_lookup_reply", return_value={"reply": "Na web encontrei a documentacao do Flask.\n\nFontes web: https://flask.palletsprojects.com/"}), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value='{"type":"action","action":"deploy"}'), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({
                "message": "consultar na internet, documentacao do flask, como subir um servidor web",
                "history": [],
                "chat_mode": "ia",
            })

        self.assertIn("Flask", result["reply"])
        self.assertIn("Fontes web:", result["reply"])

    def test_handle_chat_agent_mode_also_prioritizes_web_docs_over_action(self):
        with mock.patch.object(agent_web, "_agent_local_context_reply", return_value=None), \
            mock.patch.object(agent_web, "_agent_web_lookup_reply", return_value={"reply": "Na web encontrei a documentacao do Flask.\n\nFontes web: https://flask.palletsprojects.com/"}), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value='{"type":"action","action":"deploy"}'), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({
                "message": "consultar na internet, documentacao do flask, como subir um servidor web",
                "history": [],
                "chat_mode": "agent",
            })

        self.assertIn("Flask", result["reply"])
        self.assertIn("Fontes web:", result["reply"])

    def test_handle_chat_web_intent_without_result_does_not_fall_to_action(self):
        with mock.patch.object(agent_web, "_agent_local_context_reply", return_value=None), \
            mock.patch.object(agent_web, "_agent_web_lookup_reply", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_request", return_value='{"type":"action","action":"deploy"}'), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({
                "message": "consultar na internet, documentacao do flask, como subir um servidor web",
                "history": [],
                "chat_mode": "agent",
            })

        self.assertIn("Nao consegui consultar a documentacao web", result["reply"])
        self.assertNotIn("Deploy local", result["reply"])

    def test_web_lookup_prioritizes_firebird_official_docs(self):
        result = agent_web._agent_web_lookup_reply("consulte na internet a documentacao do firebird", "ia")

        self.assertIn("Firebird", result["reply"])
        self.assertIn("firebirdsql.org", result["reply"])
        self.assertIn("Fontes web:", result["reply"])

    def test_web_lookup_prioritizes_windows_official_docs(self):
        result = agent_web._agent_web_lookup_reply("pesquise na internet a documentacao do windows server", "ia")

        self.assertIn("Windows", result["reply"])
        self.assertIn("learn.microsoft.com", result["reply"])
        self.assertIn("Fontes web:", result["reply"])

    def test_web_lookup_reads_docs_content_for_procedural_question(self):
        fake_html = """
        <html>
          <head>
            <title>Development Server - Flask Documentation (3.1.x)</title>
            <meta name="description" content="Use the flask command to run the development server from the terminal.">
          </head>
          <body>
            <h1>Development Server</h1>
            <p>Use the flask --app hello run command to start the development server.</p>
            <p>Do not use the development server in production. Use a production WSGI server instead.</p>
          </body>
        </html>
        """
        with mock.patch.object(agent_web, "_duckduckgo_search", return_value=[
            {
                "title": "Development Server - Flask Documentation (3.1.x)",
                "url": "https://flask.palletsprojects.com/en/3.1.x/server/",
                "snippet": "Use the flask command to run the development server.",
            }
        ]), mock.patch.object(agent_web, "_http_get_text", return_value=fake_html):
            result = agent_web._agent_web_lookup_reply(
                "consultar na internet, documentacao do flask, como subir um servidor web",
                "ia",
            )

        self.assertIn("Comando:", result["reply"])
        self.assertIn("`flask --app hello run`", result["reply"])
        self.assertIn("Observacao:", result["reply"])
        self.assertIn("production", result["reply"])
        self.assertIn("https://flask.palletsprojects.com/cli/#run-the-development-server", result["reply"])

    def test_web_lookup_uses_internal_docs_links_when_search_is_blocked(self):
        root_html = """
        <html>
          <body>
            <a href="quickstart/">Quickstart</a>
            <a href="server/">Development Server</a>
            <a href="cli/#run-the-development-server">Run the Development Server</a>
          </body>
        </html>
        """
        page_html = """
        <html>
          <head>
            <title>Development Server - Flask Documentation (3.1.x)</title>
            <meta name="description" content="Use the flask command to run the development server from the terminal.">
          </head>
          <body>
            <h1>Development Server</h1>
            <p>Use the flask --app hello run command to start the development server.</p>
            <p>Do not use the development server in production. Use a production WSGI server instead.</p>
          </body>
        </html>
        """
        def fake_get(url):
            if url == "https://flask.palletsprojects.com/":
                return root_html
            if url == "https://flask.palletsprojects.com/quickstart/":
                return "<html><body><h1>Quickstart</h1></body></html>"
            if url == "https://flask.palletsprojects.com/server/":
                return "<html><body><h1>Development Server</h1></body></html>"
            if url == "https://flask.palletsprojects.com/cli/#run-the-development-server":
                return page_html
            raise AssertionError(f"URL inesperada: {url}")

        with mock.patch.object(agent_web, "_duckduckgo_search", return_value=[]), \
            mock.patch.object(agent_web, "_http_get_text", side_effect=fake_get):
            result = agent_web._agent_web_lookup_reply(
                "consultar na internet, documentacao do flask, como subir um servidor web",
                "ia",
            )

        self.assertIn("Comando:", result["reply"])
        self.assertIn("`flask --app hello run`", result["reply"])
        self.assertIn("https://flask.palletsprojects.com/cli/#run-the-development-server", result["reply"])

    def test_web_lookup_follows_internal_python_docs_for_http_server_command(self):
        python_root_html = """
        <html>
          <body>
            <a href="library/index.html">Library reference</a>
            <a href="tutorial/">Tutorial</a>
          </body>
        </html>
        """
        python_library_html = """
        <html>
          <body>
            <a href="http.server.html">http.server</a>
            <a href="socketserver.html">socketserver</a>
          </body>
        </html>
        """
        http_server_html = """
        <html>
          <head>
            <title>http.server — HTTP servers</title>
            <meta name="description" content="This module defines classes for implementing HTTP servers.">
          </head>
          <body>
            <h1>http.server</h1>
            <p>python -m http.server</p>
            <p>This command runs a basic HTTP server on port 8000 by default.</p>
            <p>Use python -m http.server 9000 to choose another port.</p>
          </body>
        </html>
        """
        def fake_get(url):
            if url == "https://docs.python.org/3/":
                return python_root_html
            if url == "https://docs.python.org/3/library/index.html":
                return python_library_html
            if url == "https://docs.python.org/3/library/http.server.html":
                return http_server_html
            raise AssertionError(f"URL inesperada: {url}")

        with mock.patch.object(agent_web, "_duckduckgo_search", return_value=[]), \
            mock.patch.object(agent_web, "_http_get_text", side_effect=fake_get):
            result = agent_web._agent_web_lookup_reply(
                "documentacao, comando em python para subir um servidor http",
                "ia",
            )

        self.assertIn("Comando:", result["reply"])
        self.assertIn("`python -m http.server`", result["reply"])
        self.assertIn("Exemplo:", result["reply"])
        self.assertIn("`python -m http.server 9000`", result["reply"])
        self.assertIn("Observacao:", result["reply"])
        self.assertIn("https://docs.python.org/3/library/http.server.html", result["reply"])

    def test_web_lookup_prefers_internal_docs_over_generic_search_result(self):
        internal_page = {
            "label": "Python",
            "title": "http.server — HTTP servers",
            "description": "This module defines classes for implementing HTTP servers.",
            "highlights": [
                "python -m http.server",
                "Use python -m http.server 9000 to choose another port.",
            ],
            "url": "https://docs.python.org/3/library/http.server.html",
        }
        with mock.patch.object(agent_web, "_try_known_doc_candidates", return_value=None), \
            mock.patch.object(agent_web, "_find_internal_docs_summary", return_value=internal_page), \
            mock.patch.object(agent_web, "_duckduckgo_search", return_value=[
                {
                    "title": "Python 3.16.0a0 Documentation",
                    "url": "https://docs.python.org/3.16/",
                    "snippet": "The official Python documentation.",
                }
            ]):
            result = agent_web._agent_web_lookup_reply(
                "documentacao, comando em python para subir um servidor http",
                "ia",
            )

        self.assertIn("`python -m http.server`", result["reply"])
        self.assertIn("https://docs.python.org/3/library/http.server.html", result["reply"])

    def test_web_lookup_uses_known_python_http_server_candidate(self):
        page = {
            "title": "http.server — HTTP servers",
            "description": "This module defines classes for implementing HTTP servers.",
            "highlights": [
                "python -m http.server",
                "Use python -m http.server 9000 to choose another port.",
            ],
            "url": "https://docs.python.org/3/library/http.server.html",
        }
        with mock.patch.object(agent_web, "_fetch_web_page_summary", return_value=page):
            result = agent_web._agent_web_lookup_reply(
                "encontrar na documentacao ou na internet, o comando para python do modulo que sobe um servidor web",
                "ia",
            )

        self.assertIn("`python -m http.server`", result["reply"])
        self.assertIn("https://docs.python.org/3/library/http.server.html", result["reply"])

    def test_handle_chat_uses_overview_for_broad_system_questions(self):
        with mock.patch.object(agent_web, "_agent_llm_request", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True):
            result = agent_web.handle_chat({"message": "quero entender tudo sobre o sistema", "history": []})

        self.assertIn("Visao geral do sistema", result["reply"])
        self.assertIn("Fretes e kanban", result["reply"])
        self.assertIn("NF-e", result["reply"])
        self.assertTrue(any(action["name"] == "module_nfe" for action in result.get("actions", [])))

    def test_handle_chat_uses_direct_module_action(self):
        result = agent_web.handle_chat({"action": "module_nfe"})
        self.assertIn("Estoque e NF-e", result["reply"])
        self.assertIn("Fontes:", result["reply"])

    def test_handle_chat_injects_repo_context_into_llm_prompt(self):
        captured = {}

        def fake_request(messages):
            captured["messages"] = messages
            return '{"type":"reply","reply":"OK"}'

        with mock.patch.object(agent_web, "_agent_local_context_reply", return_value=None), \
            mock.patch.object(agent_web, "_agent_llm_request", side_effect=fake_request), \
            mock.patch.object(agent_web, "_agent_llm_enabled", return_value=True), \
            mock.patch.object(agent_web, "build_repo_context", return_value={"files": [{"path": ".env", "snippets": [{"line": 13, "text": "RB_PUBLIC_BASE_URL=https://192.168.200.14:8443"}]}]}), \
            mock.patch.object(agent_web, "format_repo_context", return_value="Contexto local encontrado no repositorio:\n- .env\n  - L13: RB_PUBLIC_BASE_URL=https://192.168.200.14:8443"), \
            mock.patch.object(agent_web, "format_repo_sources", return_value="Fontes: .env"):
            result = agent_web.handle_chat({"message": "onde fica a url publica?", "history": []})

        self.assertEqual(result["reply"], "OK\n\nFontes: .env")
        system_messages = [msg["content"] for msg in captured.get("messages", []) if msg.get("role") == "system"]
        self.assertTrue(any("Contexto local encontrado no repositorio" in msg for msg in system_messages))

    def test_normalize_agent_action_handles_refresh_alias(self):
        action = agent_web._normalize_agent_action({"name": "refresh_fretes"})
        self.assertIsNotNone(action)
        self.assertEqual(action["name"], "refresh_fretes")
        self.assertEqual(action["label"], "Listar cargas")


if __name__ == "__main__":
    unittest.main()
