import json
import html
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def function_source(source, name, next_name):
    start = source.index(f"function {name}")
    end = source.index(f"function {next_name}", start)
    return source[start:end]


def run_chrome_script(script):
    page = f"<body><script>{script}</script></body>"
    with tempfile.TemporaryDirectory(prefix="financeiro-js-test-") as temp_dir:
        page_path = Path(temp_dir) / "test.html"
        page_path.write_text(page, encoding="utf-8")
        return subprocess.run(
            [
                shutil.which("google-chrome"),
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--dump-dom",
                page_path.as_uri(),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout


class FinanceiroConciliacaoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (PROJECT_DIR / "apps/financeiro/static/app.js").read_text(encoding="utf-8")
        cls.markup = (PROJECT_DIR / "apps/financeiro/source.html").read_text(encoding="utf-8")

    def test_tela_diferencia_sem_vinculo_match_e_vinculado(self):
        self.assertIn("Sem vínculo", self.markup)
        self.assertIn("Match sugerido", self.markup)
        self.assertIn("Vinculado", self.markup)
        self.assertIn("Match #${pairNumber}", self.source)
        self.assertIn("Com: ${escapeHtml", self.source)

    def test_sugestao_nao_grava_antes_da_confirmacao(self):
        handler = self.source.split('$("#btnSugerir").addEventListener', 1)[1]
        handler = handler.split('$("#btnSelecionarMatches").addEventListener', 1)[0]
        self.assertIn("reconciliationSuggestions", handler)
        self.assertNotIn("persistStateOrRollback", handler)

    def test_varios_matches_podem_ser_vinculados_em_uma_gravacao(self):
        self.assertIn('id="btnVincularMatches"', self.markup)
        handler = self.source.split('$("#btnVincularMatches").addEventListener', 1)[1]
        handler = handler.split("function scoreMatch", 1)[0]
        self.assertIn("for(const pair of pairs)", handler)
        self.assertEqual(1, handler.count("persistStateOrRollback"))
        self.assertIn("confirmBankValueCorrections", handler)
        self.assertIn("correctLancamentoFromBank", handler)

    def test_match_automatico_exige_mesmo_tipo_financeiro(self):
        self.assertIn('bankIsCredit !== (lanc.tipo === "RECEITA")', self.source)

    def test_exclusao_sem_vinculo_cria_bloqueio_para_reimportacao(self):
        self.assertIn('id="btnIgnorarBankTx"', self.markup)
        self.assertIn("state.ignoredBankTransactions.push", self.source)
        self.assertIn("knownBankTransactionKeys", self.source)
        portal_source = (PROJECT_DIR / "app.py").read_text(encoding="utf-8")
        self.assertIn('"ignoredBankTransactions"', portal_source)

    def test_importacao_pode_trocar_conta_ou_ser_excluida_na_tela_importar(self):
        self.assertIn('id="listaImportsImportar"', self.markup)
        self.assertIn('data-act="moveImport"', self.source)
        self.assertIn('data-act="delImport"', self.source)
        self.assertIn("moveFinanceImportAccount", self.source)
        self.assertIn("deleteFinanceImportFromState", self.source)
        self.assertIn("Lançamentos e títulos criados no sistema serão preservados", self.source)

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome nao instalado")
    def test_troca_de_conta_move_vinculos_e_exclusao_preserva_registros(self):
        start = self.source.index("function financeImportRelatedSummary")
        end = self.source.index("function renderFinanceImportsList", start)
        functions = self.source[start:end]
        scenario = f"""
let completeImportTargetId = null;
let state = {{
  contas: [{{id:"errada",nome:"Errada"}},{{id:"correta",nome:"Correta"}}],
  imports: [{{id:"imp_1",contaId:"errada",txs:[{{id:"bank_1",fitid:"fit_1",date:"2026-08-20",amount:-10,memo:"PIX"}}]}}],
  reconciliations: [{{bankTxId:"bank_1",lancId:"lanc_1"}}],
  ignoredBankTransactions: [],
  lancamentos: [{{id:"lanc_1",contaId:"errada",bankTxId:"bank_1",conciliado:true}}],
  titulos: [{{id:"tit_1",contaId:"errada",bankTxId:"bank_1",lancId:"lanc_1"}}],
  compras: [{{id:"compra_1",titleId:"tit_1",contaId:"errada"}}]
}};
function bankTransactionKey(contaId, tx){{ return `${{contaId}}|${{tx.date}}|${{tx.amount}}|${{tx.memo}}`; }}
function isTransferenciaLancamento(item){{ return !!item.transferenciaId; }}
{functions}
const moved = moveFinanceImportAccount("imp_1", "correta");
const afterMove = JSON.parse(JSON.stringify(state));
const removed = deleteFinanceImportFromState("imp_1");
document.body.innerHTML = `<pre id="result">${{JSON.stringify({{moved,afterMove,removed,afterDelete:state}})}}</pre>`;
"""
        output = run_chrome_script(scenario)
        match = re.search(r'<pre id="result">(.*?)</pre>', output)
        self.assertIsNotNone(match, output)
        result = json.loads(html.unescape(match.group(1)))
        self.assertEqual("correta", result["afterMove"]["imports"][0]["contaId"])
        self.assertEqual("correta", result["afterMove"]["lancamentos"][0]["contaId"])
        self.assertEqual("correta", result["afterMove"]["titulos"][0]["contaId"])
        self.assertEqual("correta", result["afterMove"]["compras"][0]["contaId"])
        self.assertEqual([], result["afterDelete"]["imports"])
        self.assertIsNone(result["afterDelete"]["lancamentos"][0]["bankTxId"])
        self.assertFalse(result["afterDelete"]["lancamentos"][0]["conciliado"])
        self.assertIsNone(result["afterDelete"]["titulos"][0]["bankTxId"])

    def test_conciliacao_permite_excluir_lancamento_sem_vinculo(self):
        self.assertIn('id="btnExcluirLancConc"', self.markup)
        self.assertIn('$("#btnExcluirLancConc").addEventListener', self.source)
        self.assertIn("removeLancamentosFromState", self.source)
        self.assertIn("título(s) de origem também serão excluídos", self.source)

    def test_conciliacao_permite_excluir_todos_sem_vinculo_em_lote(self):
        self.assertIn('id="btnExcluirTodosLancSemVinculo"', self.markup)
        self.assertIn("unlinkedLancamentoDeletionPlan", self.source)
        handler = self.source.split('$("#btnExcluirTodosLancSemVinculo").addEventListener', 1)[1]
        handler = handler.split('$("#bankList").addEventListener', 1)[0]
        self.assertIn("for(const lancamentoId of plan.roots)", handler)
        self.assertEqual(1, handler.count("persistStateOrRollback"))
        self.assertIn("Esta ação não exclui lançamentos já vinculados", handler)
        self.assertIn("o outro lado já está vinculado", handler)
        self.assertIn("deleteSourceTitles: true", handler)
        self.assertIn("título(s) de origem também serão excluídos", handler)

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome nao instalado")
    def test_exclusao_em_lote_preserva_vinculados_e_transferencia_parcial(self):
        start = self.source.index("function unlinkedLancamentoDeletionPlan")
        end = self.source.index('$("#tbLanc").addEventListener', start)
        plan_function = self.source[start:end]
        scenario = f"""
let state = {{
  lancamentos: [
    {{id:"avulso", contaId:"conta_a", tipo:"DESPESA", valor:100}},
    {{id:"vinculado", contaId:"conta_a", tipo:"RECEITA", valor:5}},
    {{id:"transf_a", contaId:"conta_a", tipo:"DESPESA", valor:20, transferenciaId:"transf_ok"}},
    {{id:"transf_b", contaId:"conta_b", tipo:"RECEITA", valor:20, transferenciaId:"transf_ok"}},
    {{id:"parcial_a", contaId:"conta_a", tipo:"DESPESA", valor:30, transferenciaId:"transf_parcial"}},
    {{id:"parcial_b", contaId:"conta_b", tipo:"RECEITA", valor:30, transferenciaId:"transf_parcial"}}
  ],
  reconciliations: [
    {{lancId:"vinculado", bankTxId:"bank_1"}},
    {{lancId:"parcial_b", bankTxId:"bank_2"}}
  ],
  titulos: [{{id:"titulo_1", lancId:"transf_b", status:"BAIXADO"}}],
  compras: []
}};
function getTransferenciaEntries(transferenciaId){{
  return state.lancamentos.filter(item => item.transferenciaId === transferenciaId);
}}
function getCompraByTituloId(tituloId){{
  return state.compras.find(compra => compra.titleId === tituloId) || null;
}}
{plan_function}
const result = unlinkedLancamentoDeletionPlan("conta_a");
document.body.innerHTML = `<pre id="result">${{JSON.stringify(result)}}</pre>`;
"""
        output = run_chrome_script(scenario)
        match = re.search(r'<pre id="result">(.*?)</pre>', output)
        self.assertIsNotNone(match)
        result = json.loads(html.unescape(match.group(1)))
        self.assertEqual(["avulso", "transf_a"], result["roots"])
        self.assertEqual(2, result["selectedCount"])
        self.assertEqual(3, result["removedCount"])
        self.assertEqual(-120, result["netImpact"])
        self.assertEqual(0, result["reopenedTitles"])
        self.assertEqual(1, result["deletedTitles"])
        self.assertEqual(1, result["transferCount"])
        self.assertEqual(1, result["skippedTransferCount"])

    def test_possiveis_duplicados_sao_destacados(self):
        self.assertIn("possibleDuplicateBankTransaction", self.source)
        self.assertIn("Possível duplicado", self.source)
        self.assertIn("Já consta no banco", self.source)

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome nao instalado")
    def test_repara_titulo_do_extrato_que_roubou_vinculo_existente(self):
        start = self.source.index("function statementBankTransactionsById")
        end = self.source.index("function tituloLancamentoPayloadFromRecord", start)
        functions = self.source[start:end]
        scenario = r'''
let financeStateNeedsPersist = false;
function normalizeText(value){ return String(value || "").toLowerCase().replace(/[^a-z0-9\s]/g, " ").replace(/\s+/g, " ").trim(); }
const bankTx = {id:"bank_fernando",date:"2026-08-21",amount:-1613.88,memo:"PIX FERNANDO MOREIRA"};
const data = {
  imports:[{id:"imp",contaId:"inter_pf",txs:[bankTx]}],
  lancamentos:[
    {id:"original",contaId:"inter_pf",tipo:"DESPESA",valor:1613.88,desc:"Parcela Fernando Moreira",bankTxId:"bank_fernando"},
    {id:"duplicado",contaId:"inter_pf",tipo:"DESPESA",valor:1613.88,desc:"PIX FERNANDO MOREIRA",bankTxId:"bank_fernando"}
  ],
  titulos:[
    {id:"titulo_original",lancId:"original",pessoa:"Fernando",desc:"Parcela",status:"BAIXADO",bankTxId:null},
    {id:"titulo_duplicado",lancId:"duplicado",pessoa:"",desc:"PIX FERNANDO MOREIRA",status:"BAIXADO",bankTxId:"bank_fernando",baixadoEm:"2026-08-21"}
  ],
  reconciliations:[{bankTxId:"bank_fernando",lancId:"duplicado"}]
};
const repaired = repairGeneratedStatementDuplicates(data);
document.body.innerHTML = `<pre id="result">${JSON.stringify({repaired,data,financeStateNeedsPersist})}</pre>`;
'''
        output = run_chrome_script(functions + scenario)
        match = re.search(r'<pre id="result">(.*?)</pre>', output)
        self.assertIsNotNone(match, output)
        result = json.loads(html.unescape(match.group(1)))
        self.assertEqual(1, result["repaired"])
        self.assertEqual("original", result["data"]["reconciliations"][0]["lancId"])
        self.assertEqual(["original"], [item["id"] for item in result["data"]["lancamentos"]])
        self.assertEqual("bank_fernando", result["data"]["titulos"][0]["bankTxId"])
        self.assertEqual("CANCELADO", result["data"]["titulos"][1]["status"])
        self.assertIsNone(result["data"]["titulos"][1]["lancId"])
        self.assertTrue(result["financeStateNeedsPersist"])

    def test_criacoes_em_lote_preservam_matches_e_vinculos_existentes(self):
        launch_handler = self.source.split('$("#btnCriarLancDoBanco").addEventListener', 1)[1]
        launch_handler = launch_handler.split("/* ---------- AP/AR", 1)[0]
        self.assertIn("reconciliationSuggestions(contaId, imp)", launch_handler)
        self.assertIn("pendingCandidates.filter(t => !suggestions.has(t.id))", launch_handler)
        self.assertIn("com match foram preservadas", launch_handler)

        title_function = function_source(self.source, "criarTitulosDoOFX", "defaultCompraAiState")
        self.assertIn("state.reconciliations.map(item => item.bankTxId)", title_function)
        self.assertIn("similarTitleForBankTransaction", title_function)
        self.assertIn("skippedLinked", title_function)
        self.assertIn("skippedSimilar", title_function)

    def test_vinculo_de_titulo_nao_pode_roubar_conciliacao(self):
        title_link = function_source(self.source, "vincularBankTxAoTitulo", "detectCodesFromAttachment")
        self.assertIn("existingBankLink", title_link)
        self.assertIn("já está vinculada a outro lançamento", title_link)
        self.assertIn("reconcileBankTransactionWithLancamento", self.source)
        self.assertIn("syncTituloFromLancamento(lanc)", self.source)

    def test_lancamento_aceita_anexo_pdf(self):
        self.assertIn('id="lAnexoFile"', self.markup)
        self.assertIn('id="btnAddLancAnexo"', self.markup)
        self.assertIn("uploadFinanceAttachment", self.source)
        self.assertIn("renderLancAnexos", self.source)

    def test_conciliados_ficam_ocultos_por_padrao(self):
        self.assertIn('id="btnAlternarVinculados"', self.markup)
        self.assertIn("let showReconciledItems = false", self.source)
        self.assertIn("allBankTxs.filter(tx => !reconByBank.has(tx.id))", self.source)
        self.assertIn("Não há lançamentos sem vínculo", self.source)

    def test_acoes_de_titulo_ficam_na_barra_superior(self):
        toolbar_start = self.markup.index('<button class="btn" id="btnSugerir">')
        grid_start = self.markup.index('<div class="grid3">', toolbar_start)
        toolbar = self.markup[toolbar_start:grid_start]
        self.assertIn('id="btnVincularTitulo"', toolbar)
        self.assertIn('id="btnCriarTitulosDoOFX"', toolbar)
        self.assertEqual(1, self.markup.count('id="btnVincularTitulo"'))
        self.assertEqual(1, self.markup.count('id="btnCriarTitulosDoOFX"'))

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome nao instalado")
    def test_valor_e_data_sugerem_match_mesmo_com_nomes_diferentes(self):
        functions = "\n".join(
            (
                function_source(self.source, "reconciliationSuggestions", "pruneReconciliationSuggestions"),
                function_source(self.source, "financialMatchFacts", "scoreMatch"),
                function_source(self.source, "scoreMatch", "normalizeText"),
            )
        )
        scenario = r"""
function parseISODate(value){ return new Date(value + "T00:00:00"); }
function clamp(value, min, max){ return Math.min(max, Math.max(min, value)); }
function normalizeText(value){ return String(value).toLowerCase().replace(/[^a-z0-9\s]/g, " ").trim(); }
function textOverlap(a, b){
  const first = new Set(a.split(" ").filter(word => word.length >= 4));
  const second = new Set(b.split(" ").filter(word => word.length >= 4));
  let matches = 0;
  for(const word of first) if(second.has(word)) matches++;
  return matches;
}
const state = {
  config: {tolDias: 3, tolValor: 0.50, scoreMin: 100},
  reconciliations: [],
  lancamentos: [
    {id: "lanc_40", contaId: "conta", data: "2026-08-12", tipo: "DESPESA", valor: 40, desc: "Almoço da equipe"},
    {id: "lanc_40_20", contaId: "conta", data: "2026-08-12", tipo: "DESPESA", valor: 40.20, desc: "PIX LOJA NOME TOTALMENTE DIFERENTE"}
  ]
};
const imported = {
  txs: [{id: "bank_40", date: "2026-08-12", amount: -40, memo: "PIX LOJA NOME TOTALMENTE DIFERENTE"}]
};
const suggestion = reconciliationSuggestions("conta", imported).get("bank_40");
document.body.textContent = JSON.stringify(suggestion);
"""
        output = run_chrome_script(functions + scenario)
        match = re.search(r"<body>(\{.*\})</body>", output)
        self.assertIsNotNone(match, output)
        suggestion = json.loads(match.group(1))
        self.assertEqual("lanc_40", suggestion["lancId"])
        self.assertEqual("Data + valor", suggestion["reason"])

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome nao instalado")
    def test_data_similar_sugere_valores_diferentes(self):
        functions = "\n".join(
            (
                function_source(self.source, "reconciliationSuggestions", "pruneReconciliationSuggestions"),
                function_source(self.source, "financialMatchFacts", "scoreMatch"),
                function_source(self.source, "scoreMatch", "normalizeText"),
            )
        )
        scenario = r"""
function parseISODate(value){ return new Date(value + "T00:00:00"); }
function clamp(value, min, max){ return Math.min(max, Math.max(min, value)); }
function normalizeText(value){ return String(value).toLowerCase().replace(/[^a-z0-9\s]/g, " ").trim(); }
function textOverlap(){ return 0; }
const state = {
  config: {tolDias: 3, tolValor: 0.01, scoreMin: 100},
  reconciliations: [],
  lancamentos: [{id: "lanc_703", contaId: "conta", data: "2026-08-12", tipo: "DESPESA", valor: 703.50, desc: "Nome diferente"}]
};
const imported = {txs: [{id: "bank_40", date: "2026-08-12", amount: -40, memo: "Sem palavras iguais"}]};
document.body.textContent = JSON.stringify(reconciliationSuggestions("conta", imported).get("bank_40"));
"""
        output = run_chrome_script(functions + scenario)
        match = re.search(r"<body>(\{.*\})</body>", output)
        self.assertIsNotNone(match, output)
        suggestion = json.loads(match.group(1))
        self.assertEqual("lanc_703", suggestion["lancId"])
        self.assertTrue(suggestion["valueMismatch"])
        self.assertEqual("Data similar • valor divergente", suggestion["reason"])

    def test_valor_do_banco_corrige_lancamento_apos_confirmacao(self):
        manual_handler = self.source.split('$("#btnVincular").addEventListener', 1)[1]
        manual_handler = manual_handler.split('$("#btnDesvincular").addEventListener', 1)[0]
        self.assertIn("confirmBankValueCorrections", manual_handler)
        self.assertIn("correctLancamentoFromBank", manual_handler)
        self.assertIn("O valor do banco será considerado correto", self.source)

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome nao instalado")
    def test_javascript_da_tela_permanece_valido(self):
        script = (
            "try { new Function(" + json.dumps(self.source) + "); "
            "document.body.textContent = 'JS_OK'; } "
            "catch (error) { document.body.textContent = 'JS_ERROR:' + error.message; }"
        )
        output = run_chrome_script(script)
        self.assertIsNotNone(re.search(r"<body>JS_OK</body>", output), output)


if __name__ == "__main__":
    unittest.main()
