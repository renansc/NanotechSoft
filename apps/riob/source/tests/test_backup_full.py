import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

import server


class FullBackupTests(unittest.TestCase):
    def test_full_backup_sources_use_external_data_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = os.path.join(tmp, "app_data")
            cameras_root = os.path.join(tmp, "cameras_data")
            relatorios = os.path.join(tmp, "Relatorios")
            os.makedirs(data_root)
            os.makedirs(cameras_root)
            os.makedirs(relatorios)

            with mock.patch.object(server, "DATA_ROOT", data_root), \
                mock.patch.object(server, "CAMERAS_DATA_DIR", cameras_root), \
                mock.patch.object(server, "VENDAS_RELATORIOS_DIR", relatorios):
                sources = dict(server._full_backup_sources())

        self.assertEqual(sources["app_data"], data_root)
        self.assertEqual(sources["cameras_data"], cameras_root)
        self.assertEqual(sources["relatorios"], relatorios)

    def test_full_backup_endpoint_builds_recoverable_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = os.path.join(tmp, "backups")
            app_data = os.path.join(tmp, "app_data")
            cameras_data = os.path.join(tmp, "cameras_data")
            relatorios = os.path.join(tmp, "Relatorios")
            os.makedirs(backup_dir)
            os.makedirs(app_data)
            os.makedirs(cameras_data)
            os.makedirs(relatorios)

            with open(os.path.join(app_data, "vendas-config.json"), "w", encoding="utf-8") as f:
                f.write('{"habilitado": true}')
            with open(os.path.join(cameras_data, "cams.json"), "w", encoding="utf-8") as f:
                f.write('{"cams": []}')
            with open(os.path.join(relatorios, "config-rel-vendas"), "w", encoding="utf-8") as f:
                f.write("regras")

            def fake_dump(output_path):
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write("-- MariaDB dump\nCREATE TABLE `x` (`id` int);\n")
                return subprocess.CompletedProcess(["mariadb-dump"], 0, "", "")

            previous_testing = server.app.testing
            server.app.testing = True
            try:
                with mock.patch.object(server, "DB_BACKUP_DIR", backup_dir), \
                    mock.patch.object(server, "_dump_database_sql", side_effect=fake_dump), \
                    mock.patch.object(
                        server,
                        "_full_backup_sources",
                        return_value=[
                            ("app_data", app_data),
                            ("cameras_data", cameras_data),
                            ("relatorios", relatorios),
                        ],
                    ):
                    response = server.app.test_client().get("/api/backup/full")
            finally:
                server.app.testing = previous_testing

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("X-Backup-Type"), "full")

            with tarfile.open(fileobj=io.BytesIO(response.data), mode="r:gz") as archive:
                names = set(archive.getnames())
                self.assertIn("manifest.json", names)
                self.assertIn("db/backup.sql", names)
                self.assertIn("app_data/vendas-config.json", names)
                self.assertIn("cameras_data/cams.json", names)
                self.assertIn("relatorios/config-rel-vendas", names)

                manifest_file = archive.extractfile("manifest.json")
                self.assertIsNotNone(manifest_file)
                with manifest_file:
                    manifest = json.load(manifest_file)
                self.assertEqual(manifest["formato"], "riobranco-full-backup-v1")
                self.assertIn("db/backup.sql", manifest["inclui"])
            response.close()


class SalesImportTests(unittest.TestCase):
    def test_sales_import_keeps_vendor_columns_even_if_marked_ignored(self):
        regras = server._vendas_import_regras_padrao()
        fieldnames = [
            "Data",
            "Vendedor Pedido",
            "Vendedor Cadastro",
            "Supervisor Pedido",
            "Supervisor Cadastro",
            "Cliente",
            "Produto",
        ]

        efetivas = server._vendas_import_colunas_efetivas(fieldnames, regras)

        self.assertIn("Vendedor Pedido", efetivas)
        self.assertIn("Vendedor Cadastro", efetivas)
        self.assertIn("Supervisor Pedido", efetivas)
        self.assertIn("Supervisor Cadastro", efetivas)

    def test_sales_import_uses_vendor_fallback_columns_when_order_vendor_is_blank(self):
        row = server._vendas_normalizar_linha({
            "Data": "01/01/2025",
            "Vendedor Pedido": "",
            "Vendedor Cadastro": "123 - Carlos",
            "Supervisor Pedido": "",
            "Supervisor Cadastro": "",
            "Número nf": "1001",
            "Cliente": "Mercado A",
            "Cidade": "Rio Branco",
            "Produto": "Refrigerante PET 2L",
            "Tipo Operação": "VENDA",
            "Condição": "A",
            "Quantidade": "10",
            "Litro": "20",
            "Caixa Física": "10",
            "Valor Venda": "100,00",
        })

        self.assertEqual(row["vendedor_codigo"], "123")
        self.assertEqual(row["vendedor_nome"], "Carlos")
        self.assertEqual(row["vendedor_key"], "123 - Carlos")

    def test_sales_import_falls_back_to_supervisor_when_vendor_columns_are_blank(self):
        row = server._vendas_normalizar_linha({
            "Data": "01/01/2025",
            "Vendedor Pedido": "",
            "Vendedor Cadastro": "",
            "Supervisor Pedido": "456 - Maria",
            "Supervisor Cadastro": "",
            "Número nf": "1002",
            "Cliente": "Mercado B",
            "Cidade": "Rio Branco",
            "Produto": "Refrigerante PET 600ML",
            "Tipo Operação": "VENDA",
            "Condição": "A",
            "Quantidade": "5",
            "Litro": "3",
            "Caixa Física": "5",
            "Valor Venda": "50,00",
        })

        self.assertEqual(row["vendedor_codigo"], "456")
        self.assertEqual(row["vendedor_nome"], "Maria")
        self.assertEqual(row["vendedor_key"], "456 - Maria")


if __name__ == "__main__":
    unittest.main()
