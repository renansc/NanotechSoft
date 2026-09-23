/* Estimativa da formula para 1000 litros, por produto do estoque. */
const custoProdutoState = { produtos: [], insumos: [], xarope: null, editando: null, carregando: false };

function custoProdutoMoeda(value) {
  return Number(value).toLocaleString('pt-BR', {style: 'currency', currency: 'BRL', minimumFractionDigits: 4, maximumFractionDigits: 6});
}

async function carregarCustoProduto() {
  if (custoProdutoState.editando || custoProdutoState.carregando) return;
  const status = document.getElementById('custoProdutoStatus');
  custoProdutoState.carregando = true;
  status.textContent = 'Carregando produtos e fórmulas…';
  try {
    const resp = await apiFetch('/api/custo-produto');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.erro || 'Não foi possível carregar os produtos.');
    receberCustoProduto(data);
    renderCustoProduto();
    status.textContent = '';
  } catch (error) {
    custoProdutoState.produtos = [];
    renderCustoProduto();
    status.textContent = error.message;
  } finally { custoProdutoState.carregando = false; }
}

function receberCustoProduto(data) {
  custoProdutoState.produtos = data.produtos || [];
  custoProdutoState.insumos = data.insumos || [];
  custoProdutoState.xarope = data.xarope;
}

function renderCustoProduto() {
  const base = custoProdutoState.xarope;
  document.getElementById('custoProdutoBaseResumo').textContent = base?.precificado
    ? `Xarope: ${custoProdutoMoeda(base.custo_litro)}/L · Rendimento da receita: ${gestaoNumero(base.rendimento_litros)} L`
    : base?.valido ? 'Xarope cadastrado; há ingredientes sem preço de compra ou conversão de unidade.' : 'Cadastre a receita e o rendimento do xarope antes das fórmulas dos produtos.';
  const busca = document.getElementById('custoProdutoBusca').value.trim().toLocaleLowerCase('pt-BR');
  const grupo = document.getElementById('custoProdutoGrupo').value;
  const rows = custoProdutoState.produtos.filter(p => (!grupo || p.grupo_estoque.trim().toUpperCase() === grupo)
    && (!busca || p.nome_produto.toLocaleLowerCase('pt-BR').includes(busca)));
  document.getElementById('custoProdutoBody').innerHTML = rows.map(p => `<tr>
    <td>${gestaoEsc(p.nome_produto)}</td><td>${p.grupo_estoque.trim().toUpperCase() === 'PET' ? 'PET' : 'Retornável'}</td>
    <td>${p.volume_ml ? gestaoNumero(p.volume_ml) + ' ml' : 'A informar'}</td>
    <td>${p.calculo ? custoProdutoMoeda(p.calculo.custo_1000_litros) : '—'}</td>
    <td>${p.calculo ? custoProdutoMoeda(p.calculo.custo_unidade) : '—'}</td>
    <td>${gestaoEsc(!p.revisao ? 'Sem fórmula' : p.pendencias?.length ? p.pendencias.join(' ') : p.calculo?.itens_sem_custo ? 'Revisar itens com preço zero' : 'Cadastrada')}</td>
    <td><button type="button" onclick="editarCustoProduto(${Number(p.produto_id)})">${p.revisao ? 'Editar fórmula' : 'Cadastrar fórmula'}</button></td>
  </tr>`).join('') || '<tr><td colspan="7">Nenhum produto PET ou retornável encontrado para este filtro.</td></tr>';
}

