import json
import re
import runpy
import unittest
from pathlib import Path
from unittest import mock

import app as portal
from jinja2 import Environment, FileSystemLoader, select_autoescape


class MenuPdfTests(unittest.TestCase):
    def setUp(self):
        self.client = mock.patch.object(portal, "configured_client_id", return_value="rio-branco")
        self.client.start()
        self.addCleanup(self.client.stop)
        contract = json.loads((Path(portal.BASE_DIR) / "clientes-modulos.json").read_text())
        self.keys = {m["slug"] for c in contract["clients"] if c["id"] == "rio-branco" for m in c["modules"]}
        self.apps = [portal.normalize_app(json.loads((Path(portal.BASE_DIR) / "apps" / key / "app.json").read_text())) for key in self.keys]

    def test_filesystem_loading_preserves_menu_and_permission_catalog(self):
        with mock.patch.object(portal, "database_apps", return_value=[]), mock.patch.object(portal, "active_external_apps", return_value=[]):
            apps = portal.list_apps()
            menu = portal.menu_sections(apps, {"id": 1, "perfil": "admin"})
            self.assertEqual(10, len(menu["primary"]))
            catalog = {a["app_key"]: {r["key"] for r in a["recursos"]} for a in portal.permission_catalog()}
        self.assertIn("estoque_contagem", catalog["riob"])
        self.assertIn("vendas_orcamentos_relatorio", catalog["riob"])
        self.assertIn("backup", catalog["riob-email"])
        self.assertIn("estoque_contagem_finalizar", catalog["riob"])
        self.assertIn("estoque_contagem_relatorio", catalog["riob"])

    def test_header_order_and_module_groups(self):
        menu = portal.menu_sections(self.apps, {"id": 1, "perfil": "admin"})
        self.assertEqual(["DASHBOARD", "WORKFLOW", "GESTAO", "CADASTRO", "RELATORIOS", "DADOS", "ESTOQUE", "MONITOR", "CONFIGURAR", "DOCUMENTOS"], [s["nome"] for s in menu["primary"]])
        with portal.app.test_request_context():
            html = portal.render_template("_menu.html", menu=menu, usuario={"perfil": "admin"})
        self.assertEqual(1, html.count('id="mainMenu"'))
        self.assertIn("#estoque:contagem", html)
        self.assertIn("#relatorios:orcamentos", html)
        self.assertIn("/riob/backup", html)
        self.assertIn("/riob/historico", html)
        self.assertIn("/riob/recuperar", html)
        self.assertNotIn("module-riob-chat", html)
        for section in menu["primary"]:
            self.assertTrue(all(g["nome"] and g["entries"] for g in section["groups"]))

    def test_existing_destinations_are_preserved_by_client_menu(self):
        menu = portal.menu_sections(self.apps, {"id": 1, "perfil": "admin"})
        links = {e["url"] for s in menu["primary"] for g in s["groups"] for e in g["entries"]}
        equivalents = {
            "/apps/tecnologia": ["/apps/tecnologia#dashboard"],
            "/apps/tecnologia#backup": ["/apps/tecnologia#backup-visao", "/apps/tecnologia#backup-planos", "/apps/tecnologia#backup-agentes"],
            "/apps/riob-email/riob": ["/apps/riob-email/riob/?painel=resumo"],
        }
        # Excecoes explicitas do contrato e do popup de Comunicacao, nao uma
        # permissao generica para omitir os demais atalhos dos manifests.
        exceptions = {
            "/apps/riob#monitor:cameras": "Modulo desativado neste cliente",
            "/apps/riob#config:cameras": "Modulo desativado neste cliente",
            "/apps/riob#monitor:esxi": "Modulo desativado neste cliente",
            "/apps/riob#comunicacao": "Popup de Comunicacao",
            "/apps/riob#comunicacao:chat": "Popup de Comunicacao / Chat",
            "/apps/riob#comunicacao:ia": "Popup de Comunicacao / IA",
            "/apps/riob#agentia": "Popup de Comunicacao / Agent IA",
            "/apps/riob#comunicacao:telefonia": "Popup de Comunicacao / Telefonia",
        }
        for item in self.apps:
            entries = list(item.get("workflow_cards") or [])
            for key in ("menu_groups", "config_groups"):
                entries += [e for group in (item.get(key) or {}).values() for e in group]
            for entry in entries:
                url = entry["url"]
                with self.subTest(app=item["app_key"], url=url):
                    if url in exceptions:
                        self.assertNotIn(url, links)
                    else:
                        for destination in equivalents.get(url, [url]):
                            self.assertIn(destination, links, "Atalho perdido na reorganizacao")
        documented=(Path(portal.BASE_DIR)/'docs/MENU_RIO_BRANCO_PDF.md').read_text()
        for destination in re.findall(r'^\| [^\n]+ \| `([^`]+)` \| `[^`]+` \|$',documented,re.M):
            self.assertIn(destination,links,"Destino da matriz documentada ausente do menu")

    def test_documentation_menu_preserves_module_permissions(self):
        user = {"id":42,"perfil":"usuario"}
        with mock.patch.object(portal,"get_user_permissions",return_value={"automacao":{"*"},"chamados":{"documentos"}}):
            menu=portal.menu_sections(self.apps,user)
            docs=next(section for section in menu["primary"] if section["key"]=="docs")
            links={e["url"] for g in docs["groups"] for e in g["entries"]}
            self.assertIn('/apps/automacao/documentacao',links)
            self.assertIn('/apps/chamados?view=documentos',links)
        with mock.patch.object(portal,"get_user_permissions",return_value={"riob":{"vendas"}}):
            menu=portal.menu_sections(self.apps,user)
            self.assertFalse(any(s["key"]=="docs" for s in menu["primary"]))
        paths=['/apps/automacao/documentacao','/apps/automacao/documentacao/empacotadora-rodighero-er1500',
               '/apps/automacao/static/documentos/manual-fotografado-rodighero-er1500.pdf',
               '/apps/automacao/documentacao/envasadora-zegla-40-50-10-ga',
               '/apps/automacao/static/documentos/envasadora-zegla-40-50-10-ga.pdf',
               '/apps/automacao/documentacao/impressora-laser-cyklop',
               '/apps/automacao/static/documentos/protocolo-comunicacao-laser-cyklop-n8-v1.2.pdf',
               '/apps/automacao/maquinas/impressora-laser-cyklop',
               '/apps/automacao/api/maquinas',
               '/apps/automacao/api/maquinas/impressora-laser-cyklop/ultima']
        for path in paths:
            for permissions,allowed in (({"automacao":{"*"}},True),({"riob":{"vendas"}},False)):
                with self.subTest(path=path,allowed=allowed), portal.app.test_request_context(path), mock.patch.object(portal,'allowed_app_keys',return_value=self.keys), mock.patch.object(portal,'current_user_or_logout',return_value=user), mock.patch.object(portal,'get_user_permissions',return_value=permissions):
                    result=portal.enforce_app_permission()
                    self.assertIsNone(result) if allowed else self.assertEqual(403,result[1])
        with portal.app.test_request_context('/apps/automacao/documentacao'), mock.patch.object(portal,'allowed_app_keys',return_value=self.keys), mock.patch.object(portal,'current_user_or_logout',return_value=None):
            self.assertEqual('/login',portal.enforce_app_permission().location)

    def test_cyklop_gateway_requires_automation_permission(self):
        path = '/apps/automacao/api/maquinas/impressora-laser-cyklop/leituras'
        user = {"id": 42, "perfil": "usuario"}
        for permissions, allowed in (({"automacao": {"*"}}, True), ({"riob": {"vendas"}}, False)):
            with self.subTest(allowed=allowed), portal.app.test_request_context(path, method='POST'), mock.patch.object(portal, 'allowed_app_keys', return_value=self.keys), mock.patch.object(portal, 'current_user_or_logout', return_value=user), mock.patch.object(portal, 'get_user_permissions', return_value=permissions):
                result = portal.enforce_app_permission()
                self.assertIsNone(result) if allowed else self.assertEqual(403, result[1])

    def test_documentation_detail_uses_documents_section(self):
        self.assertEqual('docs',portal.automacao_active_page('documentacao/empacotadora-rodighero-er1500'))
        with portal.app.test_request_context('/apps/chamados?view=documentos'):
            self.assertEqual('docs',portal.static_app_active_page('chamados',''))
        with mock.patch.object(portal,'configured_client_id',return_value='nanotech'):
            self.assertEqual('cadastros',portal.automacao_active_page('documentacao'))

    def test_manual_links_are_rewritten_under_authenticated_proxy(self):
        root=Path(portal.BASE_DIR)/'apps/automacao/source'
        machines=runpy.run_path(str(root/'machine_catalog.py'))['DOCUMENTED_MACHINES']
        templates=Environment(loader=FileSystemLoader(root/'templates'),autoescape=select_autoescape())
        raw=templates.get_template('documentacao.html').render(maquinas=machines).encode()
        with portal.app.test_request_context('/apps/automacao/documentacao'), mock.patch.object(portal,'current_theme_key',return_value='rio_branco'):
            _style,html=portal.extract_automacao_page(raw)
        for machine in machines:
            self.assertIn('href="/apps/automacao/documentacao/'+machine['slug']+'"',html)
            self.assertIn('href="/apps/automacao/static/'+machine['documentacao']['arquivo']+'"',html)
        self.assertNotIn('href="/static/',html)

    def test_other_clients_keep_original_menu(self):
        with mock.patch.object(portal, "configured_client_id", return_value="nanotech"):
            menu = portal.menu_sections(self.apps, {"id": 1, "perfil": "admin"})
        self.assertNotIn("primary", menu)
        self.assertTrue(menu["modules"])

    def test_sales_user_sees_report_without_stock_or_email(self):
        with mock.patch.object(portal, "get_user_permissions", return_value={"riob": {"vendas", "vendas_orcamentos_relatorio"}}):
            menu = portal.menu_sections(self.apps, {"id": 42, "perfil": "usuario"})
        links = [e["url"] for s in menu["primary"] for g in s["groups"] for e in g["entries"]]
        self.assertIn("/apps/riob#relatorios:orcamentos", links)
        self.assertNotIn("/apps/riob#estoque:contagem", links)
        self.assertFalse(any("riob-email" in url for url in links))

    def test_new_routes_preserve_server_resource_checks(self):
        cases = [
            ("/apps/riob/api/estoque/contagens/conferir", "POST", {"riob": {"estoque_contagem_finalizar"}}, True),
            ("/apps/riob/api/estoque/contagens/conferir", "POST", {"riob": {"estoque_contagem"}}, False),
            ("/apps/riob/api/estoque/contagens/1/finalizar", "POST", {"riob": {"estoque_contagem_finalizar"}}, True),
            ("/apps/riob/api/estoque/contagens/1/finalizar", "POST", {"riob": {"estoque"}}, False),
            ("/apps/riob/api/estoque/contagens/relatorio", "GET", {"riob": {"estoque_contagem_relatorio"}}, True),
            ("/apps/riob/api/estoque/contagens/relatorio/pdf", "GET", {"riob": {"estoque_contagem"}}, False),
            ("/apps/riob/api/vendas/diario/importar", "POST", {"riob": {"vendas"}}, True),
            ("/apps/riob/api/vendas/diario/importar", "POST", {"riob": {"estoque"}}, False),
            ("/apps/riob/api/vendas/orcamentos/relatorio", "GET", {"riob": {"vendas_orcamentos_relatorio"}}, True),
            ("/apps/riob/api/vendas/orcamentos/relatorio", "GET", {"riob": {"estoque"}}, False),
            ("/apps/riob/api/estoque/posicao", "GET", {"riob": {"estoque_contagem"}}, True),
            ("/apps/riob/api/estoque/posicao", "GET", {"riob": {"vendas"}}, False),
            ("/apps/riob-email/riob/backup/download", "POST", {"riob-email": {"*"}}, True),
            ("/apps/riob-email/riob/backup/download", "POST", {"riob": {"vendas"}}, False),
            ("/apps/riob/api/vendas/orcamentos/relatorio", "GET", {"riob": {"vendas"}}, False),
            ("/apps/riob/api/vendas/orcamentos/1/pdf", "GET", {"riob": {"vendas_orcamentos_relatorio"}}, True),
            ("/apps/riob/api/estoque/produtos/1/ajuste", "POST", {"riob": {"estoque_contagem"}}, False),
            ("/apps/riob-email/riob/backup/download", "POST", {"riob-email": {"backup"}}, True),
            ("/apps/riob-email/riob/importar", "POST", {"riob-email": {"backup"}}, False),
            ("/apps/riob-email/riob/backup/download", "POST", {"riob-email": {"operacao"}}, False),
            ("/apps/riob/gestor-emails/backup/download", "POST", {"riob": {"vendas"}}, False),
        ]
        for path, method, permissions, allowed in cases:
            with self.subTest(path=path, allowed=allowed), portal.app.test_request_context(path, method=method), mock.patch.object(portal, "current_user_or_logout", return_value={"id": 42, "perfil": "usuario"}), mock.patch.object(portal, "allowed_app_keys", return_value=self.keys), mock.patch.object(portal, "get_user_permissions", return_value=permissions):
                result = portal.enforce_app_permission()
                self.assertIsNone(result) if allowed else self.assertEqual(403, result[1])

    def test_disabled_modules_block_admin_and_embedded_alias(self):
        paths = [f"/apps/{key}/" for key in ("financeiro", "nanoponto", "nanostore", "riob-cameras", "riob-esxi")]
        paths += ["/apps/riob/monitor/cameras/", "/apps/riob/monitor/esxi/api/status", "/api/finance/attachments"]
        for path in paths:
            with self.subTest(path=path), portal.app.test_request_context(path), mock.patch.object(portal, "allowed_app_keys", return_value=self.keys), mock.patch.object(portal, "current_user_or_logout", return_value={"id": 1, "perfil": "admin"}):
                self.assertEqual(404, portal.enforce_app_permission()[1])

    def test_catalog_preserves_all_previous_resources(self):
        with mock.patch.object(portal, "list_apps", return_value=self.apps):
            catalog = {a["app_key"]: {r["key"] for r in a["recursos"]} for a in portal.permission_catalog()}
        for app in self.apps:
            for key in ("menu_groups", "config_groups"):
                for items in app.get(key, {}).values():
                    for item in items:
                        if item.get("recurso"):
                            self.assertIn(item["recurso"], catalog[app["app_key"]])


if __name__ == "__main__":
    unittest.main()
