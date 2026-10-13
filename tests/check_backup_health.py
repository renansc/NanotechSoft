"""Browser regression: historical success cannot mask a disconnected agent."""
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / "apps/tecnologia/source"


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/google/chrome/chrome", headless=True, args=["--no-sandbox"])
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    mode = "OFFLINE"

    def serve(route):
        path = urlsplit(route.request.url).path
        assert route.request.method == "GET", "No business writes in browser test"
        if path.endswith("/backup/jobs"):
            if mode == "FAIL_FETCH":
                route.fulfill(status=503, json={"erro": "indisponivel"})
                return
            route.fulfill(json={"jobs": [{
                "id": 1, "name": "Backup <teste>", "machine": "Servidor", "active": True,
                "health": mode, "times": ["08:00"], "destinationPath": "/media/discoExterno/Backups",
                "lastSeenAt": "2026-09-24T09:47:00Z", "databaseType": "FILES", "sourcePaths": ["/origem"],
                "lastRun": {"status": "SUCCESS", "completedAt": "2026-09-23T19:00:00Z", "sizeBytes": 1024},
            }], "executions": [{"jobName": "Backup <teste>", "status": "SUCCESS", "completedAt": "2026-09-23T19:00:00Z", "tiers": ["diario"], "message": "Sucesso antigo"}]})
        elif "/api/" in path:
            route.fulfill(json={})
        else:
            target = ROOT / (path.removeprefix("/apps/tecnologia/") or "index.html")
            mime = "text/javascript" if target.suffix == ".js" else "text/css" if target.suffix == ".css" else "image/svg+xml" if target.suffix == ".svg" else "text/html"
            route.fulfill(body=target.read_bytes(), content_type=mime)

    page.route("**/*", serve)
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 1000})
        mode = "OFFLINE"
        page.goto("about:blank")
        page.goto("http://backup.test/apps/tecnologia/#backup-visao")
        expect(page.locator("#backupCurrentStatus")).to_have_class("diag critical")
        expect(page.locator("#backupHealthTable")).to_contain_text("Erro: agente sem contato")
        expect(page.locator("#backupHealthTable")).to_contain_text("Backup <teste>")
        expect(page.locator("#backupHealthTable")).to_contain_text("/media/discoExterno/Backups")
        expect(page.locator("#backupRunsTable")).to_contain_text("Sucesso antigo")
        expect(page.locator("#newBackup")).not_to_be_visible()
        mode = "FAIL_FETCH"
        page.evaluate("window.dispatchEvent(new HashChangeEvent('hashchange'))")
        expect(page.locator("#backupCurrentStatus")).to_contain_text("Erro ao atualizar")
        mode = "ONLINE"
        page.evaluate("window.dispatchEvent(new HashChangeEvent('hashchange'))")
        expect(page.locator("#backupCurrentStatus")).to_contain_text("Agentes conectados")
        expect(page.locator("#backupCurrentStatus")).not_to_have_class("diag critical")
    assert not errors, errors
    browser.close()
    print("OK: offline + sucesso antigo, destino, falha de consulta, recuperacao e desktop/celular")
