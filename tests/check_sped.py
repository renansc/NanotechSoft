"""Headless browser fixture for integrated SPED parsing; uses synthetic data only."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_SOURCE = (ROOT / "apps/sped/source/index.html").read_text(encoding="utf-8")
SOURCE = re.sub(r"<header>.*?</header>", "", RAW_SOURCE, count=1, flags=re.I | re.S)
SOURCE = re.sub(r'<nav class="nav">.*?</nav>', "", SOURCE, count=1, flags=re.I | re.S)
SYNTHETIC_SPED = """|0000|||01012026||EMPRESA TESTE|12345678000199|
|0150|CLI1|CLIENTE TESTE||12345678000199|||3550308||RUA TESTE|
|0190|31|KG|
|0200|PROD1|AROMA LARANJA LIMÃO RODOLAR FORTE|||31||22021000|
|C100|0|1|CLI1|55|00|1|123|35260123456780001995550010000001231000001234|02012026||150,00|||||||||150,00|27,00|||||
|C170|1|PROD1||2,00|31|150,00|75,00|0,00|000|5102||150,00|18,00|27,00|||||||||
|C190|000|5102|18,00|150,00|150,00|27,00|
|E110|27,00||||0,00||||||27,00||27,00|
"""


chrome = next(
    (path for command in ("google-chrome", "chromium", "chromium-browser")
     if (path := shutil.which(command))),
    None,
)
if not chrome:
    raise SystemExit("Chrome/Chromium nao encontrado para a verificacao SPED.")

fixture = f"""
<script>
(async () => {{
  document.documentElement.dataset.spedStarted = "true";
  try {{
    data = [parse({json.dumps(SYNTHETIC_SPED)}, "sped-sintetico.txt")];
    render();
    document.documentElement.dataset.spedFiles = document.querySelector("#filesBadge").textContent;
    document.documentElement.dataset.spedDocs = document.querySelector("#docs").textContent;
    document.documentElement.dataset.spedItems = document.querySelector("#items").textContent;
    document.documentElement.dataset.spedCompany = String(document.querySelector("#fileRows").textContent.includes("EMPRESA TESTE"));
    document.documentElement.dataset.spedUnit = data[0].saleItems[0].unit;
    document.documentElement.dataset.spedUnitValue = String(data[0].saleItems[0].unitValue);
    document.documentElement.dataset.spedNetwork = String(performance.getEntriesByType("resource").filter(item => /^https?:/.test(item.name)).length);
    let synced;
    window.fetch = async (url, options) => {{
      synced = {{url, body: JSON.parse(options.body)}};
      return {{ok: true, json: async () => ({{itens_gravados: 1}})}};
    }};
    await syncCostReferences(data[0]);
    document.documentElement.dataset.spedSync = String(
      synced.url === "/apps/riob/api/custo-produto/sped"
      && synced.body.empresa_cnpj === "12345678000199"
      && synced.body.itens[0].data_emissao === "2026-01-02"
      && synced.body.itens[0].unidade === "KG"
      && synced.body.itens[0].valor_item === 150
    );
    page("sales");
    document.documentElement.dataset.spedSaleDefault = String(
      document.querySelector("#saleOp").value === "all"
      && document.querySelector("#saleCount").textContent === "1"
    );
    const productSelect = document.querySelector("#saleProduct");
    const clientSelect = document.querySelector("#saleClient");
    const documentSelect = document.querySelector("#saleDocument");
    productSelect.value = "PROD1";
    productSelect.dispatchEvent(new Event("change", {{bubbles: true}}));
    document.documentElement.dataset.spedSaleProduct = String(
      document.querySelector("#saleCount").textContent === "1"
      && clientSelect.options.length === 2
      && documentSelect.options.length === 2
    );
    clientSelect.selectedIndex = 1;
    clientSelect.dispatchEvent(new Event("change", {{bubbles: true}}));
    documentSelect.selectedIndex = 1;
    documentSelect.dispatchEvent(new Event("change", {{bubbles: true}}));
    document.documentElement.dataset.spedSaleCombined = String(
      document.querySelector("#saleCount").textContent === "1"
      && document.querySelector("#saleSearchStatus").textContent.includes("Consulta concluída")
    );
    document.querySelector("#saleOp").value = "Saída";
    document.querySelector("#saleOp").dispatchEvent(new Event("change", {{bubbles: true}}));
    document.documentElement.dataset.spedSaleEmpty = String(
      document.querySelector("#saleCount").textContent === "0"
      && document.querySelector("#saleSearchStatus").textContent.includes("Nenhum item")
    );
    document.querySelector("#saleClear").click();
    document.documentElement.dataset.spedSaleClear = String(
      document.querySelector("#saleOp").value === "all"
      && productSelect.value === "all"
      && clientSelect.value === "all"
      && documentSelect.value === "all"
      && document.querySelector("#saleCount").textContent === "1"
    );
    page("details");
    document.documentElement.dataset.spedPreserved = String(data.length === 1 && !document.querySelector("#page-details").classList.contains("hidden"));
  }} catch (error) {{
    document.documentElement.dataset.spedError = error.message;
  }}
}})();
</script>
"""
html = SOURCE.replace("</body>", fixture + "</body>")

with tempfile.TemporaryDirectory(prefix="sped-browser-") as temporary:
    temporary_path = Path(temporary)
    fixture_path = temporary_path / "index.html"
    fixture_path.write_text(html, encoding="utf-8")
    result = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--enable-logging=stderr",
            "--v=0",
            "--dump-dom",
            "--virtual-time-budget=2500",
            f"--user-data-dir={temporary_path / 'chrome'}",
            fixture_path.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

output = result.stdout
diagnostic = result.stderr[-4000:] + "\n" + output[:1000] + "\n...\n" + output[-2000:]
assert 'data-sped-files="1 arquivo(s)"' in output, diagnostic
assert 'data-sped-docs="1"' in output, output[-2000:]
assert 'data-sped-items="1"' in output, output[-2000:]
assert 'data-sped-company="true"' in output, output[-2000:]
assert 'data-sped-unit="KG"' in output, output[-2000:]
assert 'data-sped-unit-value="37.5"' in output, output[-2000:]
assert 'data-sped-network="0"' in output, output[-2000:]
assert 'data-sped-sync="true"' in output, output[-2000:]
assert 'data-sped-sale-default="true"' in output, output[-2000:]
assert 'data-sped-sale-product="true"' in output, output[-2000:]
assert 'data-sped-sale-combined="true"' in output, output[-2000:]
assert 'data-sped-sale-empty="true"' in output, output[-2000:]
assert 'data-sped-sale-clear="true"' in output, output[-2000:]
assert 'data-sped-preserved="true"' in output, output[-2000:]
assert "Uncaught" not in result.stderr, result.stderr
print("OK: TXT sintetico processado; dashboard, seletores fiscais, itens e resumo de custo SPED validados sem rede externa.")
