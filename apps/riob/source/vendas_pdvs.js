const pdvsTotais = {vendedores: [], totais: [], arquivo: null, ocupada: false};
const pdvsCodigo = key => String(key).split('-')[0].trim().replace(/^0+/, '') || String(key);
const pdvsEl = id => document.getElementById(id);
async function pdvsApi(suffix = '', options) {
  const response = await apiFetch('/api/vendas/pdvs-totais' + suffix, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.erro || 'Não foi possível consultar os totais.');
  return data;
}
function pdvsOcupada(value) {
  pdvsTotais.ocupada = value;
  pdvsEl('pdvsTotais').querySelectorAll('button,input,select').forEach(el => el.disabled = value);
}
async function abrirPdvsTotais() {
  showTab('pdvsTotais');
  if (pdvsTotais.ocupada) return;
  pdvsLimparConferencia();
  pdvsOcupada(true);
  try {
    const data = await pdvsApi();
    pdvsTotais.vendedores = data.vendedores || [];
    pdvsTotais.totais = data.totais || [];
    pdvsRenderAtuais();
    pdvsEl('pdvsStatus').textContent = '';
  } catch (err) { pdvsEl('pdvsStatus').textContent = err.message; }
  finally { pdvsOcupada(false); }
}
function pdvsRenderAtuais() {
  pdvsEl('pdvsAtuais').innerHTML = pdvsTotais.totais.length ? pdvsTotais.totais.map(item => `<tr>
    <td>${_escHtml(item.vendedor_key)}</td><td>${_escHtml(_fmtNumVendas(item.total))}</td>
    <td>${_escHtml(item.atualizado_em ? new Date(item.atualizado_em).toLocaleString('pt-BR') : '')}</td></tr>`).join('') : '<tr><td colspan="3">Nenhum total importado.</td></tr>';
}
function pdvsLinha(item = {}) {
  const row = document.createElement('tr');
  row.innerHTML = `<td><select aria-label="Vendedor"><option value="">Selecione</option>${pdvsTotais.vendedores.map(v => `<option value="${_escHtml(v.chave)}">${_escHtml(v.chave)}</option>`).join('')}</select></td>
    <td class="pdvs-anterior"></td><td><input aria-label="Total de PDVs" type="number" min="0" max="10000000" step="1" required></td>
    <td>${_escHtml(item.com_compra_pdf == null ? '—' : _fmtNumVendas(item.com_compra_pdf))}</td>
    <td><button type="button" class="btn-secondary">Remover</button></td>`;
  row.querySelector('select').value = item.vendedor_key || '';
  row.querySelector('input').value = item.total ?? '';
  const update = () => { const old = pdvsTotais.totais.find(t => pdvsCodigo(t.vendedor_key) === pdvsCodigo(row.querySelector('select').value));
    row.querySelector('.pdvs-anterior').textContent = old ? _fmtNumVendas(old.total) : 'Não cadastrado'; };
  row.querySelector('select').onchange = update;
  row.querySelector('button').onclick = () => row.remove();
  update(); pdvsEl('pdvsConferenciaBody').appendChild(row);
}
function pdvsLimparConferencia() {
  pdvsTotais.arquivo = null;
  pdvsEl('pdvsConferencia').classList.add('hidden');
  pdvsEl('pdvsConferenciaBody').replaceChildren();
}
async function conferirPdfPdvs() {
  if (pdvsTotais.ocupada) return;
  const file = pdvsEl('pdvsArquivo').files[0];
  pdvsLimparConferencia();
  if (!file) { pdvsEl('pdvsStatus').textContent = 'Selecione o PDF.'; return; }
  if (file.size > 10 * 1024 * 1024) { pdvsEl('pdvsStatus').textContent = 'Limite de 10 MB.'; return; }
  pdvsOcupada(true); pdvsEl('pdvsStatus').textContent = 'Lendo o PDF…';
  try {
    const form = new FormData(); form.append('arquivo', file);
    const data = await pdvsApi('/conferir', {method: 'POST', body: form});
    pdvsTotais.arquivo = file; pdvsTotais.vendedores = data.vendedores; pdvsTotais.totais = data.totais;
    pdvsRenderAtuais(); data.itens.forEach(pdvsLinha);
    pdvsEl('pdvsTexto').textContent = data.texto;
    pdvsEl('pdvsConferencia').classList.remove('hidden');
    pdvsEl('pdvsStatus').textContent = `${data.itens.length} vendedores identificados. Confira os totais antes de salvar.`;
  } catch (err) { pdvsEl('pdvsStatus').textContent = err.message; }
  finally { pdvsOcupada(false); }
}
async function salvarPdfPdvs(event) {
  event.preventDefault();
  if (pdvsTotais.ocupada || !pdvsTotais.arquivo) return;
  const itens = Array.from(pdvsEl('pdvsConferenciaBody').rows).map(row => ({
    vendedor_key: row.querySelector('select').value, total: row.querySelector('input').value}));
  if (!itens.length) { pdvsEl('pdvsStatus').textContent = 'Mantenha ao menos um vendedor.'; return; }
  const form = new FormData(); form.append('arquivo', pdvsTotais.arquivo);
  form.append('itens', JSON.stringify(itens));
  form.append('anteriores', JSON.stringify(Object.fromEntries(pdvsTotais.totais.map(t => [t.vendedor_key, t.importacao_id]))));
  pdvsOcupada(true);
  try {
    const data = await pdvsApi('', {method: 'POST', body: form});
    pdvsLimparConferencia(); pdvsEl('pdvsArquivo').value = '';
    const atual = await pdvsApi(); pdvsTotais.totais = atual.totais; pdvsRenderAtuais();
    pdvsEl('pdvsStatus').textContent = `${data.atualizados} totais atualizados. O relatório já usa a nova carteira.`;
  } catch (err) { pdvsEl('pdvsStatus').textContent = err.message; }
  finally { pdvsOcupada(false); }
}