function editarCustoProduto(id) {
  if (id === 'xarope' && !custoProdutoState.xarope) return;
  const produto = id === 'xarope' ? {...custoProdutoState.xarope, produto_id: 'xarope', nome_produto: 'Base compartilhada: xarope'} : custoProdutoState.produtos.find(p => p.produto_id === id);
  if (!produto) return;
  custoProdutoState.editando = produto;
  const base = id === 'xarope';
  document.getElementById('custoProdutoDadosGarrafa').classList.toggle('hidden', base);
  document.getElementById('custoProdutoDadosXarope').classList.toggle('hidden', !base);
  document.getElementById('custoProdutoVolume').disabled = base;
  document.getElementById('custoProdutoDose').disabled = base;
  document.getElementById('custoProdutoRendimento').disabled = !base;
  document.getElementById('custoProdutoDose').value = produto.xarope_litros || '';
  document.getElementById('custoProdutoRendimento').value = produto.rendimento_litros || '';
  document.getElementById('custoProdutoItensTitulo').textContent = base ? 'Ingredientes da receita de xarope' : 'Itens específicos do produto (não repita os ingredientes do xarope)';
  document.getElementById('custoProdutoQuantidadeTitulo').textContent = base ? 'Quantidade / receita de xarope' : 'Quantidade / 1.000 L de bebida';
  document.getElementById('custoProdutoLista').classList.add('hidden');
  document.getElementById('custoProdutoEditor').classList.remove('hidden');
  document.getElementById('custoProdutoTitulo').textContent = produto.nome_produto;
  document.getElementById('custoProdutoVolume').value = produto.volume_ml || '';
  document.getElementById('custoProdutoItens').innerHTML = '';
  (produto.itens.length ? produto.itens : base ? [{}] : []).forEach(adicionarItemCustoProduto);
  document.getElementById('custoProdutoMensagem').textContent = '';
  document.getElementById('custoProdutoAtualizacao').textContent = produto.atualizado_em
    ? `Última atualização: ${produto.atualizado_em} · ${produto.atualizado_por}` : 'Nova fórmula';
  atualizarCalculoCustoProduto();
  document.getElementById(base ? 'custoProdutoRendimento' : 'custoProdutoDose').focus();
}

function adicionarItemCustoProduto(item = {}) {
  const body = document.getElementById('custoProdutoItens');
  if (body.children.length >= 100) return;
  const tr = document.createElement('tr');
  const selected = custoProdutoState.insumos.find(p => p.id === Number(item.produto_id));
  const options = custoProdutoState.insumos.map(p => `<option value="${Number(p.id)}" ${p.id === Number(item.produto_id) ? 'selected' : ''}>${gestaoEsc(p.nome_produto)} (#${Number(p.id)})</option>`).join('');
  tr.innerHTML = `<td><select data-custo="produto_id" aria-label="Produto do cadastro" required onchange="selecionarInsumoCusto(this)" style="max-width:320px">
      <option value="">${gestaoEsc(item.nome && !selected ? 'Vincular: ' + item.nome : 'Selecione um produto cadastrado')}</option>${options}</select></td>
    <td><select data-custo="unidade" aria-label="Unidade do item" required onchange="alterarUnidadeCusto(this)"><option value="">Unidade</option>${['kg','g','l','ml','un'].map(u => `<option value="${u}" ${u === (item.unidade || '') ? 'selected' : ''}>${u}</option>`).join('')}</select></td>
    <td><input data-custo="quantidade" aria-label="Quantidade para 1000 litros" type="number" required min="0.000001" max="999999999.999999" step="0.000001" value="${gestaoEsc(item.quantidade ?? '')}"></td>
    <td><input data-custo="fator_compra" aria-label="Quantidade na unidade da fórmula por embalagem comprada" type="number" min="0.000001" max="999999999.999999" step="0.000001" value="${gestaoEsc(item.fator_compra || '')}" oninput="confirmarConversaoCusto(this)">
      <input type="hidden" data-custo="unidade_compra" value="${gestaoEsc(item.unidade_compra || '')}"><small data-custo="conversao"></small></td>
    <td><input data-custo="preco_unitario" aria-label="Preço automático da última compra" type="number" readonly step="any"><small data-custo="origem_preco"></small></td>
    <td data-custo="subtotal">—</td><td><button type="button" aria-label="Remover item" onclick="this.closest('tr').remove(); atualizarCalculoCustoProduto()">Remover</button></td>`;
  body.appendChild(tr);
  atualizarCalculoCustoProduto();
}

function itensCustoProduto() {
  return [...document.querySelectorAll('#custoProdutoItens tr')].map(tr => Object.fromEntries(
    ['produto_id', 'unidade', 'quantidade', 'fator_compra', 'unidade_compra'].map(key => [key, tr.querySelector(`[data-custo="${key}"]`).value])));
}

