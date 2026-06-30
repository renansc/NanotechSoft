import io
import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import legacy_services


class LegacyEmailPop3Tests(unittest.TestCase):
    def test_homologacao_never_deletes_from_pop3(self):
        with patch.dict(
            os.environ,
            {
                "RB_ENV": "homologacao",
                "APP_ENV": "homologacao",
                "RB_EMAIL_DELETE_FROM_SERVER": "1",
            },
            clear=False,
        ):
            self.assertFalse(legacy_services._delete_from_server_enabled())

    def test_producao_deletes_by_default_and_allows_emergency_disable(self):
        with patch.dict(
            os.environ,
            {
                "RB_ENV": "producao",
                "APP_ENV": "producao",
                "RB_EMAIL_DELETE_FROM_SERVER": "1",
            },
            clear=False,
        ):
            self.assertTrue(legacy_services._delete_from_server_enabled())

        with patch.dict(
            os.environ,
            {
                "RB_ENV": "producao",
                "APP_ENV": "producao",
                "RB_EMAIL_DELETE_FROM_SERVER": "0",
            },
            clear=False,
        ):
            self.assertFalse(legacy_services._delete_from_server_enabled())

    def test_account_uid_keeps_legacy_pop3_and_prefixes_second_account(self):
        self.assertEqual(
            "UID-1",
            legacy_services._email_uid_key(
                {"id": 1, "protocol": "pop3"},
                "UID-1",
            ),
        )
        self.assertEqual(
            "acct:2:imap:123",
            legacy_services._email_uid_key(
                {"id": 2, "protocol": "imap"},
                "123",
            ),
        )
        self.assertEqual(
            "acct:2:imap:Itens Enviados:123",
            legacy_services._email_uid_key(
                {"id": 2, "protocol": "imap", "mailbox": "INBOX"},
                "123",
                mailbox="Itens Enviados",
            ),
        )

    def test_account_filter_matches_materia_prima_terms(self):
        message = EmailMessage()
        message["From"] = "Fornecedor <nfe@example.com>"
        message["Subject"] = "Cotacao de materia prima"
        message.set_content("Segue XML para compra de insumos.")

        matches, terms = legacy_services._email_message_matches_account_filter(
            message,
            {"filter_keywords": "materia prima;compra;pedido"},
        )

        self.assertTrue(matches)
        self.assertIn("materia prima", terms)

        unrelated = EmailMessage()
        unrelated["From"] = "RH <rh@example.com>"
        unrelated["Subject"] = "Comunicado interno"
        unrelated.set_content("Aviso geral.")

        matches, _ = legacy_services._email_message_matches_account_filter(
            unrelated,
            {"filter_keywords": "materia prima;compra;pedido"},
        )

        self.assertFalse(matches)

        unrelated.add_attachment(
            b"<nfe/>",
            maintype="application",
            subtype="xml",
            filename="nota.xml",
        )
        matches, terms = legacy_services._email_message_matches_account_filter(
            unrelated,
            {"filter_keywords": "materia prima;compra;pedido"},
            force_xml_attachments=True,
        )

        self.assertTrue(matches)
        self.assertEqual("anexo xml/zip", terms)

    def test_decode_text_falls_back_for_unknown_8bit_headers(self):
        self.assertEqual(
            "Matéria prima",
            legacy_services._decode_text("=?unknown-8bit?q?Mat=E9ria_prima?="),
        )

    def test_imap_mailbox_arg_quotes_names_with_spaces(self):
        self.assertEqual("INBOX", legacy_services._imap_mailbox_arg("INBOX"))
        self.assertEqual(
            '"Itens Enviados"',
            legacy_services._imap_mailbox_arg("Itens Enviados"),
        )

    def test_local_copy_requires_every_attachment_file(self):
        message = EmailMessage()
        message["From"] = "Posto <posto@example.com>"
        message["Subject"] = "NF-e"
        message.set_content("Conteudo completo")
        message.add_attachment(
            b"<nfe>teste</nfe>",
            maintype="application",
            subtype="xml",
            filename="nota.xml",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            attachment_path = Path(tmp_dir) / "nota.xml"
            attachment_path.write_bytes(b"<nfe>teste</nfe>")
            stored = [
                {
                    "id": 1,
                    "filename": "nota.xml",
                    "path_relativo": "nota.xml",
                    "size_bytes": attachment_path.stat().st_size,
                }
            ]
            with (
                patch.object(
                    legacy_services,
                    "_row",
                    return_value={
                        "id": 10,
                        "raw_headers": "From: posto@example.com",
                        "body_loaded_at": "2026-06-12T10:00:00",
                    },
                ),
                patch.object(legacy_services, "_rows", return_value=stored),
                patch.object(
                    legacy_services,
                    "_attachment_path",
                    return_value=attachment_path,
                ),
            ):
                complete, reason = legacy_services._email_local_copy_complete(
                    10,
                    message,
                )
                self.assertTrue(complete, reason)

            attachment_path.unlink()
            with (
                patch.object(
                    legacy_services,
                    "_row",
                    return_value={
                        "id": 10,
                        "raw_headers": "From: posto@example.com",
                        "body_loaded_at": "2026-06-12T10:00:00",
                    },
                ),
                patch.object(legacy_services, "_rows", return_value=stored),
                patch.object(
                    legacy_services,
                    "_attachment_path",
                    return_value=attachment_path,
                ),
            ):
                complete, reason = legacy_services._email_local_copy_complete(
                    10,
                    message,
                )
                self.assertFalse(complete)
                self.assertIn("nota.xml", reason)

    def test_import_only_sends_dele_in_production_after_local_validation(self):
        class FakePop3:
            def __init__(self):
                self.deleted = []
                self.quit_called = False

            def stat(self):
                return 1, 100

            def uidl(self, index):
                return b"+OK", [f"{index} UID-1".encode()], 1

            def retr(self, index):
                return (
                    b"+OK",
                    [
                        b"From: Posto <posto@example.com>",
                        b"Subject: NF-e",
                        b"",
                        b"Mensagem",
                    ],
                    50,
                )

            def dele(self, index):
                self.deleted.append(index)

            def quit(self):
                self.quit_called = True
                return b"+OK"

        def run_import(environment, local_complete=True, xml_complete=True):
            fake_server = FakePop3()
            marked = []
            with (
                patch.dict(
                    os.environ,
                    {
                        "RB_ENV": environment,
                        "APP_ENV": environment,
                        "RB_EMAIL_DELETE_FROM_SERVER": "1",
                    },
                    clear=False,
                ),
                patch.object(
                    legacy_services,
                    "_email_config",
                    return_value={
                        "pop_host": "pop.example.com",
                        "pop_port": 995,
                        "use_ssl": 1,
                        "email_user": "teste@example.com",
                        "email_pass": "secret",
                        "storage_limit_gb": 1,
                    },
                ),
                patch.object(
                    legacy_services,
                    "_email_import_pending_local_attachments",
                    return_value={
                        "attachments": 0,
                        "imported": 0,
                        "existing": 0,
                        "errors": 0,
                        "message": "",
                    },
                ),
                patch.object(
                    legacy_services,
                    "_connect_pop3",
                    return_value=fake_server,
                ),
                patch.object(legacy_services, "_row", return_value=None),
                patch.object(
                    legacy_services,
                    "_persist_email_locally",
                    return_value={
                        "email_id": 20,
                        "new": True,
                        "recovered": False,
                        "attachments_added": 0,
                    },
                ),
                patch.object(
                    legacy_services,
                    "_email_local_copy_complete",
                    return_value=(
                        local_complete,
                        "" if local_complete else "anexo ausente",
                    ),
                ),
                patch.object(
                    legacy_services,
                    "_email_import_xml_attachments",
                    return_value={
                        "ok": xml_complete,
                        "relevant_attachments": 1,
                        "imported": 1 if xml_complete else 0,
                        "existing": 0,
                        "errors": 0 if xml_complete else 1,
                        "message": "" if xml_complete else "XML invalido",
                    },
                ),
                patch.object(
                    legacy_services,
                    "_mark_emails_deleted_from_server",
                    side_effect=lambda ids: marked.extend(ids),
                ),
                patch.object(legacy_services, "_storage_used_bytes", return_value=0),
            ):
                legacy_services._import_emails_unlocked(1)
            return fake_server, marked

        homolog_server, homolog_marked = run_import("homologacao")
        self.assertEqual([], homolog_server.deleted)
        self.assertEqual([], homolog_marked)
        self.assertTrue(homolog_server.quit_called)

        production_server, production_marked = run_import("producao")
        self.assertEqual([1], production_server.deleted)
        self.assertEqual([20], production_marked)
        self.assertTrue(production_server.quit_called)

        incomplete_server, incomplete_marked = run_import(
            "producao",
            local_complete=False,
        )
        self.assertEqual([], incomplete_server.deleted)
        self.assertEqual([], incomplete_marked)

        xml_error_server, xml_error_marked = run_import(
            "producao",
            local_complete=True,
            xml_complete=False,
        )
        self.assertEqual([], xml_error_server.deleted)
        self.assertEqual([], xml_error_marked)

    def test_imap_import_uses_since_filter_and_never_deletes(self):
        class FakeImap:
            def __init__(self):
                self.selected = None
                self.search_args = []
                self.fetches = []
                self.logged_out = False
                self.unselected = False

            def select(self, mailbox, readonly=False):
                mailbox_name = mailbox.strip('"')
                self.selected = (mailbox_name, readonly)
                if mailbox_name == "Analise de Refrigerante":
                    return "NO", [b"cannot select"]
                return "OK", [b"2"]

            def search(self, charset, *criteria):
                self.search_args.append((self.selected[0], charset, criteria))
                if self.selected[0] == "Itens Enviados":
                    return "OK", [b"20"]
                return "OK", [b"10 11"]

            def fetch(self, message_id, query):
                self.fetches.append((self.selected[0], message_id, query))
                if self.selected[0] == "INBOX" and message_id == b"10":
                    raw = (
                        b"From: Avisos <aviso@example.com>\n"
                        b"Subject: Comunicado\n\nNada para compras."
                    )
                    return "OK", [(b"10 (UID 100 BODY[] {1}", raw)]
                if self.selected[0] == "INBOX":
                    raw = (
                        b"From: Fornecedor <nfe@example.com>\n"
                        b"Subject: Pedido de materia prima\n\nXML de compra."
                    )
                    return "OK", [(b"11 (UID 101 BODY[] {1}", raw)]
                raw = (
                    b"From: Compras <compras@riob.com.br>\n"
                    b"Subject: Pedido SAPORITI materia prima\n\nSegue pedido."
                )
                return "OK", [(b"20 (UID 202 BODY[] {1}", raw)]

            def unselect(self):
                self.unselected = True
                return "OK", []

            def logout(self):
                self.logged_out = True
                return "BYE", []

        fake_imap = FakeImap()
        persisted = []

        def persist(uid, message, existing=None, account=None, matched_filter=""):
            persisted.append(
                {
                    "uid": uid,
                    "account": account,
                    "matched_filter": matched_filter,
                    "subject": message.get("Subject"),
                }
            )
            return {
                "email_id": 55,
                "new": True,
                "recovered": False,
                "attachments_added": 0,
            }

        account = {
            "id": 2,
            "account_name": "BOL Compras Materia Prima",
            "protocol": "imap",
            "enabled": 1,
            "pop_host": "imap.bol.com.br",
            "pop_port": 993,
            "use_ssl": 1,
            "mailbox": "INBOX",
            "email_user": "riobranco1951@bol.com.br",
            "email_pass": "secret",
            "since_date": "2026-01-01",
            "filter_keywords": "materia prima,pedido",
            "storage_limit_gb": 5,
        }
        with (
            patch.object(
                legacy_services,
                "_email_import_pending_local_attachments",
                return_value={
                    "attachments": 0,
                    "imported": 0,
                    "existing": 0,
                    "errors": 0,
                    "message": "",
                },
            ),
            patch.object(legacy_services, "_email_accounts", return_value=[account]),
            patch.object(legacy_services, "_connect_imap", return_value=fake_imap),
            patch.object(legacy_services, "_row", return_value=None),
            patch.object(
                legacy_services,
                "_persist_email_locally",
                side_effect=persist,
            ),
            patch.object(
                legacy_services,
                "_email_import_xml_attachments",
                return_value={
                    "ok": True,
                    "relevant_attachments": 0,
                    "imported": 0,
                    "existing": 0,
                    "errors": 0,
                    "message": "",
                },
            ),
            patch.object(legacy_services, "_storage_used_bytes", return_value=0),
            patch.dict(
                os.environ,
                {
                    "RB_EMAIL_BOL_HISTORY_MAILBOXES": (
                        "INBOX,Analise de Refrigerante,Itens Enviados"
                    )
                },
                clear=False,
            ),
        ):
            imported, message = legacy_services._import_emails_unlocked(
                0,
                history_until_date="2026-06-23",
                force_xml_attachments=True,
                account_ids=[2],
            )

        self.assertEqual(2, imported)
        self.assertIn("2 novo", message)
        self.assertEqual(("Itens Enviados", True), fake_imap.selected)
        self.assertEqual(
            [
                ("INBOX", None, ("SINCE", "01-Jan-2026", "BEFORE", "24-Jun-2026")),
                ("Itens Enviados", None, ("SINCE", "01-Jan-2026", "BEFORE", "24-Jun-2026")),
            ],
            fake_imap.search_args,
        )
        self.assertEqual(
            [
                ("INBOX", b"10", "(UID BODY.PEEK[])"),
                ("INBOX", b"11", "(UID BODY.PEEK[])"),
                ("Itens Enviados", b"20", "(UID BODY.PEEK[])"),
            ],
            fake_imap.fetches,
        )
        self.assertTrue(fake_imap.unselected)
        self.assertTrue(fake_imap.logged_out)
        self.assertEqual(2, len(persisted))
        self.assertEqual("acct:2:imap:101", persisted[0]["uid"])
        self.assertEqual("Pedido de materia prima", persisted[0]["subject"])
        self.assertEqual(
            "acct:2:imap:Itens Enviados:202",
            persisted[1]["uid"],
        )
        self.assertEqual("Pedido SAPORITI materia prima", persisted[1]["subject"])

    def test_imap_import_reconnects_when_fetch_fails_once(self):
        class FakeImap:
            def __init__(self, fail_fetch=False):
                self.fail_fetch = fail_fetch
                self.selected = None
                self.fetches = []
                self.unselected = False
                self.logged_out = False

            def select(self, mailbox, readonly=False):
                self.selected = (mailbox.strip('"'), readonly)
                return "OK", [b"1"]

            def search(self, charset, *criteria):
                return "OK", [b"1"]

            def fetch(self, message_id, query):
                self.fetches.append((self.selected[0], message_id, query))
                if self.fail_fetch:
                    self.fail_fetch = False
                    return "NO", [b"timeout"]
                raw = (
                    b"From: Fornecedor <nfe@example.com>\n"
                    b"Subject: Pedido materia prima\n\nXML de compra."
                )
                return "OK", [(b"1 (UID 900 BODY[] {1}", raw)]

            def unselect(self):
                self.unselected = True
                return "OK", []

            def logout(self):
                self.logged_out = True
                return "BYE", []

        first_server = FakeImap(fail_fetch=True)
        second_server = FakeImap()
        persisted = []
        account = {
            "id": 2,
            "account_name": "BOL Compras Materia Prima",
            "protocol": "imap",
            "enabled": 1,
            "pop_host": "imap.bol.com.br",
            "pop_port": 993,
            "use_ssl": 1,
            "mailbox": "INBOX",
            "email_user": "riobranco1951@bol.com.br",
            "email_pass": "secret",
            "since_date": "2026-01-01",
            "filter_keywords": "materia prima",
            "storage_limit_gb": 5,
        }

        def persist(uid, message, existing=None, account=None, matched_filter=""):
            persisted.append((uid, message.get("Subject"), matched_filter))
            return {
                "email_id": 56,
                "new": True,
                "recovered": False,
                "attachments_added": 0,
            }

        with (
            patch.object(
                legacy_services,
                "_email_import_pending_local_attachments",
                return_value={
                    "attachments": 0,
                    "imported": 0,
                    "existing": 0,
                    "errors": 0,
                    "message": "",
                },
            ),
            patch.object(legacy_services, "_email_accounts", return_value=[account]),
            patch.object(
                legacy_services,
                "_connect_imap",
                side_effect=[first_server, second_server],
            ),
            patch.object(legacy_services, "_row", return_value=None),
            patch.object(
                legacy_services,
                "_persist_email_locally",
                side_effect=persist,
            ),
            patch.object(
                legacy_services,
                "_email_import_xml_attachments",
                return_value={
                    "ok": True,
                    "relevant_attachments": 0,
                    "imported": 0,
                    "existing": 0,
                    "errors": 0,
                    "message": "",
                },
            ),
            patch.object(legacy_services, "_storage_used_bytes", return_value=0),
        ):
            imported, message = legacy_services._import_emails_unlocked(
                0,
                account_ids=[2],
            )

        self.assertEqual(1, imported)
        self.assertIn("1 novo", message)
        self.assertEqual(
            [("acct:2:imap:900", "Pedido materia prima", "materia prima")],
            persisted,
        )
        self.assertEqual([("INBOX", b"1", "(UID BODY.PEEK[])")], first_server.fetches)
        self.assertEqual([("INBOX", b"1", "(UID BODY.PEEK[])")], second_server.fetches)
        self.assertTrue(first_server.unselected)
        self.assertTrue(first_server.logged_out)
        self.assertTrue(second_server.unselected)
        self.assertTrue(second_server.logged_out)

    def test_zip_attachment_imports_each_xml(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "notas.zip"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("nota-1.xml", b"<nfe>1</nfe>")
                archive.writestr("pasta/nota-2.xml", b"<nfe>2</nfe>")
                archive.writestr("leia-me.txt", b"ignorar")
            zip_path.write_bytes(buffer.getvalue())

            imported_names = []
            with (
                patch.object(
                    legacy_services,
                    "_attachment_path",
                    return_value=zip_path,
                ),
                patch.object(
                    legacy_services,
                    "_email_import_xml_bytes",
                    side_effect=lambda attachment_id, name, payload, **kwargs: (
                        imported_names.append(name)
                        or {
                            "ok": True,
                            "status": "IMPORTADO",
                            "tipo": "ESTOQUE",
                            "registros": 1,
                            "mensagem": "",
                        }
                    ),
                ),
            ):
                result = legacy_services._email_import_xml_attachment(
                    {
                        "id": 5,
                        "filename": "notas.zip",
                        "path_relativo": "notas.zip",
                    }
                )

            self.assertTrue(result["ok"])
            self.assertEqual(
                ["notas.zip::nota-1.xml", "notas.zip::pasta/nota-2.xml"],
                imported_names,
            )

    def test_zip_entry_error_is_tracked(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "notas.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("nota.xml", b"<nfe>conteudo maior</nfe>")

            tracked = []
            with (
                patch.object(
                    legacy_services,
                    "_attachment_path",
                    return_value=zip_path,
                ),
                patch.object(
                    legacy_services,
                    "_email_xml_limits",
                    return_value={
                        "max_entries": 10,
                        "max_file_bytes": 1,
                        "max_total_bytes": 1024,
                    },
                ),
                patch.object(
                    legacy_services,
                    "_email_xml_tracking",
                    side_effect=lambda *args, **kwargs: tracked.append(
                        (args, kwargs)
                    ),
                ),
            ):
                result = legacy_services._email_import_xml_attachment(
                    {
                        "id": 77,
                        "filename": "notas.zip",
                        "path_relativo": "notas.zip",
                    }
                )

            self.assertTrue(result["relevant"])
            self.assertFalse(result["ok"])
            self.assertEqual(1, len(tracked))
            self.assertEqual(77, tracked[0][0][0])
            self.assertEqual("notas.zip::nota.xml", tracked[0][0][1])
            self.assertEqual("ERRO", tracked[0][0][3])

    def test_auto_parts_supplier_routes_xml_to_maintenance(self):
        cab = {
            "chave_nfe": "1" * 44,
            "numero_nota": "123",
            "data_emissao": "2026-06-01T10:00:00-03:00",
            "emitente_cnpj": "12345678000190",
            "emitente_nome": "AUTO PECAS TESTE LTDA",
        }
        items = [
            {
                "descricao_produto": "FILTRO",
                "quantidade": 1,
                "valor_unitario": 50,
                "valor_total_item": 50,
            }
        ]
        tracked = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch.object(legacy_services, "_xml_upload_dir", Path(tmp_dir)),
                patch.object(
                    legacy_services,
                    "_email_xml_limits",
                    return_value={
                        "max_entries": 10,
                        "max_file_bytes": 1024,
                        "max_total_bytes": 1024,
                    },
                ),
                patch.object(legacy_services, "parse_nfe", return_value=(cab, items)),
                patch.object(legacy_services, "eh_combustivel", return_value=False),
                patch.object(
                    legacy_services,
                    "_email_xml_tracking_existing",
                    return_value=None,
                ),
                patch.object(
                    legacy_services,
                    "_supplier_upsert_from_xml",
                    return_value={
                        "id": 7,
                        "nome": "AUTO PECAS TESTE LTDA",
                        "categoria": "pecas_auto",
                    },
                ),
                patch.object(
                    legacy_services,
                    "_email_xml_already_imported",
                    return_value=False,
                ),
                patch.object(
                    legacy_services,
                    "_email_import_maintenance_xml",
                    return_value=(True, 1, "ok"),
                ) as maintenance_import,
                patch.object(
                    legacy_services,
                    "_email_xml_tracking",
                    side_effect=lambda *args, **kwargs: tracked.append(
                        (args, kwargs)
                    ),
                ),
            ):
                result = legacy_services._email_import_xml_bytes(
                    99,
                    "nota.xml",
                    b"<nfe/>",
                    sender_email="auto@example.com",
                )

        self.assertTrue(result["ok"])
        self.assertEqual("MANUTENCAO", result["tipo"])
        maintenance_import.assert_called_once()
        self.assertEqual("IMPORTADO", tracked[0][0][3])
        self.assertEqual(7, tracked[0][1]["fornecedor_id"])
        self.assertEqual("manutencao", tracked[0][1]["destino_importacao"])

    def test_trusted_sender_accepts_zip_above_default_entry_limit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "remessa.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for index in range(205):
                    archive.writestr(f"nota-{index:03d}.xml", b"<nfe/>")

            with (
                patch.dict(
                    os.environ,
                    {
                        "RB_EMAIL_XML_ZIP_MAX_ENTRIES": "200",
                        "RB_EMAIL_XML_TRUSTED_SENDERS":
                            "bebidasriobranco8@gmail.com",
                        "RB_EMAIL_XML_TRUSTED_ZIP_MAX_ENTRIES": "1000",
                    },
                    clear=False,
                ),
                patch.object(
                    legacy_services,
                    "_attachment_path",
                    return_value=zip_path,
                ),
                patch.object(
                    legacy_services,
                    "_email_import_xml_bytes",
                    return_value={
                        "ok": True,
                        "status": "IMPORTADO",
                        "tipo": "ESTOQUE",
                        "registros": 1,
                        "mensagem": "",
                    },
                ) as importer,
            ):
                result = legacy_services._email_import_xml_attachment(
                    {
                        "id": 9,
                        "filename": "remessa.zip",
                        "path_relativo": "remessa.zip",
                    },
                    sender_email="bebidasriobranco8@gmail.com",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(205, importer.call_count)

    def test_local_xml_backlog_prioritizes_trusted_sender(self):
        attachments = [
            {
                "id": 1,
                "email_id": 1,
                "filename": "comum.xml",
                "path_relativo": "comum.xml",
                "size_bytes": 10,
                "sender_email": "outro@example.com",
            },
            {
                "id": 2,
                "email_id": 2,
                "filename": "remessa.zip",
                "path_relativo": "remessa.zip",
                "size_bytes": 20,
                "sender_email": "bebidasriobranco8@gmail.com",
            },
        ]
        processed = []

        def import_attachment(attachment, sender_email=""):
            processed.append((attachment["id"], sender_email))
            return {
                "relevant": True,
                "ok": True,
                "results": [
                    {
                        "ok": True,
                        "status": "IMPORTADO",
                        "mensagem": "",
                    }
                ],
            }

        with (
            patch.object(legacy_services, "_rows", return_value=attachments),
            patch.object(
                legacy_services,
                "_email_import_xml_attachment",
                side_effect=import_attachment,
            ),
        ):
            result = legacy_services._email_import_pending_local_attachments()

        self.assertEqual(
            [
                (2, "bebidasriobranco8@gmail.com"),
                (1, "outro@example.com"),
            ],
            processed,
        )
        self.assertEqual(2, result["imported"])

    def test_local_xml_backlog_runs_even_without_pop3_configuration(self):
        with (
            patch.object(
                legacy_services,
                "_email_import_pending_local_attachments",
                return_value={
                    "attachments": 1,
                    "imported": 255,
                    "existing": 0,
                    "errors": 0,
                    "message": "",
                },
            ),
            patch.object(legacy_services, "_email_config", return_value={}),
        ):
            imported, message = legacy_services._import_emails_unlocked(50)

        self.assertEqual(0, imported)
        self.assertIn("255 importado(s)", message)

    def test_scheduler_only_runs_in_production_business_hours(self):
        timezone = ZoneInfo("America/Sao_Paulo")
        with patch.dict(
            os.environ,
            {
                "RB_ENV": "homologacao",
                "RB_EMAIL_AUTO_IMPORT": "1",
            },
            clear=False,
        ):
            self.assertFalse(legacy_services._email_scheduler_enabled())

        with patch.dict(
            os.environ,
            {
                "RB_ENV": "producao",
                "RB_EMAIL_AUTO_IMPORT": "1",
                "RB_EMAIL_BUSINESS_START": "08:00",
                "RB_EMAIL_BUSINESS_END": "18:00",
                "RB_EMAIL_BUSINESS_DAYS": "0,1,2,3,4",
                "RB_EMAIL_TIMEZONE": "America/Sao_Paulo",
            },
            clear=False,
        ):
            config = legacy_services._email_schedule_config()
            friday = datetime(2026, 6, 12, 10, 0, tzinfo=timezone)
            saturday = datetime(2026, 6, 13, 10, 0, tzinfo=timezone)
            after_hours = datetime(2026, 6, 12, 18, 1, tzinfo=timezone)
            self.assertTrue(legacy_services._email_scheduler_enabled())
            self.assertTrue(
                legacy_services._email_is_business_time(friday, config)
            )
            self.assertFalse(
                legacy_services._email_is_business_time(saturday, config)
            )
            self.assertFalse(
                legacy_services._email_is_business_time(after_hours, config)
            )
            next_run = legacy_services._email_next_business_run(
                saturday,
                config,
            )
            self.assertEqual(0, next_run.weekday())
            self.assertEqual("08:00", next_run.strftime("%H:%M"))


if __name__ == "__main__":
    unittest.main()
