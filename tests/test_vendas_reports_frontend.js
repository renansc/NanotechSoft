const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('apps/riob/source/script.js', 'utf8');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

async function testMonths() {
  let calls = 0;
  let now = 1000;
  let response = deferred();
  const controls = {a: {value: ''}, b: {value: '2025-12'}};
  const context = vm.createContext({
    Date: {now: () => now}, document: {getElementById: id => controls[id]},
    apiFetch: () => { calls++; return response.promise; },
    _vendasPreencherSelectMeses: (_months, selected, id) => { controls[id].value = selected; },
  });
  vm.runInContext(source.slice(source.indexOf('let vendasMesesConsulta ='),
    source.indexOf('async function carregarDashboardBonificacoes')), context);
  const a = context._vendasCarregarMeses('a');
  const b = context._vendasCarregarMeses('b');
  assert.equal(calls, 1, 'chamadas concorrentes compartilham a consulta');
  response.resolve({ok: true, json: async () => ({mes_atual: '2026-09', meses_disponiveis: ['2025-12', '2026-09']})});
  assert.deepEqual(await Promise.all([a, b]), ['2026-09', '2025-12']);
  await context._vendasCarregarMeses('a');
  assert.equal(calls, 1);
  now += 60001;
  response = deferred();
  const failed = context._vendasCarregarMeses('a');
  response.resolve({ok: false, json: async () => ({erro: 'indisponivel'})});
  await assert.rejects(failed, /indisponivel/);
  response = deferred();
  const retry = context._vendasCarregarMeses('a');
  response.resolve({ok: true, json: async () => ({mes_atual: '2026-10', meses_disponiveis: ['2026-10']})});
  await retry;
  assert.equal(calls, 3, 'falha nao fica armazenada');
  vm.runInContext('vendasMesesConsulta = null', context);
  await context._vendasCarregarMeses('a');
  assert.equal(calls, 4, 'troca/importacao da base invalida a lista');
}

async function testLastFilterWins(name, nextName) {
  const pending = [];
  const rendered = [];
  const controls = {};
  const context = vm.createContext({
    URLSearchParams, vendasState: {},
    document: {getElementById: id => controls[id] || (controls[id] = {value: ''})},
    _vendasCarregarMeses: async () => {},
    apiFetch: () => { const item = deferred(); pending.push(item); return item.promise; },
    renderRelatorioVendas: data => rendered.push(data.id),
    _vendasRenderComparativoAnual: data => rendered.push(data.id),
    _vendasAtualizarInfoAnual: () => {}, alert: () => { throw Error('erro inesperado'); },
  });
  vm.runInContext(source.slice(source.indexOf(`async function ${name}(`),
    source.indexOf(`function ${nextName}(`)), context);
  const first = context[name]();
  await new Promise(resolve => setImmediate(resolve));
  const second = context[name]();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(pending.length, 2);
  pending[1].resolve({ok: true, json: async () => ({id: 'atual'})});
  await second;
  pending[0].resolve({ok: true, json: async () => ({id: 'anterior'})});
  await first;
  assert.deepEqual(rendered, ['atual']);
}

(async () => {
  await testMonths();
  await testLastFilterWins('carregarRelatorioVendas', 'renderRelatorioPrecoMedioVendas');
  await testLastFilterWins('carregarRelatorioVendasAnual', 'limparFiltrosRelatorioVendasAnual');
  console.log('OK: meses compartilhados, expiracao, falhas, invalidacao e ordem de respostas mensal/anual');
})().catch(error => { console.error(error); process.exitCode = 1; });