function selecionarInsumoCusto(select) {
  const product = custoProdutoState.insumos.find(p => p.id === Number(select.value));
  const aliases = {lt:'l', litro:'l', litros:'l', und:'un', unidade:'un', unidades:'un', kgs:'kg'};
  const raw = (product?.unidade || '').toLowerCase().trim();
  const unit = aliases[raw] || raw;
  select.closest('tr').querySelector('[data-custo="unidade"]').value = ['kg','g','l','ml','un'].includes(unit) ? unit : '';
  select.closest('tr').querySelector('[data-custo="fator_compra"]').value = '';
  select.closest('tr').querySelector('[data-custo="unidade_compra"]').value = '';
  atualizarCalculoCustoProduto();
}

function alterarUnidadeCusto(select) {
  select.closest('tr').querySelector('[data-custo="fator_compra"]').value = '';
  select.closest('tr').querySelector('[data-custo="unidade_compra"]').value = '';
  atualizarCalculoCustoProduto();
}

function confirmarConversaoCusto(input) {
  const row = input.closest('tr');
  const product = custoProdutoState.insumos.find(p => p.id === Number(row.querySelector('[data-custo="produto_id"]').value));
  row.querySelector('[data-custo="unidade_compra"]').value = product?.ultima_compra?.unidade_compra || '';
}

function precoCompraCusto(item) {
  const product = custoProdutoState.insumos.find(p => p.id === Number(item.produto_id));
  const compra = product?.ultima_compra;
  if (!compra) return {preco:null, mensagem:'Sem compra de fornecedor vinculada.', automatico:false};
  const units = {KG:['massa',1],G:['massa',.001],T:['massa',1000],L:['volume',1],ML:['volume',.001],M3:['volume',1000],UN:['pecas',1],MIL:['pecas',1000]};
  const origem = units[compra.unidade_compra], destino = units[item.unidade.toUpperCase()];
  let automatico = Boolean(origem && destino && origem[0] === destino[0]);
  let fator = automatico ? origem[1] / destino[1] : item.unidade_compra === compra.unidade_compra ? Number(item.fator_compra) : 0;
  const conversaoEstoque = compra.conversao_estoque;
  const unidadeEstoque = units[conversaoEstoque?.unidade];
  let peloEstoque = false;
  if (!fator && !item.fator_compra && unidadeEstoque && destino && unidadeEstoque[0] === destino[0]) {
    fator = Number(conversaoEstoque.quantidade) * unidadeEstoque[1] / destino[1];
    automatico = true;
    peloEstoque = true;
  }
  const fonte = `XML · NF-e ${compra.nota} · ${compra.data_compra.slice(0,10)} · ${custoProdutoMoeda(compra.preco)}/${compra.unidade_compra}`;
  const mensagem = Number(compra.preco) <= 0 ? 'Última compra sem preço positivo.' : !fator ? `Informe quantos ${item.unidade || 'kg/l/un'} há em 1 ${compra.unidade_compra || 'embalagem'}.` : fonte;
  return {preco: fator > 0 && Number(compra.preco) > 0 ? Number(compra.preco) / fator : null,
    mensagem, automatico, conversao:peloEstoque ? `Cadastro de estoque: ${fator} ${item.unidade}/${compra.unidade_compra}` : automatico ? 'Conversão automática' : `${item.unidade || 'unidade da fórmula'} por ${compra.unidade_compra || 'embalagem'}`,
    detalhe: compra.vinculo ? `${compra.vinculo}: ${compra.codigo_xml || ''} · ${compra.descricao_xml || ''}` : ''};
}

