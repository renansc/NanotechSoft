import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest import mock

try:
    import app as portal
    HAS_FLASK = True
except ModuleNotFoundError:
    portal = None
    HAS_FLASK = False


PROJECT_DIR = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_DIR / "apps" / "financeiro" / "static" / "app.js"


def function_source(source, name, next_name):
    start = source.index(f"function {name}")
    end = source.index(f"function {next_name}", start)
    return source[start:end]


class FinanceiroDashboardTests(unittest.TestCase):
    def test_dashboard_possui_sincronizacao_continua(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('new BroadcastChannel("nanotechsoft-financeiro-state")', source)
        self.assertIn("FINANCE_SYNC_INTERVAL_MS = 3000", source)
        self.assertIn("syncFinanceStateFromServer", source)
        self.assertIn("startFinanceRealtimeSync();", source)

    def test_contas_filtradas_exibem_quantidade_e_soma_dos_valores(self):
        source = APP_JS.read_text(encoding="utf-8")
        markup = (PROJECT_DIR / "apps/financeiro/source.html").read_text(encoding="utf-8")

        for element_id in (
            'id="apTotalQuantidade"',
            'id="apTotalFiltrado"',
            'id="arTotalQuantidade"',
            'id="arTotalFiltrado"',
        ):
            self.assertIn(element_id, markup)
        renderer = function_source(source, "renderTabelaTitulos", "installmentFileSignature")
        self.assertIn("list.reduce", renderer)
        self.assertIn("Number.isFinite(valor)", renderer)
        self.assertIn("totalEl.textContent = brl(totalFiltrado)", renderer)

    def test_sincronizacao_nao_reaplica_resposta_anterior_a_gravacao(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("const requestedRevision = financeStateRevision", source)
        self.assertIn("financeStateRevision !== requestedRevision", source)
        self.assertIn("financeSyncPending = true", source)
        self.assertIn("JSON.stringify({ state, revision: financeStateRevision })", source)

    def test_dashboard_calcula_saldo_sem_sobrescrever_pelo_extrato(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function latestStatementBalance", source)
        calculator = function_source(source, "calcContaFinanceStatus", "aggregateFinanceStatus")
        self.assertIn("status.saldoAtual = Number(conta.saldoInicial || 0)", calculator)
        self.assertNotIn("closingBalance", calculator)
        self.assertIn("dataMovimento >= saldoInicialEm", calculator)
        self.assertIn("applyStatementBalanceMetadata", source)
        self.assertIn("buildAccountBalanceAudit", source)
        audit = function_source(source, "buildAccountBalanceAudit", "isTituloAberto")
        self.assertIn("const isInsideAuditPeriod", audit)
        self.assertIn("!initialDate || value >= initialDate", audit)
        self.assertNotIn("lanc.data > statement.balanceDate", audit)
        self.assertIn("Saldo confere com o banco", source)
        self.assertIn("Lançamentos que precisam de revisão", source)
        self.assertIn("provavelmente já está incluído no saldo inicial", source)
        self.assertIn("reconciledBankTransactionsByLancamento", source)
        self.assertIn("const dataMovimento = bankTx?.date || lanc.data", source)

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome nao instalado")
    def test_saldo_conciliado_usa_data_e_valor_do_banco(self):
        source = APP_JS.read_text(encoding="utf-8")
        calculator = "\n".join(
            (
                function_source(source, "toISODate", "formatDateTime"),
                function_source(source, "isValidDateISO", "isSameMonthISO"),
                function_source(source, "isSameMonthISO", "isTituloAberto"),
                function_source(source, "isTituloAberto", "selectedContaIds"),
                function_source(source, "emptyFinanceStatus", "finishFinanceStatus"),
                function_source(source, "finishFinanceStatus", "calcContaFinanceStatus"),
                function_source(source, "calcContaFinanceStatus", "aggregateFinanceStatus"),
            )
        )
        scenario = r"""
function isTransferenciaLancamento(lancamento){ return !!lancamento?.transferenciaId; }
const state = {
  contas: [{id: "caixa", saldoInicial: -2204.51, saldoInicialEm: "2026-07-02"}],
  imports: [
    {
      id: "julho", contaId: "caixa", createdAt: "2026-08-13 08:00:00",
      closingBalance: -877.29, balanceDate: "2026-07-27",
      txs: [
        {id: "bank_referencia", date: "2026-07-02", amount: -18.20},
        {id: "bank_julho", date: "2026-07-22", amount: 1327.22}
      ]
    },
    {
      id: "agosto", contaId: "caixa", createdAt: "2026-08-13 08:01:00",
      txs: [{id: "bank_agosto", date: "2026-08-12", amount: -1138.29}]
    }
  ],
  reconciliations: [
    {bankTxId: "bank_referencia", lancId: "lanc_referencia"},
    {bankTxId: "bank_julho", lancId: "lanc_julho"},
    {bankTxId: "bank_agosto", lancId: "lanc_agosto"}
  ],
  lancamentos: [
    {id: "lanc_referencia", contaId: "caixa", data: "2026-08-12", tipo: "DESPESA", valor: 9999},
    {id: "lanc_julho", contaId: "caixa", data: "2026-08-12", tipo: "RECEITA", valor: 9999},
    {id: "lanc_agosto", contaId: "caixa", data: "2026-08-12", tipo: "DESPESA", valor: 9999}
  ],
  titulos: []
};
document.body.textContent = JSON.stringify(calcContaFinanceStatus("caixa", "2026-08", "2026-08-13"));
"""
        page = f"<body><script>{calculator}\n{scenario}</script></body>"
        result = subprocess.run(
            [
                shutil.which("google-chrome"), "--headless", "--no-sandbox",
                "--disable-gpu", "--disable-dev-shm-usage", "--dump-dom",
                "data:text/html;charset=utf-8," + quote(page),
            ],
            check=True, capture_output=True, text=True, timeout=30,
        )
        match = re.search(r"<body>(\{.*\})</body>", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        values = json.loads(match.group(1))
        self.assertAlmostEqual(-2033.78, values["saldoAtual"], places=2)
        self.assertAlmostEqual(1138.29, values["despesasMes"], places=2)

    @unittest.skipUnless(HAS_FLASK, "Flask nao instalado")
    def test_api_rejeita_gravacao_de_aba_desatualizada(self):
        user = {"id": 1, "perfil": "admin", "ativo": 1}
        current_state = portal.default_finance_state()
        current_revision = portal.finance_state_revision(current_state)
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["usuario_id"] = 1

        with (
            mock.patch.object(portal, "current_user_or_logout", return_value=user),
            mock.patch.object(portal, "app_visible_to_user", return_value=True),
            mock.patch.object(portal, "get_finance_state", return_value=current_state),
            mock.patch.object(portal, "save_finance_state") as save_state,
        ):
            response = client.put(
                "/apps/financeiro/api/state",
                json={"revision": "revisao-antiga", "state": current_state},
            )

        self.assertEqual(409, response.status_code)
        self.assertEqual(current_revision, response.get_json()["currentRevision"])
        save_state.assert_not_called()

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome nao instalado")
    def test_saldo_atual_acumula_movimentos_de_todos_os_meses(self):
        source = APP_JS.read_text(encoding="utf-8")
        calculator = "\n".join(
            (
                function_source(source, "toISODate", "formatDateTime"),
                function_source(source, "isValidDateISO", "isSameMonthISO"),
                function_source(source, "isSameMonthISO", "isTituloAberto"),
                function_source(source, "isTituloAberto", "selectedContaIds"),
                function_source(source, "emptyFinanceStatus", "finishFinanceStatus"),
                function_source(source, "finishFinanceStatus", "calcContaFinanceStatus"),
                function_source(source, "calcContaFinanceStatus", "aggregateFinanceStatus"),
            )
        )
        scenario = r"""
function isTransferenciaLancamento(lancamento){ return !!lancamento?.transferenciaId; }
const state = {
  contas: [
    {id: "principal", saldoInicial: 1000},
    {id: "outra", saldoInicial: 0},
    {id: "conta_inter_19f230a596c", saldoInicial: 0.37}
  ],
  lancamentos: [
    {contaId: "principal", data: "2026-06-10", tipo: "RECEITA", valor: 300},
    {contaId: "principal", data: "2026-07-05", tipo: "DESPESA", valor: 125},
    {contaId: "principal", data: "2026-08-02", tipo: "RECEITA", valor: 50},
    {contaId: "principal", data: "2026-08-20", tipo: "DESPESA", valor: 25},
    {contaId: "conta_inter_19f230a596c", data: "2026-04-14", tipo: "DESPESA", valor: 350},
    {contaId: "conta_inter_19f230a596c", data: "2026-05-15", tipo: "DESPESA", valor: 350},
    {contaId: "conta_inter_19f230a596c", data: "2026-06-09", tipo: "DESPESA", valor: 350},
    {contaId: "conta_inter_19f230a596c", data: "2026-07-07", tipo: "DESPESA", valor: 0.08},
    {contaId: "conta_inter_19f230a596c", data: "2026-08-12", tipo: "RECEITA", valor: 1644.51}
  ],
  titulos: []
};
const june = calcContaFinanceStatus("principal", "2026-06", "2026-08-12");
const august = calcContaFinanceStatus("principal", "2026-08", "2026-08-12");
state.lancamentos[0].contaId = "outra";
const principalDepoisDaTroca = calcContaFinanceStatus("principal", "2026-08", "2026-08-12");
const outraDepoisDaTroca = calcContaFinanceStatus("outra", "2026-08", "2026-08-12");
const interPj = calcContaFinanceStatus("conta_inter_19f230a596c", "2026-08", "2026-08-12");
document.body.textContent = JSON.stringify({
  juneSaldo: june.saldoAtual,
  augustSaldo: august.saldoAtual,
  juneReceitas: june.receitasMes,
  augustReceitas: august.receitasMes,
  augustFuturo: august.despesasFuturas,
  principalDepoisDaTroca: principalDepoisDaTroca.saldoAtual,
  outraDepoisDaTroca: outraDepoisDaTroca.saldoAtual,
  interPjSaldo: interPj.saldoAtual,
  interPjResultadoAgosto: interPj.resultadoRealizadoMes
});
"""
        page = f"<body><script>{calculator}\n{scenario}</script></body>"
        result = subprocess.run(
            [
                shutil.which("google-chrome"),
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--dump-dom",
                "data:text/html;charset=utf-8," + quote(page),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        match = re.search(r"<body>(\{.*\})</body>", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        values = json.loads(match.group(1))

        self.assertEqual(1225, values["juneSaldo"])
        self.assertEqual(values["juneSaldo"], values["augustSaldo"])
        self.assertEqual(300, values["juneReceitas"])
        self.assertEqual(50, values["augustReceitas"])
        self.assertEqual(25, values["augustFuturo"])
        self.assertEqual(925, values["principalDepoisDaTroca"])
        self.assertEqual(300, values["outraDepoisDaTroca"])
        self.assertAlmostEqual(1644.80, values["interPjSaldo"], places=2)
        self.assertAlmostEqual(1644.51, values["interPjResultadoAgosto"], places=2)


if __name__ == "__main__":
    unittest.main()