function atualizarCalculoCustoProduto() {
  const baseEditor = custoProdutoState.editando?.produto_id === 'xarope';
  const items = itensCustoProduto();
  const volume = Number(document.getElementById('custoProdutoVolume').value);
  const dose = Number(document.getElementById('custoProdutoDose').value);
  const rendimento = Number(document.getElementById('custoProdutoRendimento').value);
  const base = custoProdutoState.xarope;
  const rows = [...document.querySelectorAll('#custoProdutoItens tr')];
  let total = 0;
  let valido = baseEditor ? items.length > 0 && document.getElementById('custoProdutoRendimento').checkValidity()
    : base?.precificado && document.getElementById('custoProdutoVolume').checkValidity() && document.getElementById('custoProdutoDose').checkValidity();
  items.forEach((item, index) => {
    const row = rows[index];
    const price = precoCompraCusto(item);
    row.querySelector('[data-custo="preco_unitario"]').value = price.preco === null ? '' : price.preco;
    row.querySelector('[data-custo="origem_preco"]').textContent = price.mensagem;
    row.querySelector('[data-custo="origem_preco"]').title = price.detalhe || '';
    row.querySelector('[data-custo="conversao"]').textContent = price.conversao || '';
    row.querySelector('[data-custo="fator_compra"]').disabled = price.automatico;
    const ok = [...row.querySelectorAll('input,select')].every(input => input.checkValidity()) && price.preco !== null;
    const subtotal = Number(item.quantidade) * price.preco;
    row.querySelector('[data-custo="subtotal"]').textContent = ok ? custoProdutoMoeda(subtotal) : '—';
    valido = valido && ok;
    total += subtotal;
  });
  const status = document.getElementById('custoProdutoCalculo');
  if (!valido) {
    status.textContent = !baseEditor && !base?.valido ? 'Cadastre ou revise a base de xarope para calcular o produto.' : 'Preencha a fórmula e resolva os preços de compra ou conversões pendentes para calcular.';
  } else if (baseEditor) {
    status.textContent = `Receita de xarope: ${custoProdutoMoeda(total)} · Por litro de xarope: ${custoProdutoMoeda(total / rendimento)}`;
  } else {
    const custoBase = base.itens.reduce((sum,i) => sum + Number(i.quantidade) * Number(i.preco_unitario), 0) / base.rendimento_litros * dose;
    const completo = total + custoBase;
    status.textContent = `Xarope (${gestaoNumero(dose)} L): ${custoProdutoMoeda(custoBase)} · Itens específicos: ${custoProdutoMoeda(total)} · 1.000 litros: ${custoProdutoMoeda(completo)} · Por litro: ${custoProdutoMoeda(completo / 1000)} · Por garrafa: ${custoProdutoMoeda(completo * volume / 1000000)}`;
  }
  document.getElementById('custoProdutoAviso').textContent = 'Preços consultados nos XMLs de entrada, usando o vínculo com o cadastro de estoque. O servidor recalcula com a última compra ao salvar.';
}

async function salvarCustoProduto(event) {
  event.preventDefault();
  const produto = custoProdutoState.editando;
  if (!produto) return;
  const fields = document.getElementById('custoProdutoCampos');
  const status = document.getElementById('custoProdutoMensagem');
  const payload = {volume_ml: document.getElementById('custoProdutoVolume').value,
    itens: itensCustoProduto(), revisao: produto.revisao,
    rendimento_litros: document.getElementById('custoProdutoRendimento').value,
    xarope_litros: document.getElementById('custoProdutoDose').value, xarope_revisao: custoProdutoState.xarope?.revisao};
  fields.disabled = true;
  status.textContent = 'Salvando fórmula…';
  try {
    const resp = await apiFetch(`/api/custo-produto/${produto.produto_id}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.erro || 'Não foi possível salvar a fórmula.');
    if (produto.produto_id === 'xarope') receberCustoProduto(data);
    else custoProdutoState.produtos = custoProdutoState.produtos.map(p => p.produto_id === data.produto_id ? data : p);
    custoProdutoState.editando = null;
    document.getElementById('custoProdutoEditor').classList.add('hidden');
    document.getElementById('custoProdutoLista').classList.remove('hidden');
    renderCustoProduto();
    document.getElementById('custoProdutoStatus').textContent = produto.produto_id === 'xarope' ? 'Xarope salvo. Custos de todos os produtos recalculados.' : 'Fórmula salva. Estimativa recalculada.';
  } catch (error) { status.textContent = error.message; }
  finally { fields.disabled = false; }
}

function cancelarCustoProduto() {
  custoProdutoState.editando = null;
  document.getElementById('custoProdutoEditor').classList.add('hidden');
  document.getElementById('custoProdutoLista').classList.remove('hidden');
  carregarCustoProduto();
}

const custoDashboardState = {data:null, request:0};

async function carregarDashboardCustoProduto() {
  const year = document.getElementById('custoDashboardAno');
  if (!year.options.length) {
    const atual = new Date().getFullYear();
    year.innerHTML = Array.from({length:atual-1999},(_,i)=>`<option value="${atual-i}">${atual-i}</option>`).join('');
  }
  const status = document.getElementById('custoDashboardStatus');
  const requestId = ++custoDashboardState.request;
  status.textContent = 'Consultando custos e compras…';
  try {
    const response = await apiFetch(`/api/custo-produto/dashboard?ano=${year.value}`);
    const data = await response.json();
    if (requestId !== custoDashboardState.request) return;
    if (!response.ok) throw new Error(data.erro || 'Não foi possível consultar os custos.');
    custoDashboardState.data = data;
    const select = document.getElementById('custoDashboardProduto');
    const previous = select.value;
    select.innerHTML = '<option value="">Todos os produtos</option>' + data.produtos.map(p=>`<option value="${p.produto_id}">${gestaoEsc(p.nome_produto)}</option>`).join('');
    select.value = previous;
    renderDashboardCustoProduto();
    status.textContent = `Custo atual em ${data.data_referencia}. Valores por garrafa; meses sem referência completa ficam pendentes.`;
  } catch(error) {
    if (requestId !== custoDashboardState.request) return;
    custoDashboardState.data = null;
    document.getElementById('custoDashboardBody').innerHTML = '';
    document.getElementById('custoDashboardResumo').textContent = '';
    document.getElementById('custoDashboardGrafico').innerHTML = '';
    status.textContent = error.message;
  }
}

function renderDashboardCustoProduto() {
  const data = custoDashboardState.data;
  if (!data) return;
  const group = document.getElementById('custoDashboardGrupo').value;
  const id = Number(document.getElementById('custoDashboardProduto').value);
  const rows = data.produtos.filter(p=>(!group || p.grupo_estoque.trim().toUpperCase()===group) && (!id || p.produto_id===id));
  const priced = rows.filter(p=>p.atual).length;
  document.getElementById('custoDashboardResumo').textContent = `${rows.length} produtos · ${priced} com custo atual calculado · ${rows.length-priced} pendentes`;
  document.getElementById('custoDashboardHead').innerHTML = '<tr><th>Produto / sabor</th><th>Volume</th><th>Custo atual / garrafa</th>' + data.meses.map(m=>`<th>${m.slice(5)}/${m.slice(0,4)}</th>`).join('') + '<th>Pendências atuais</th></tr>';
  document.getElementById('custoDashboardBody').innerHTML = rows.map(p=>`<tr><td>${gestaoEsc(p.nome_produto)}</td><td>${gestaoNumero(p.volume_ml)} ml</td><td>${p.atual ? custoProdutoMoeda(p.atual.custo_unidade) : 'Pendente'}</td>${p.mensal.map(m=>`<td title="${gestaoEsc(m.pendencias.join(' '))}">${m.calculo ? custoProdutoMoeda(m.calculo.custo_unidade) : '—'}</td>`).join('')}<td>${gestaoEsc(p.atual ? '' : p.pendencias.join(' ') || 'Cadastre a fórmula do produto.')}</td></tr>`).join('') || `<tr><td colspan="${data.meses.length+4}">Nenhum produto para este filtro.</td></tr>`;
  const chart = document.getElementById('custoDashboardGrafico');
  if (!id || !rows.length) {
    chart.textContent = 'Selecione um produto para visualizar o gráfico mensal.';
    return;
  }
  const product = rows[0];
  const maximum = Math.max(...product.mensal.map(m=>m.calculo?.custo_unidade || 0), .000001);
  const width = Math.max(660,product.mensal.length*88);
  const bars = product.mensal.map((m,i)=>{
    const value = m.calculo?.custo_unidade;
    const x = 20 + i*(width-40)/product.mensal.length;
    const h = value == null ? 0 : value/maximum*150;
    return `<g><title>${m.mes}: ${value == null ? 'Pendente' : gestaoEsc(custoProdutoMoeda(value))}</title><rect x="${x}" y="${185-h}" width="45" height="${h}" fill="currentColor" rx="3"/><text x="${x+22}" y="${175-h}" text-anchor="middle" fill="currentColor" font-size="11">${value == null ? '—' : Number(value).toLocaleString('pt-BR',{maximumFractionDigits:4})}</text><text x="${x+22}" y="205" text-anchor="middle" fill="currentColor" font-size="12">${m.mes.slice(5)}</text></g>`;
  }).join('');
  chart.innerHTML = `<p>${gestaoEsc(product.nome_produto)} · R$ por garrafa</p><div style="overflow-x:auto"><svg role="img" aria-label="Custo mensal por garrafa; valores também disponíveis na tabela" viewBox="0 0 ${width} 220" style="min-width:${width}px;width:100%;max-height:260px">${bars}</svg></div>`;
}
