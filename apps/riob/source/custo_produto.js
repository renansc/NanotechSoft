/* Estimativa da formula para 1000 litros, por produto do estoque. */
const custoProdutoState = { produtos: [], insumos: [], xarope: null, xaropesCompostos: [], rateio: null, editando: null, carregando: false };

function custoProdutoMoeda(value) {
  return Number(value).toLocaleString('pt-BR', {style: 'currency', currency: 'BRL', minimumFractionDigits: 4, maximumFractionDigits: 6});
}

function custoProdutoFaixaPreforma(produto) {
  const texto = String(produto?.nome_produto || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
  if (!texto.includes('PREFORMA')) return '';
  const peso = Number((texto.match(/\b(\d{2}(?:[.,]\d+)?)\s*(?:G|GR)\b/)?.[1] || '').replace(',', '.'));
  if ((peso >= 40 && peso < 50) || /\b2\s*L(?:ITROS?)?\b/.test(texto)) return 'Faixa 40 · PET 2 L';
  if ((peso >= 20 && peso < 30) || /\b600\s*ML\b/.test(texto)) return 'Faixa 20 · PET 600 ml';
  if ((peso >= 14 && peso < 20) || /\b200\s*ML\b/.test(texto)) return 'Faixa 15 · PET 200 ml';
  return '';
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
  custoProdutoState.xaropesCompostos = data.xaropes_compostos || [];
  custoProdutoState.rateio = data.rateio || null;
}

function renderCustoProduto() {
  const base = custoProdutoState.xarope;
  document.getElementById('custoProdutoBaseResumo').textContent = base?.precificado
    ? `Xarope base: ${custoProdutoMoeda(base.custo_litro)}/L · Rendimento da receita: ${gestaoNumero(base.rendimento_litros)} L`
    : base?.valido ? 'Xarope base cadastrado; há ingredientes sem preço de compra ou conversão de unidade.' : 'Cadastre a receita e o rendimento do xarope base antes dos compostos por sabor.';
  document.getElementById('custoProdutoCompostosBody').innerHTML = custoProdutoState.xaropesCompostos.map(x => `<tr>
    <td>${gestaoEsc(x.nome)}</td><td>${gestaoNumero(x.xarope_base_litros)} L</td><td>${gestaoNumero(x.rendimento_bebida_litros || x.rendimento_litros)} L</td><td>${gestaoNumero(x.xarope_base_litros_1000)} L</td>
    <td>${x.precificado ? custoProdutoMoeda(x.custo_litro) : '—'}</td>
    <td>${gestaoEsc(x.pendencias?.length ? x.pendencias.join(' ') : 'Cadastrado')}</td>
    <td><button type="button" onclick="editarCustoProduto('composto-${Number(x.id)}')">Editar composto</button></td>
  </tr>`).join('') || '<tr><td colspan="7">Nenhum xarope composto por sabor cadastrado.</td></tr>';
  const busca = document.getElementById('custoProdutoBusca').value.trim().toLocaleLowerCase('pt-BR');
  const grupo = document.getElementById('custoProdutoGrupo').value;
  const mostrarExcluidos = document.getElementById('custoProdutoMostrarExcluidos').checked;
  const rows = custoProdutoState.produtos.filter(p => (mostrarExcluidos || !p.excluido_custo)
    && (!grupo || p.grupo_estoque.trim().toUpperCase() === grupo)
    && (!busca || p.nome_produto.toLocaleLowerCase('pt-BR').includes(busca)));
  const linha = p => ({AGUA:'Água',PET:'PET',GFA:'Retornável'}[p.grupo_estoque.trim().toUpperCase()] || p.grupo_estoque);
  document.getElementById('custoProdutoBody').innerHTML = rows.map(p => `<tr>
    <td>${gestaoEsc(p.nome_produto)}</td><td>${linha(p)}</td><td>${gestaoEsc(p.usa_xarope ? (p.xarope_composto_nome || 'Não selecionado') : 'Sem xarope')}</td>
    <td>${p.volume_ml ? gestaoNumero(p.volume_ml) + ' ml' : 'A informar'}</td>
    <td>${p.calculo ? custoProdutoMoeda(p.calculo.custo_unidade_sem_rateio) : '—'}</td>
    <td>${p.calculo ? custoProdutoMoeda(p.calculo.custo_unidade) : '—'}</td>
    <td>${p.unidades_pacote ? gestaoNumero(p.unidades_pacote) : 'A informar'}</td>
    <td>${p.calculo?.custo_pacote_sem_rateio != null ? custoProdutoMoeda(p.calculo.custo_pacote_sem_rateio) : '—'}</td>
    <td>${p.calculo?.custo_pacote != null ? custoProdutoMoeda(p.calculo.custo_pacote) : '—'}</td>
    <td>${gestaoEsc(p.excluido_custo ? 'Fora da lista de produção' : !p.revisao ? 'Sem fórmula' : p.pendencias?.length ? p.pendencias.join(' ') : !p.unidades_pacote ? 'Informe as unidades por pacote.' : p.calculo?.itens_sem_custo ? 'Revisar itens com preço zero' : 'Cadastrada')}</td>
    <td>${p.excluido_custo
      ? `<button type="button" onclick="restaurarProdutoCusto(${Number(p.produto_id)})">Restaurar na lista</button>`
      : `<button type="button" onclick="editarCustoProduto(${Number(p.produto_id)})">${p.revisao ? 'Editar fórmula' : 'Cadastrar fórmula'}</button>${p.revisao ? ` <button type="button" class="btn-danger" onclick="excluirCustoProduto(${Number(p.produto_id)})">Excluir fórmula</button>` : ''}${p.sugestao_formula ? ` <button type="button" class="btn-secondary" onclick="editarCustoProduto(${Number(p.produto_id)}, true)">Autocompletar pelo mesmo sabor</button>` : ''} <button type="button" class="btn-danger" onclick="removerProdutoCusto(${Number(p.produto_id)})">Remover da lista</button>`}</td>
  </tr>`).join('') || '<tr><td colspan="11">Nenhum produto de água, PET ou retornável encontrado para este filtro.</td></tr>';
}

async function removerProdutoCusto(id) {
  const produto = custoProdutoState.produtos.find(item => item.produto_id === id);
  if (!produto || produto.excluido_custo) return;
  const confirmado = confirm(`Remover "${produto.nome_produto}" da lista de custo de produção?\n\nO cadastro do produto, estoque, fórmula e referências de NF-e/SPED serão preservados. O item também sairá do dashboard de custos e poderá ser restaurado depois.`);
  if (!confirmado) return;
  await alterarVisibilidadeProdutoCusto(produto, false);
}

async function restaurarProdutoCusto(id) {
  const produto = custoProdutoState.produtos.find(item => item.produto_id === id);
  if (!produto?.excluido_custo) return;
  await alterarVisibilidadeProdutoCusto(produto, true);
}

async function alterarVisibilidadeProdutoCusto(produto, restaurar) {
  const status = document.getElementById('custoProdutoStatus');
  status.textContent = restaurar ? 'Restaurando produto na lista…' : 'Removendo produto da lista…';
  try {
    const response = await apiFetch(`/api/custo-produto/produtos/${produto.produto_id}${restaurar ? '/restaurar' : ''}`, {
      method: restaurar ? 'POST' : 'DELETE'
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.erro || 'Não foi possível alterar a lista de produção.');
    custoDashboardState.data = null;
    await carregarCustoProduto();
    status.textContent = restaurar
      ? 'Produto restaurado na lista de custo de produção.'
      : 'Produto removido da lista de produção. Cadastro, estoque, fórmula e dados fiscais foram mantidos.';
  } catch (error) { status.textContent = error.message; }
}

async function excluirCustoProduto(id) {
  const produto = custoProdutoState.produtos.find(item => item.produto_id === id);
  if (!produto?.revisao) return;
  const confirmado = confirm(`Excluir somente a fórmula de "${produto.nome_produto}"?\n\nO produto, o estoque e as referências de NF-e/SPED serão mantidos. O item voltará para "Sem fórmula" e poderá ser cadastrado novamente no futuro.`);
  if (!confirmado) return;
  const status = document.getElementById('custoProdutoStatus');
  status.textContent = 'Excluindo fórmula…';
  try {
    const response = await apiFetch(`/api/custo-produto/${produto.produto_id}`, {
      method: 'DELETE', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({revisao: produto.revisao})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.erro || 'Não foi possível excluir a fórmula.');
    custoDashboardState.data = null;
    await carregarCustoProduto();
    status.textContent = 'Fórmula excluída. O produto e os dados fiscais foram mantidos e a fórmula pode ser cadastrada novamente.';
  } catch (error) { status.textContent = error.message; }
}

function editarCustoProduto(id, usarSugestao = false) {
  if (id === 'xarope' && !custoProdutoState.xarope) return;
  const compostoId = typeof id === 'string' && id.startsWith('composto-') ? Number(id.slice(9)) : null;
  const novoComposto = id === 'composto-novo';
  const composto = compostoId ? custoProdutoState.xaropesCompostos.find(x => x.id === compostoId) : null;
  let produto = id === 'xarope'
    ? {...custoProdutoState.xarope, produto_id: 'xarope', nome_produto: 'Xarope base'}
    : novoComposto
      ? {produto_id:'composto-novo', id:null, nome:'', nome_produto:'Novo xarope composto', revisao:0, itens:[]}
      : composto
        ? {...composto, produto_id:`composto-${composto.id}`, nome_produto:`Xarope composto: ${composto.nome}`}
        : custoProdutoState.produtos.find(p => p.produto_id === id);
  if (!produto) return;
  if (usarSugestao && produto.sugestao_formula) {
    const sugestao = produto.sugestao_formula;
    produto = {...produto, volume_ml:sugestao.volume_ml, unidades_pacote:sugestao.unidades_pacote,
      xarope_composto_id:sugestao.xarope_composto_id,
      xarope_composto_revisao:sugestao.xarope_composto_revisao,
      itens:sugestao.itens, sugestao_aplicada:sugestao};
  }
  custoProdutoState.editando = produto;
  const base = id === 'xarope';
  const editandoComposto = novoComposto || Boolean(composto);
  const receita = base || editandoComposto;
  const produtoAgua = !receita && produto.grupo_estoque?.trim().toUpperCase() === 'AGUA';
  document.getElementById('custoProdutoDadosGarrafa').classList.toggle('hidden', receita);
  document.getElementById('custoProdutoDadosXarope').classList.toggle('hidden', !base);
  document.getElementById('custoProdutoDadosComposto').classList.toggle('hidden', !editandoComposto);
  document.getElementById('custoProdutoVolume').disabled = receita;
  document.getElementById('custoProdutoUnidadesPacote').disabled = receita;
  document.getElementById('custoProdutoDose').disabled = receita;
  document.getElementById('custoProdutoCompostoSelect').disabled = receita;
  document.getElementById('custoProdutoAguaQuenteLitros').disabled = receita;
  document.getElementById('custoProdutoAguaQuenteValor').disabled = receita;
  document.getElementById('custoProdutoRendimento').disabled = !base;
  document.getElementById('custoProdutoCompostoNome').disabled = !editandoComposto;
  document.getElementById('custoProdutoCompostoBaseLitros').disabled = !editandoComposto;
  document.getElementById('custoProdutoCompostoRendimento').disabled = !editandoComposto;
  document.getElementById('custoProdutoCompostoDose').disabled = !editandoComposto;
  document.getElementById('custoProdutoCompostoNome').value = produto.nome || '';
  document.getElementById('custoProdutoCompostoBaseLitros').value = produto.xarope_base_litros || '';
  document.getElementById('custoProdutoCompostoRendimento').value = editandoComposto ? (produto.rendimento_litros || '') : '';
  document.getElementById('custoProdutoCompostoDose').value = editandoComposto ? (produto.xarope_base_litros_1000 || produto.dose_litros_1000 || '') : '';
  const compostoSelect = document.getElementById('custoProdutoCompostoSelect');
  compostoSelect.innerHTML = '<option value="">Selecione o xarope composto</option>' + custoProdutoState.xaropesCompostos.map(x => `<option value="${Number(x.id)}">${gestaoEsc(x.nome)}</option>`).join('');
  compostoSelect.value = produto.xarope_composto_id || '';
  compostoSelect.required = !receita && !produtoAgua;
  document.getElementById('custoProdutoCompostoLabel').classList.toggle('hidden', produtoAgua);
  document.getElementById('custoProdutoDoseLabel').classList.toggle('hidden', produtoAgua);
  document.getElementById('custoProdutoDose').value = produto.xarope_litros || '';
  document.getElementById('custoProdutoAguaQuenteLitros').value = produto.agua_quente_litros || '';
  document.getElementById('custoProdutoAguaQuenteValor').value = produto.agua_quente_valor_litro || '';
  document.getElementById('custoProdutoRendimento').value = produto.rendimento_litros || '';
  document.getElementById('custoProdutoItensTitulo').textContent = base ? 'Ingredientes da receita do xarope base' : editandoComposto ? 'Ingredientes adicionais do sabor' : 'Itens por unidade pronta (PET/garrafa, tampa, rótulo e outros)';
  document.getElementById('custoProdutoQuantidadeTitulo').textContent = receita ? 'Quantidade / receita' : 'Quantidade / garrafa';
  document.getElementById('custoProdutoLista').classList.add('hidden');
  document.getElementById('custoProdutoEditor').classList.remove('hidden');
  document.getElementById('custoProdutoTitulo').textContent = produto.nome_produto;
  document.getElementById('custoProdutoVolume').value = produto.volume_ml || '';
  document.getElementById('custoProdutoUnidadesPacote').value = produto.unidades_pacote || '';
  document.getElementById('custoProdutoItens').innerHTML = '';
  (produto.itens.length ? produto.itens : receita ? [{}] : []).forEach(adicionarItemCustoProduto);
  document.getElementById('custoProdutoMensagem').textContent = '';
  document.getElementById('custoProdutoAtualizacao').textContent = produto.sugestao_aplicada
    ? `Sugestão baseada em ${produto.sugestao_aplicada.origem_produto_nome}: mesmo líquido do sabor, com preforma e rótulo do volume correto. Confira os itens e salve para criar a fórmula.`
    : produto.atualizado_em ? `Última atualização: ${produto.atualizado_em} · ${produto.atualizado_por}` : 'Nova fórmula';
  atualizarCalculoCustoProduto();
  document.getElementById(base ? 'custoProdutoRendimento' : editandoComposto ? 'custoProdutoCompostoNome' : produtoAgua ? 'custoProdutoVolume' : 'custoProdutoCompostoSelect').focus();
}

function adicionarItemCustoProduto(item = {}) {
  const body = document.getElementById('custoProdutoItens');
  if (body.children.length >= 100) return;
  const tr = document.createElement('tr');
  const selected = custoProdutoState.insumos.find(p => p.id === Number(item.produto_id));
  const receita = custoProdutoState.editando?.produto_id === 'xarope'
    || String(custoProdutoState.editando?.produto_id || '').startsWith('composto-');
  const quantidadeLabel = receita ? 'Quantidade na receita' : 'Quantidade por garrafa';
  const options = custoProdutoState.insumos.map(p => {
    const compra = p.ultima_compra;
    const faixa = custoProdutoFaixaPreforma(p);
    const origem = compra?.fonte === 'sped' ? 'SPED' : 'NF-e';
    const referencia = compra
      ? ` · ${origem} ${compra.nota} · ${custoProdutoMoeda(compra.preco)}/${compra.unidade_compra}`
      : ' · sem referência fiscal de entrada vinculada';
    return `<option value="${Number(p.id)}" ${p.id === Number(item.produto_id) ? 'selected' : ''}>${gestaoEsc(p.nome_produto)} (#${Number(p.id)})${faixa ? ` · ${gestaoEsc(faixa)}` : ''}${gestaoEsc(referencia)}</option>`;
  }).join('');
  tr.innerHTML = `<td><select data-custo="produto_id" aria-label="Produto do cadastro" required onchange="selecionarInsumoCusto(this)" style="max-width:320px">
      <option value="">${gestaoEsc(item.nome && !selected ? 'Vincular: ' + item.nome : 'Selecione um produto cadastrado')}</option>${options}</select></td>
    <td><select data-custo="unidade" aria-label="Unidade do item" required onchange="alterarUnidadeCusto(this)"><option value="">Unidade</option>${['kg','g','l','ml','un'].map(u => `<option value="${u}" ${u === (item.unidade || '') ? 'selected' : ''}>${u}</option>`).join('')}</select></td>
    <td><input data-custo="quantidade" aria-label="${quantidadeLabel}" type="number" required min="0.000001" max="999999999.999999" step="0.000001" value="${gestaoEsc(item.quantidade ?? '')}"></td>
    <td><input data-custo="fator_compra" aria-label="Quantidade na unidade da fórmula por embalagem comprada" type="number" min="0.000001" max="999999999.999999" step="0.000001" value="${gestaoEsc(item.fator_compra || '')}" oninput="confirmarConversaoCusto(this)">
      <input type="hidden" data-custo="unidade_compra" value="${gestaoEsc(item.unidade_compra || '')}"><small data-custo="conversao"></small></td>
    <td><input data-custo="preco_provisorio" aria-label="Valor provisório por unidade do item" type="number" min="0.000001" max="999999999.999999" step="0.000001" value="${gestaoEsc(item.preco_provisorio || '')}"><small>Usado somente sem referência fiscal válida.</small></td>
    <td><input data-custo="preco_unitario" aria-label="Preço usado no cálculo; digite se não houver referência fiscal" type="number" readonly min="0.000001" max="999999999.999999" step="0.000001" oninput="informarPrecoProvisorioCusto(this)"><small data-custo="origem_preco"></small></td>
    <td data-custo="subtotal">—</td><td><button type="button" aria-label="Remover item" onclick="this.closest('tr').remove(); atualizarCalculoCustoProduto()">Remover</button></td>`;
  body.appendChild(tr);
  atualizarCalculoCustoProduto();
}

function itensCustoProduto() {
  return [...document.querySelectorAll('#custoProdutoItens tr')].map(tr => {
    const item = Object.fromEntries(
      ['produto_id', 'unidade', 'quantidade', 'fator_compra', 'unidade_compra', 'preco_provisorio']
        .map(key => [key, tr.querySelector(`[data-custo="${key}"]`).value]));
    const precoUsado = tr.querySelector('[data-custo="preco_unitario"]');
    if (!item.preco_provisorio && !precoUsado.readOnly) item.preco_provisorio = precoUsado.value;
    return item;
  });
}

function selecionarInsumoCusto(select) {
  const product = custoProdutoState.insumos.find(p => p.id === Number(select.value));
  const aliases = {lt:'l', litro:'l', litros:'l', und:'un', unidade:'un', unidades:'un', mi:'un', mil:'un', milheiro:'un', kgs:'kg'};
  const raw = (product?.unidade || '').toLowerCase().trim();
  const textoPeca = `${product?.grupo_estoque || ''} ${product?.nome_produto || ''}`.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
  const unit = /PREFORMA|TAMPA|ROTULO|GARRAFA|ROLHA/.test(textoPeca) ? 'un' : (aliases[raw] || raw);
  const row = select.closest('tr');
  row.querySelector('[data-custo="unidade"]').value = ['kg','g','l','ml','un'].includes(unit) ? unit : '';
  if (unit === 'un' && !row.querySelector('[data-custo="quantidade"]').value) row.querySelector('[data-custo="quantidade"]').value = '1';
  row.querySelector('[data-custo="fator_compra"]').value = '';
  row.querySelector('[data-custo="unidade_compra"]').value = '';
  row.querySelector('[data-custo="preco_provisorio"]').value = '';
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

function informarPrecoProvisorioCusto(input) {
  input.closest('tr').querySelector('[data-custo="preco_provisorio"]').value = input.value;
}

function precoCompraCusto(item) {
  const product = custoProdutoState.insumos.find(p => p.id === Number(item.produto_id));
  const compra = product?.ultima_compra;
  const provisorio = Number(item.preco_provisorio);
  const fallback = mensagem => Number.isFinite(provisorio) && provisorio > 0
    ? {preco:provisorio, mensagem:`Valor provisório informado · ${custoProdutoMoeda(provisorio)}/${item.unidade || 'unidade'}. ${mensagem}`, automatico:false, fonte:'provisorio'}
    : {preco:null, mensagem, automatico:false, fonte:null};
  if (!compra) return fallback('Sem compra fiscal de fornecedor vinculada.');
  const units = {KG:['massa',1],G:['massa',.001],T:['massa',1000],L:['volume',1],ML:['volume',.001],M3:['volume',1000],UN:['pecas',1],MIL:['pecas',1000]};
  const origem = units[compra.unidade_compra], destino = units[item.unidade.toUpperCase()];
  let automatico = Boolean(origem && destino && origem[0] === destino[0]);
  let fator = automatico ? origem[1] / destino[1] : (!item.unidade_compra || item.unidade_compra === compra.unidade_compra) ? Number(item.fator_compra) : 0;
  const descricaoPeca = `${product?.nome_produto || ''} ${compra.descricao_xml || ''}`.toUpperCase();
  if (!fator && String(compra.unidade_compra || '').toUpperCase() === 'ML' && item.unidade === 'un'
      && /TAMPA|R[OÓ]TULO|PREFORMA|GARRAFA|ROLHA/.test(descricaoPeca)) {
    fator = 1000;
    automatico = true;
  }
  if (!fator && String(compra.unidade_compra || '').toUpperCase() === 'M' && item.unidade === 'un'
      && /R[OÓ]TULO|BOOB|BOOP|BOPP/.test(descricaoPeca)) {
    const dimension = descricaoPeca.match(/(^|\D)(\d+(?:[.,]\d+)?)\s*X\s*\d/);
    const pitchCm = Number(String(dimension?.[2] || '').replace(',', '.'));
    if (pitchCm > 0) {
      fator = 100 / pitchCm;
      automatico = true;
    }
  }
  const conversaoEstoque = compra.conversao_estoque;
  const unidadeEstoque = units[conversaoEstoque?.unidade];
  let peloEstoque = false;
  if (!fator && !item.fator_compra && unidadeEstoque && destino && unidadeEstoque[0] === destino[0]) {
    fator = Number(conversaoEstoque.quantidade) * unidadeEstoque[1] / destino[1];
    automatico = true;
    peloEstoque = true;
  }
  const origemFiscal = compra.fonte === 'sped' ? 'SPED Fiscal' : 'XML · NF-e';
  const fonte = `${origemFiscal} ${compra.nota} · ${compra.data_compra.slice(0,10)} · ${custoProdutoMoeda(compra.preco)}/${compra.unidade_compra}`;
  const mensagem = Number(compra.preco) <= 0 ? 'Última compra sem preço positivo.' : !fator ? `Informe quantos ${item.unidade || 'kg/l/un'} há em 1 ${compra.unidade_compra || 'embalagem'}.` : fonte;
  if (!(fator > 0 && Number(compra.preco) > 0)) return fallback(mensagem);
  return {preco:Number(compra.preco) / fator,
    mensagem, automatico, fonte:compra.fonte === 'sped' ? 'sped' : 'nfe', conversao:peloEstoque ? `Cadastro de estoque: ${fator} ${item.unidade}/${compra.unidade_compra}` : automatico ? 'Conversão automática' : `${item.unidade || 'unidade da fórmula'} por ${compra.unidade_compra || 'embalagem'}`,
    detalhe: compra.vinculo ? `${compra.vinculo}: ${compra.codigo_xml || ''} · ${compra.descricao_xml || ''}` : ''};
}

function calcularRateioCustoProduto(custoDireto1000) {
  const categorias = {mao_obra:0, impostos:0, energia:0, caldeira:0, combustivel:0, agua:0, outros:0};
  const volume = Number(custoProdutoState.rateio?.volume_mensal_litros);
  const capacidade = Number(custoProdutoState.rateio?.capacidade_litros_hora);
  const horasMensais = Number(custoProdutoState.rateio?.horas_semanais || 44) * 52 / 12;
  for (const item of custoProdutoState.rateio?.itens || []) {
    const valor = Number(item.valor);
    const parcela = ['mensal','abastecimentos'].includes(item.tipo) ? (volume > 0 ? valor * 1000 / volume : 0)
      : item.tipo === 'mensal_horas' ? (capacidade > 0 && horasMensais > 0 ? valor * 1000 / horasMensais / capacidade : 0)
      : item.tipo === 'hora' ? (capacidade > 0 ? valor * 1000 / capacidade : 0)
      : item.tipo === 'litro' ? valor * 1000 : custoDireto1000 * valor / 100;
    categorias[item.categoria] += parcela;
  }
  return {categorias, total:Object.values(categorias).reduce((sum, value) => sum + value, 0)};
}

function atualizarCalculoCustoProduto() {
  const baseEditor = custoProdutoState.editando?.produto_id === 'xarope';
  const compostoEditor = String(custoProdutoState.editando?.produto_id || '').startsWith('composto-');
  const receitaEditor = baseEditor || compostoEditor;
  const produtoAgua = !receitaEditor && custoProdutoState.editando?.grupo_estoque?.trim().toUpperCase() === 'AGUA';
  const items = itensCustoProduto();
  const volume = Number(document.getElementById('custoProdutoVolume').value);
  const rendimento = Number(document.getElementById('custoProdutoRendimento').value);
  const compostoRendimento = Number(document.getElementById('custoProdutoCompostoRendimento').value);
  const compostoBaseLitros = Number(document.getElementById('custoProdutoCompostoBaseLitros').value);
  const compostoBasePor1000 = compostoRendimento > 0 ? compostoBaseLitros * 1000 / compostoRendimento : 0;
  if (compostoEditor) document.getElementById('custoProdutoCompostoDose').value = compostoBasePor1000 || '';
  const aguaLitrosInput = document.getElementById('custoProdutoAguaQuenteLitros');
  const aguaValorInput = document.getElementById('custoProdutoAguaQuenteValor');
  const aguaInformada = aguaLitrosInput.value !== '' || aguaValorInput.value !== '';
  const aguaValida = !aguaInformada || (aguaLitrosInput.value !== '' && aguaValorInput.value !== ''
    && aguaLitrosInput.checkValidity() && aguaValorInput.checkValidity());
  const custoAgua = aguaValida && aguaInformada ? Number(aguaLitrosInput.value) * Number(aguaValorInput.value) : 0;
  const base = custoProdutoState.xarope;
  const composto = custoProdutoState.xaropesCompostos.find(x => x.id === Number(document.getElementById('custoProdutoCompostoSelect').value));
  if (!receitaEditor) document.getElementById('custoProdutoDose').value = composto?.xarope_base_litros_1000 || composto?.dose_litros_1000 || '';
  const rows = [...document.querySelectorAll('#custoProdutoItens tr')];
  let total = 0;
  let valido = baseEditor ? items.length > 0 && document.getElementById('custoProdutoRendimento').checkValidity()
    : compostoEditor ? base?.precificado && items.length > 0
      && document.getElementById('custoProdutoCompostoNome').checkValidity()
      && document.getElementById('custoProdutoCompostoBaseLitros').checkValidity()
      && document.getElementById('custoProdutoCompostoRendimento').checkValidity()
      : (produtoAgua || composto?.precificado) && document.getElementById('custoProdutoCompostoSelect').checkValidity()
        && document.getElementById('custoProdutoVolume').checkValidity()
        && document.getElementById('custoProdutoUnidadesPacote').checkValidity()
        && document.getElementById('custoProdutoDose').checkValidity();
  items.forEach((item, index) => {
    const row = rows[index];
    const price = precoCompraCusto(item);
    const precoUsadoInput = row.querySelector('[data-custo="preco_unitario"]');
    precoUsadoInput.readOnly = ['nfe','sped'].includes(price.fonte);
    precoUsadoInput.value = price.preco === null ? '' : price.preco;
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
  valido = valido && (receitaEditor || aguaValida);
  const status = document.getElementById('custoProdutoCalculo');
  if (!valido) {
    status.textContent = !produtoAgua && !baseEditor && !base?.valido ? 'Cadastre ou revise o xarope base para calcular.'
      : !produtoAgua && !receitaEditor && !composto ? 'Selecione o xarope composto do sabor.'
      : 'Preencha a fórmula e resolva os preços de compra ou conversões pendentes para calcular.';
  } else if (baseEditor) {
    status.textContent = `Receita do xarope base: ${custoProdutoMoeda(total)} · Por litro: ${custoProdutoMoeda(total / rendimento)}`;
  } else if (compostoEditor) {
    const custoBase = Number(base.custo_litro) * compostoBaseLitros;
    const completo = total + custoBase;
    status.textContent = `Xarope base usado no lote (${gestaoNumero(compostoBaseLitros)} L): ${custoProdutoMoeda(custoBase)} · Ingredientes do sabor: ${custoProdutoMoeda(total)} · Custo do lote: ${custoProdutoMoeda(completo)} · Bebida produzida: ${gestaoNumero(compostoRendimento)} L · Base proporcional: ${gestaoNumero(compostoBasePor1000)} L/1.000 L · Custo dos xaropes por 1.000 L de bebida: ${custoProdutoMoeda(completo / compostoRendimento * 1000)}`;
  } else {
    const custoComposto = produtoAgua ? 0 : Number(composto.custo_1000_litros);
    const embalagem1000 = total * 1000000 / volume;
    const direto = embalagem1000 + custoComposto + custoAgua;
    const rateio = calcularRateioCustoProduto(direto);
    const completo = direto + rateio.total;
    const custoUnidadeDireto = direto * volume / 1000000;
    const custoUnidade = completo * volume / 1000000;
    const unidadesPacote = Number(document.getElementById('custoProdutoUnidadesPacote').value);
    const garrafas1000 = 1000000 / volume;
    status.textContent = `${produtoAgua ? 'Água sem xarope' : composto.nome + ' (lote rende ' + gestaoNumero(composto.rendimento_bebida_litros || composto.rendimento_litros) + ' L)'}: ${custoProdutoMoeda(custoComposto)}/1.000 L · ${gestaoNumero(garrafas1000)} garrafas/1.000 L · Embalagens: garrafa ${custoProdutoMoeda(total)}, pacote com ${gestaoNumero(unidadesPacote)} ${custoProdutoMoeda(total * unidadesPacote)}, 1.000 L ${custoProdutoMoeda(embalagem1000)} · Água quente: ${custoProdutoMoeda(custoAgua)}/1.000 L · Custo direto total: ${custoProdutoMoeda(direto)}/1.000 L · Sem rateio: garrafa ${custoProdutoMoeda(custoUnidadeDireto)}, pacote ${custoProdutoMoeda(custoUnidadeDireto * unidadesPacote)} · Rateio: ${custoProdutoMoeda(rateio.total)}/1.000 L · Com rateio: garrafa ${custoProdutoMoeda(custoUnidade)}, pacote ${custoProdutoMoeda(custoUnidade * unidadesPacote)}`;
  }
  document.getElementById('custoProdutoAviso').textContent = 'O valor provisório permanece digitável e salvo. Quando existir referência fiscal válida por NF-e ou SPED, ela terá prioridade somente no cálculo. O servidor recalcula ao salvar.';
}

async function salvarCustoProduto(event) {
  event.preventDefault();
  const produto = custoProdutoState.editando;
  if (!produto) return;
  const fields = document.getElementById('custoProdutoCampos');
  const status = document.getElementById('custoProdutoMensagem');
  const compostoEditor = String(produto.produto_id).startsWith('composto-');
  const compostoSelecionado = custoProdutoState.xaropesCompostos.find(x => x.id === Number(document.getElementById('custoProdutoCompostoSelect').value));
  const payload = {volume_ml: document.getElementById('custoProdutoVolume').value,
    unidades_pacote: document.getElementById('custoProdutoUnidadesPacote').value,
    itens: itensCustoProduto(), revisao: produto.revisao,
    rendimento_litros: document.getElementById('custoProdutoRendimento').value,
    nome: document.getElementById('custoProdutoCompostoNome').value,
    xarope_base_litros: document.getElementById('custoProdutoCompostoBaseLitros').value,
    dose_litros_1000: document.getElementById('custoProdutoCompostoDose').value,
    xarope_composto_id: document.getElementById('custoProdutoCompostoSelect').value,
    xarope_composto_revisao: compostoSelecionado?.revisao,
    xarope_litros: document.getElementById('custoProdutoDose').value,
    agua_quente_litros: document.getElementById('custoProdutoAguaQuenteLitros').value,
    agua_quente_valor_litro: document.getElementById('custoProdutoAguaQuenteValor').value,
    xarope_revisao: custoProdutoState.xarope?.revisao};
  if (compostoEditor) payload.rendimento_litros = document.getElementById('custoProdutoCompostoRendimento').value;
  const compostoId = produto.produto_id === 'composto-novo' ? null : compostoEditor ? produto.id : null;
  const url = produto.produto_id === 'xarope' ? '/api/custo-produto/xarope'
    : compostoEditor ? `/api/custo-produto/xaropes-compostos${compostoId ? '/' + compostoId : ''}`
    : `/api/custo-produto/${produto.produto_id}`;
  const method = compostoEditor && !compostoId ? 'POST' : 'PUT';
  fields.disabled = true;
  status.textContent = 'Salvando fórmula…';
  try {
    const resp = await apiFetch(url, {
      method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.erro || 'Não foi possível salvar a fórmula.');
    if (produto.produto_id === 'xarope' || compostoEditor) receberCustoProduto(data);
    else custoProdutoState.produtos = custoProdutoState.produtos.map(p => p.produto_id === data.produto_id ? data : p);
    custoProdutoState.editando = null;
    document.getElementById('custoProdutoEditor').classList.add('hidden');
    document.getElementById('custoProdutoLista').classList.remove('hidden');
    renderCustoProduto();
    document.getElementById('custoProdutoStatus').textContent = produto.produto_id === 'xarope'
      ? 'Xarope base salvo. Xaropes compostos e produtos foram recalculados.'
      : compostoEditor ? 'Xarope composto salvo. Todas as apresentações ligadas ao sabor foram recalculadas.'
      : 'Fórmula salva. Estimativa recalculada.';
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
  const status = document.getElementById('custoDashboardStatus');
  const requestId = ++custoDashboardState.request;
  status.textContent = 'Consultando custos e compras…';
  try {
    const response = await apiFetch('/api/custo-produto/dashboard');
    const data = await response.json();
    if (requestId !== custoDashboardState.request) return;
    if (!response.ok) throw new Error(data.erro || 'Não foi possível consultar os custos.');
    custoDashboardState.data = data;
    renderDashboardCustoProduto();
    status.textContent = `Custo atualizado em ${data.data_referencia}, usando a fórmula, os últimos preços e os rateios atuais.`;
  } catch(error) {
    if (requestId !== custoDashboardState.request) return;
    custoDashboardState.data = null;
    document.getElementById('custoDashboardTopo').innerHTML = '';
    document.getElementById('custoDashboardRateio').innerHTML = '';
    document.getElementById('custoDashboardProdutos').innerHTML = '';
    document.getElementById('custoDashboardResumo').textContent = '';
    status.textContent = error.message;
  }
}

function custoDashboardTema(nome, grupo='') {
  const texto = `${nome || ''} ${grupo || ''}`.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
  if (grupo === 'AGUA' || /\bAGUA\b/.test(texto)) return {accent:'#0284c7', soft:'#e0f2fe', ink:'#075985'};
  if (/UVA/.test(texto)) return {accent:'#7c3aed', soft:'#ede9fe', ink:'#5b21b6'};
  if (/LARANJA/.test(texto)) return {accent:'#f97316', soft:'#ffedd5', ink:'#9a3412'};
  if (/ABACAXI/.test(texto)) return {accent:'#eab308', soft:'#fef9c3', ink:'#854d0e'};
  if (/FRAMBOESA|TUTTI|ASTUBA/.test(texto)) return {accent:'#e11d48', soft:'#ffe4e6', ink:'#9f1239'};
  if (/GUARANA/.test(texto)) return {accent:'#16a34a', soft:'#dcfce7', ink:'#166534'};
  if (/LIMAO|SODA|CITRUS/.test(texto)) return {accent:'#65a30d', soft:'#ecfccb', ink:'#3f6212'};
  if (/COLA/.test(texto)) return {accent:'#92400e', soft:'#fef3c7', ink:'#78350f'};
  if (/TUBAR/.test(texto)) return {accent:'#0891b2', soft:'#cffafe', ink:'#155e75'};
  return {accent:'#0f766e', soft:'#ccfbf1', ink:'#115e59'};
}

function custoDashboardCard(titulo, subtitulo, conteudo, tema, classe='') {
  return `<article class="custo-dashboard-card ${classe}" style="--custo-accent:${tema.accent};--custo-soft:${tema.soft};--custo-ink:${tema.ink}">
    <div class="custo-dashboard-card-head"><div><h4>${gestaoEsc(titulo)}</h4>${subtitulo ? `<p>${gestaoEsc(subtitulo)}</p>` : ''}</div></div>
    <div class="custo-dashboard-card-body">${conteudo}</div>
  </article>`;
}

function custoDashboardValor(valor, rotulo) {
  return `<div class="custo-dashboard-valor"><span>${gestaoEsc(rotulo)}</span><strong>${valor == null ? '—' : custoProdutoMoeda(valor)}</strong></div>`;
}

function custoDashboardRateioPorLitro(item, rateio) {
  const valor = Number(item.valor || 0);
  if (['mensal','abastecimentos'].includes(item.tipo)) return rateio.volume_mensal_litros ? valor / Number(rateio.volume_mensal_litros) : null;
  if (item.tipo === 'mensal_horas') {
    const horasMensais = Number(rateio.horas_semanais || 44) * 52 / 12;
    return rateio.capacidade_litros_hora && horasMensais ? valor / horasMensais / Number(rateio.capacidade_litros_hora) : null;
  }
  if (item.tipo === 'hora') return rateio.capacidade_litros_hora ? valor / Number(rateio.capacidade_litros_hora) : null;
  if (item.tipo === 'litro') return valor;
  return null;
}

function renderDashboardCustoProduto() {
  const data = custoDashboardState.data;
  if (!data) return;
  const rows = data.produtos || [];
  const priced = rows.filter(p=>p.atual).length;
  document.getElementById('custoDashboardResumo').textContent = `${rows.length} fórmulas de produção · ${priced} com custo calculado · ${rows.length-priced} pendentes`;

  const base = data.xarope_base || {};
  const temaBase = {accent:'#b45309', soft:'#fef3c7', ink:'#78350f'};
  const baseStatus = base.precificado ? 'Custo completo' : (base.valido ? 'Aguardando preço de ingrediente' : 'Fórmula pendente');
  const baseCard = custoDashboardCard('Xarope base', baseStatus,
    `${custoDashboardValor(base.custo_litro, 'Xarope base puro / L de xarope')}
     ${custoDashboardValor(base.custo_lote, 'Custo do lote')}
     <p class="custo-dashboard-meta">Rendimento: ${base.rendimento_litros ? `${gestaoNumero(base.rendimento_litros)} L` : 'não informado'}</p>`, temaBase, 'custo-dashboard-card--xarope');
  const sabores = (data.sabores || []).map(sabor=>{
    const tema = custoDashboardTema(sabor.nome);
    const pendencias = (sabor.pendencias || []).join(' ');
    return custoDashboardCard(sabor.nome, 'Xarope composto do sabor',
      `${custoDashboardValor(sabor.custo_sabor_sem_base_litro_bebida, 'Ingredientes do sabor / L de bebida')}
       ${custoDashboardValor(sabor.custo_com_base_litro_bebida, 'Sabor + xarope base / L de bebida')}
       <div class="custo-dashboard-mini"><span>Base proporcional: <strong>${sabor.xarope_base_litros_1000 ? `${gestaoNumero(sabor.xarope_base_litros_1000)} L/1.000 L` : '—'}</strong></span><span>Bebida produzida: <strong>${sabor.rendimento_bebida_litros ? `${gestaoNumero(sabor.rendimento_bebida_litros)} L` : '—'}</strong></span><span>Xaropes/1.000 L: <strong>${sabor.custo_1000_litros != null ? custoProdutoMoeda(sabor.custo_1000_litros) : '—'}</strong></span></div>
       ${pendencias ? `<p class="custo-dashboard-alerta">${gestaoEsc(pendencias)}</p>` : ''}`, tema, 'custo-dashboard-card--sabor');
  }).join('');
  document.getElementById('custoDashboardTopo').innerHTML = baseCard + sabores;

  const rateio = data.rateio || {};
  const categorias = {mao_obra:'Mão de obra', impostos:'Impostos', energia:'Energia', caldeira:'Caldeira / lenha', combustivel:'Combustível', agua:'Água', outros:'Outros'};
  const tipos = {mensal:'por mês', mensal_horas:'por mês, distribuído nas horas trabalhadas', abastecimentos:'dos abastecimentos concluídos', hora:'por hora', litro:'por litro', percentual:'do custo direto'};
  document.getElementById('custoDashboardRateio').innerHTML = (rateio.itens || []).map(item=>{
    const porLitro = custoDashboardRateioPorLitro(item, rateio);
    const original = item.tipo === 'percentual' ? `${gestaoNumero(item.valor)}%` : custoProdutoMoeda(item.valor);
    const periodo = item.periodo_referencia ? item.periodo_referencia.split('-').reverse().join('/') : 'sem lançamentos';
    const detalhe = item.tipo === 'percentual'
      ? `<div class="custo-dashboard-valor"><span>Percentual</span><strong>${original}</strong></div>`
      : item.tipo === 'abastecimentos'
        ? `${custoDashboardValor(porLitro, 'Combustível por litro produzido')}<p class="custo-dashboard-meta">${original} · ${gestaoNumero(item.registros_origem || 0)} abastecimentos · ${gestaoNumero(item.litros_combustivel || 0)} L abastecidos · referência ${gestaoEsc(periodo)}</p>`
        : `${custoDashboardValor(porLitro, 'Custo convertido por litro')}<p class="custo-dashboard-meta">${original} ${tipos[item.tipo] || ''}</p>`;
    const tema = custoDashboardTema(item.categoria === 'agua' ? 'Água' : item.descricao, item.categoria === 'agua' ? 'AGUA' : '');
    return custoDashboardCard(item.descricao, categorias[item.categoria] || item.categoria, detalhe, tema, 'custo-dashboard-card--rateio');
  }).join('') || '<p class="custo-dashboard-vazio">Nenhum item de rateio cadastrado.</p>';

  const grupos = [
    {id:'AGUA', titulo:'Água', vazio:'Nenhuma fórmula de água cadastrada.'},
    {id:'PET', titulo:'PET por sabor', vazio:'Nenhuma fórmula PET cadastrada.'},
    {id:'GFA', titulo:'Retornável por sabor', vazio:'Nenhuma fórmula retornável cadastrada.'}
  ];
  document.getElementById('custoDashboardProdutos').innerHTML = grupos.map(grupo=>{
    const produtos = rows.filter(p=>String(p.grupo_estoque || '').trim().toUpperCase() === grupo.id);
    if (!produtos.length) return `<section class="custo-dashboard-grupo" data-grupo="${grupo.id}"><h3>${grupo.titulo}</h3><p class="custo-dashboard-vazio">${grupo.vazio}</p></section>`;
    const porSabor = new Map();
    produtos.forEach(produto=>{
      const sabor = grupo.id === 'AGUA' ? 'Água' : (produto.xarope_composto_nome || 'Sabor pendente');
      if (!porSabor.has(sabor)) porSabor.set(sabor, []);
      porSabor.get(sabor).push(produto);
    });
    const blocos = [...porSabor.entries()].map(([sabor, itens])=>{
      const tema = custoDashboardTema(sabor, grupo.id);
      const cards = itens.map(produto=>{
        const calculo = produto.atual;
        const componentes = calculo?.componentes_unidade || {};
        const rateioUnidade = ['mao_obra','impostos','energia','caldeira','combustivel','agua','outros']
          .reduce((total, chave)=>total + Number(componentes[chave] || 0), 0);
        const embalagemItens = (calculo?.itens_unidade || []).map(item=>
          `<li><span>${gestaoEsc(item.nome || 'Item')} · ${gestaoNumero(item.quantidade)} ${gestaoEsc(item.unidade || 'un')}</span><strong>garrafa ${custoProdutoMoeda(item.custo_unidade)} · pacote ${item.custo_pacote == null ? '—' : custoProdutoMoeda(item.custo_pacote)} · 1.000 L ${custoProdutoMoeda(item.custo_1000_litros)}</strong></li>`).join('');
        const pendencias = (produto.pendencias || []).join(' ') || (!produto.unidades_pacote ? 'Informe as unidades por pacote na fórmula.' : '');
        return custoDashboardCard(produto.nome_produto, `${gestaoNumero(produto.volume_ml)} ml · ${sabor}`,
          `${custoDashboardValor(calculo?.custo_unidade_sem_rateio, 'Unidade sem rateio')}
           ${custoDashboardValor(calculo?.custo_unidade, 'Unidade com rateio')}
           ${custoDashboardValor(calculo?.custo_pacote_sem_rateio, `Pacote sem rateio${produto.unidades_pacote ? ` (${produto.unidades_pacote} un.)` : ''}`)}
           ${custoDashboardValor(calculo?.custo_pacote, `Pacote com rateio${produto.unidades_pacote ? ` (${produto.unidades_pacote} un.)` : ''}`)}
           <div class="custo-dashboard-mini"><span>Produção: <strong>${calculo ? `${gestaoNumero(calculo.unidades_1000_litros)} garrafas/1.000 L` : '—'}</strong></span><span>Xarope: <strong>${calculo ? custoProdutoMoeda(componentes.xarope || 0) : '—'}</strong></span><span>Embalagem: <strong>${calculo ? custoProdutoMoeda(componentes.embalagem || 0) : '—'}</strong></span><span>Rateio: <strong>${calculo ? custoProdutoMoeda(rateioUnidade) : '—'}</strong></span></div>
           ${embalagemItens ? `<div class="custo-dashboard-embalagem"><span>Itens de embalagem: por garrafa · pacote · 1.000 L</span><ul>${embalagemItens}</ul></div>` : ''}
           ${pendencias ? `<p class="custo-dashboard-alerta">${gestaoEsc(pendencias)}</p>` : ''}`, tema, 'custo-dashboard-card--produto');
      }).join('');
      return `<div class="custo-dashboard-sabor" style="--custo-accent:${tema.accent};--custo-ink:${tema.ink}"><h4>${gestaoEsc(sabor)}</h4><div class="custo-dashboard-grid">${cards}</div></div>`;
    }).join('');
    return `<section class="custo-dashboard-grupo" data-grupo="${grupo.id}"><h3>${grupo.titulo}</h3>${blocos}</section>`;
  }).join('');
}

const custoRelatorioState = {data:null, request:0};

function custoRelatorioValor(value) {
  return value == null || !Number.isFinite(Number(value)) ? '—' : custoProdutoMoeda(value);
}

function custoRelatorioRateioFormula(item, rateio) {
  const valor = Number(item.valor || 0);
  const volume = Number(rateio.volume_mensal_litros || 0);
  const capacidade = Number(rateio.capacidade_litros_hora || 0);
  const horasSemanais = Number(rateio.horas_semanais || 44);
  const horasMensais = horasSemanais * 52 / 12;
  if (item.tipo === 'mensal' || item.tipo === 'abastecimentos') {
    return {
      formula:`${custoProdutoMoeda(valor)} ÷ ${gestaoNumero(volume)} L/mês`,
      porLitro:volume > 0 ? valor / volume : null
    };
  }
  if (item.tipo === 'mensal_horas') {
    return {
      formula:`${custoProdutoMoeda(valor)} ÷ (${gestaoNumero(horasSemanais)} h/sem × 52 ÷ 12) ÷ ${gestaoNumero(capacidade)} L/h`,
      porLitro:horasMensais > 0 && capacidade > 0 ? valor / horasMensais / capacidade : null
    };
  }
  if (item.tipo === 'hora') {
    return {
      formula:`${custoProdutoMoeda(valor)}/h ÷ ${gestaoNumero(capacidade)} L/h`,
      porLitro:capacidade > 0 ? valor / capacidade : null
    };
  }
  if (item.tipo === 'litro') return {formula:`Valor direto informado: ${custoProdutoMoeda(valor)}/L`, porLitro:valor};
  return {formula:`${gestaoNumero(valor)}% do custo direto de cada produto`, porLitro:null};
}

function custoRelatorioOrigemItem(item) {
  const compra = item?.compra || null;
  const fonte = item?.fonte_preco === 'provisorio'
    ? 'Valor provisório'
    : compra?.fonte === 'sped' || item?.fonte_preco === 'sped' ? 'SPED Fiscal' : compra ? 'XML / NF-e' : 'Sem referência';
  const nota = compra?.nota ? `NF ${compra.nota}` : '—';
  const data = compra?.data_compra ? String(compra.data_compra).slice(0, 10).split('-').reverse().join('/') : '—';
  const valorCompra = compra?.preco_compra != null
    ? `${custoRelatorioValor(compra.preco_compra)} / ${gestaoEsc(compra.unidade_compra || 'un.')}` : '—';
  const fator = item?.fator_aplicado || item?.fator_compra;
  const conversao = fator
    ? `1 ${gestaoEsc(compra?.unidade_compra || item?.unidade_compra || 'emb.')} = ${gestaoNumero(fator)} ${gestaoEsc(item?.unidade || 'un')}`
    : '—';
  return {fonte, nota, data, valorCompra, conversao};
}

function custoRelatorioTabelaItens(titulo, itens, contexto='receita') {
  const rows = (itens || []).map(item=>{
    const origem = custoRelatorioOrigemItem(item);
    return `<tr><td>${gestaoEsc(item.nome || 'Item')}</td><td>${gestaoNumero(item.quantidade)} ${gestaoEsc(item.unidade || '')}</td><td>${gestaoEsc(origem.fonte)}</td><td>${gestaoEsc(origem.nota)}</td><td>${gestaoEsc(origem.data)}</td><td>${origem.valorCompra}</td><td>${origem.conversao}</td><td>${custoRelatorioValor(item.preco_unitario)}</td><td>${custoRelatorioValor(item.custo_formula)}</td></tr>`;
  }).join('');
  return `<div class="custo-relatorio-bloco"><h4>${gestaoEsc(titulo)}</h4><div class="custo-relatorio-tabela"><table><thead><tr><th>Item</th><th>Quantidade/${contexto}</th><th>Fonte</th><th>Nota</th><th>Emissão</th><th>Valor na compra</th><th>Conversão</th><th>R$/un. usada</th><th>Custo na fórmula</th></tr></thead><tbody>${rows || '<tr><td colspan="9">Nenhum item informado.</td></tr>'}</tbody></table></div></div>`;
}

function custoRelatorioRateioCompacto(rateio) {
  const categorias = {mao_obra:'Mão de obra', impostos:'Impostos', energia:'Energia', caldeira:'Caldeira / lenha', combustivel:'Combustível', agua:'Água', outros:'Outros'};
  const rows = (rateio.itens || []).map(item=>{
    const calculo = custoRelatorioRateioFormula(item, rateio);
    const periodo = item.periodo_referencia ? item.periodo_referencia.split('-').reverse().join('/') : '';
    const origem = item.tipo === 'abastecimentos'
      ? `${gestaoNumero(item.registros_origem || 0)} abastecimentos; ${gestaoNumero(item.litros_combustivel || 0)} L${periodo ? `; ${periodo}` : ''}` : '—';
    return `<tr><td>${gestaoEsc(categorias[item.categoria] || item.categoria)}</td><td>${gestaoEsc(item.descricao)}</td><td>${gestaoEsc(origem)}</td><td>${gestaoEsc(calculo.formula)}</td><td>${custoRelatorioValor(calculo.porLitro)}</td><td>${custoRelatorioValor(calculo.porLitro == null ? null : calculo.porLitro * 1000)}</td></tr>`;
  }).join('');
  return `<div class="custo-relatorio-bloco"><h4>Rateios aplicados</h4><p class="hint">${gestaoNumero(rateio.volume_mensal_litros || 0)} L/mês · ${gestaoNumero(rateio.capacidade_litros_hora || 0)} L/h · ${gestaoNumero(rateio.horas_semanais || 44)} h/semana</p><div class="custo-relatorio-tabela"><table><thead><tr><th>Categoria</th><th>Custo</th><th>Origem</th><th>Cálculo</th><th>R$/L</th><th>R$/1.000 L</th></tr></thead><tbody>${rows || '<tr><td colspan="6">Nenhum item de rateio cadastrado.</td></tr>'}</tbody></table></div></div>`;
}

function custoRelatorioProduto(produto) {
  const calculo = produto.atual;
  const tema = custoDashboardTema(produto.xarope_composto_nome || produto.nome_produto, String(produto.grupo_estoque || '').trim().toUpperCase());
  const pendencias = produto.pendencias || [];
  if (!calculo) return `<article class="custo-relatorio-produto" style="--custo-accent:${tema.accent};--custo-soft:${tema.soft};--custo-ink:${tema.ink}"><h4>${gestaoEsc(produto.nome_produto)}</h4><p class="custo-dashboard-alerta">${gestaoEsc(pendencias.join(' ') || 'Custo ainda não calculado.')}</p></article>`;
  const nomes = {xarope:'Xarope composto (base + sabor)', embalagem:'Embalagens', agua_quente:'Água quente da fórmula', mao_obra:'Mão de obra', impostos:'Impostos', energia:'Energia', caldeira:'Caldeira / lenha', combustivel:'Combustível', agua:'Água', outros:'Outros'};
  const componentes = calculo.componentes_1000_litros || {};
  const linhasComponentes = Object.keys(nomes).map(chave=>{
    const v1000 = Number(componentes[chave] || 0);
    const vun = calculo.componentes_unidade?.[chave];
    const vpacote = calculo.componentes_pacote?.[chave];
    return `<tr><td>${nomes[chave]}</td><td>${custoProdutoMoeda(v1000)}</td><td>${custoRelatorioValor(v1000 / 1000)}</td><td>${custoRelatorioValor(vun)}</td><td>${custoRelatorioValor(vpacote)}</td></tr>`;
  }).join('');
  const rastreio = new Map((produto.itens || []).map(item=>[Number(item.produto_id), item]));
  const itens = (calculo.itens_unidade || []).map(item=>{
    const origem = custoRelatorioOrigemItem(rastreio.get(Number(item.produto_id)) || item);
    return `<tr><td>${gestaoEsc(item.nome || 'Item')}</td><td>${gestaoNumero(item.quantidade)} ${gestaoEsc(item.unidade || 'un')}</td><td>${gestaoEsc(origem.fonte)}</td><td>${gestaoEsc(origem.nota)}</td><td>${gestaoEsc(origem.data)}</td><td>${origem.valorCompra}</td><td>${origem.conversao}</td><td>${custoRelatorioValor(item.preco_unitario)}</td><td>${custoRelatorioValor(item.custo_unidade)}</td><td>${custoRelatorioValor(item.custo_pacote)}</td><td>${custoRelatorioValor(item.custo_1000_litros)}</td></tr>`;
  }).join('');
  const volumeLitros = Number(produto.volume_ml || 0) / 1000;
  const pacote = Number(produto.unidades_pacote || calculo.unidades_pacote || 0);
  return `<article class="custo-relatorio-produto" style="--custo-accent:${tema.accent};--custo-soft:${tema.soft};--custo-ink:${tema.ink}">
    <div class="custo-relatorio-produto-head"><div><h4>${gestaoEsc(produto.nome_produto)}</h4><p>${gestaoEsc(produto.xarope_composto_nome || (produto.grupo_estoque === 'AGUA' ? 'Água' : 'Sabor não informado'))} · ${gestaoNumero(produto.volume_ml)} ml · ${pacote ? `${gestaoNumero(pacote)} un./pacote` : 'pacote não informado'}</p></div><strong>${custoRelatorioValor(calculo.custo_unidade)} / unidade</strong></div>
    <div class="custo-relatorio-resumo"><span>Direto / 1.000 L<strong>${custoRelatorioValor(calculo.custo_direto_1000_litros)}</strong></span><span>Rateio / 1.000 L<strong>${custoRelatorioValor(calculo.custo_indireto_1000_litros)}</strong></span><span>Total / 1.000 L<strong>${custoRelatorioValor(calculo.custo_1000_litros)}</strong></span><span>Total / litro<strong>${custoRelatorioValor(calculo.custo_litro)}</strong></span><span>Unidade sem / com rateio<strong>${custoRelatorioValor(calculo.custo_unidade_sem_rateio)} / ${custoRelatorioValor(calculo.custo_unidade)}</strong></span><span>Pacote sem / com rateio<strong>${custoRelatorioValor(calculo.custo_pacote_sem_rateio)} / ${custoRelatorioValor(calculo.custo_pacote)}</strong></span></div>
    <p class="custo-relatorio-formula"><strong>Fechamento:</strong> ${custoRelatorioValor(calculo.custo_direto_1000_litros)} de custo direto + ${custoRelatorioValor(calculo.custo_indireto_1000_litros)} de rateio = ${custoRelatorioValor(calculo.custo_1000_litros)} por 1.000 L. Unidade = total de 1.000 L × ${gestaoNumero(volumeLitros)} L ÷ 1.000. Pacote = unidade × ${gestaoNumero(pacote)}.</p>
    <h5>Componentes do custo</h5><div class="custo-relatorio-tabela"><table><thead><tr><th>Componente</th><th>1.000 L</th><th>1 L</th><th>Unidade</th><th>Pacote</th></tr></thead><tbody>${linhasComponentes}</tbody></table></div>
    <h5>Itens de embalagem por unidade pronta</h5><div class="custo-relatorio-tabela"><table><thead><tr><th>Item</th><th>Quantidade/un.</th><th>Fonte</th><th>Nota</th><th>Emissão</th><th>Valor na compra</th><th>Conversão</th><th>R$/un. usada</th><th>Custo/un.</th><th>Custo/pacote</th><th>Custo/1.000 L</th></tr></thead><tbody>${itens || '<tr><td colspan="11">Nenhum item de embalagem vinculado.</td></tr>'}</tbody></table></div>
    ${pendencias.length ? `<p class="custo-dashboard-alerta">${gestaoEsc(pendencias.join(' '))}</p>` : ''}
  </article>`;
}

function custoRelatorioFolha(sabor, produtos, data) {
  const base = data.xarope_base || {};
  const agua = sabor === 'Água';
  const composto = agua ? null : (data.sabores || []).find(item=>String(item.nome || '').toLocaleLowerCase('pt-BR') === sabor.toLocaleLowerCase('pt-BR'));
  const tema = custoDashboardTema(sabor, agua ? 'AGUA' : '');
  const baseFormula = base.custo_lote != null && Number(base.rendimento_litros) > 0
    ? `${custoRelatorioValor(base.custo_lote)} ÷ ${gestaoNumero(base.rendimento_litros)} L = ${custoRelatorioValor(base.custo_litro)}/L de xarope base` : 'Custo do xarope base pendente.';
  let compostoResumo = '';
  let compostoItens = '';
  if (composto) {
    const totalLote = composto.custo_base_lote == null || composto.custo_itens_sabor_lote == null
      ? null : Number(composto.custo_base_lote) + Number(composto.custo_itens_sabor_lote);
    compostoResumo = `<p class="custo-relatorio-formula"><strong>Fórmula do sabor:</strong> ${custoRelatorioValor(composto.custo_base_lote)} de xarope base + ${custoRelatorioValor(composto.custo_itens_sabor_lote)} de ingredientes = ${custoRelatorioValor(totalLote)} por lote; ${custoRelatorioValor(totalLote)} ÷ ${gestaoNumero(composto.rendimento_bebida_litros || 0)} L = ${custoRelatorioValor(composto.custo_com_base_litro_bebida)}/L de bebida.</p>`;
    compostoItens = custoRelatorioTabelaItens(`Ingredientes específicos de ${sabor}`, composto.itens || [], 'lote');
  }
  return `<article class="boxFrota custo-relatorio-folha" style="--custo-accent:${tema.accent};--custo-soft:${tema.soft};--custo-ink:${tema.ink}">
    <header class="custo-relatorio-folha-head"><div><span>RELATÓRIO CUSTO PRODUTO</span><h3>Fórmula ${gestaoEsc(sabor)}</h3></div><div><strong>Referência ${gestaoEsc(data.data_referencia || '—')}</strong><small>${produtos.length} apresentação(ões)</small></div></header>
    ${agua ? '' : `<p class="custo-relatorio-formula"><strong>Xarope base:</strong> ${gestaoEsc(baseFormula)}</p>${custoRelatorioTabelaItens('Ingredientes do xarope base', base.itens || [], 'lote')}${compostoResumo}${compostoItens}`}
    <div class="custo-relatorio-bloco"><h4>Apresentações e fechamento do custo</h4><div class="custo-relatorio-produtos">${produtos.map(custoRelatorioProduto).join('')}</div></div>
    ${custoRelatorioRateioCompacto(data.rateio || {})}
    <p class="hint">${gestaoEsc(data.metodologia || '')}</p>
  </article>`;
}

function renderRelatorioRateioCustoProduto() {
  const root = document.getElementById('relatorioCustoProdutoConteudo');
  const data = custoRelatorioState.data;
  if (!root || !data) return;
  const grupo = document.getElementById('relatorioCustoProdutoGrupo')?.value || '';
  const busca = (document.getElementById('relatorioCustoProdutoBusca')?.value || '').trim().toLocaleLowerCase('pt-BR');
  const produtos = (data.produtos || []).filter(produto=>{
    const grupoProduto = String(produto.grupo_estoque || '').trim().toUpperCase();
    const texto = `${produto.nome_produto || ''} ${produto.xarope_composto_nome || ''}`.toLocaleLowerCase('pt-BR');
    return (!grupo || grupoProduto === grupo) && (!busca || texto.includes(busca));
  });
  const folhas = new Map();
  produtos.forEach(produto=>{
    const sabor = String(produto.xarope_composto_nome || (String(produto.grupo_estoque || '').trim().toUpperCase() === 'AGUA' ? 'Água' : 'Sabor não informado'));
    if (!folhas.has(sabor)) folhas.set(sabor, []);
    folhas.get(sabor).push(produto);
  });
  root.innerHTML = `<section class="boxFrota custo-relatorio-cabecalho"><h2>Custo produto</h2><p><strong>Referência:</strong> ${gestaoEsc(data.data_referencia || '—')} · uma folha por sabor, com ingredientes, fonte XML/SPED, nota, unidade, conversão e fechamento dos valores.</p><p class="hint">Os valores e cálculos são os mesmos do dashboard. Os filtros alteram as folhas e apresentações incluídas no PDF.</p></section>
    ${[...folhas.entries()].map(([sabor, itens])=>custoRelatorioFolha(sabor, itens, data)).join('') || '<p class="boxFrota custo-dashboard-vazio">Nenhuma fórmula encontrada para este filtro.</p>'}`;
}

async function carregarRelatorioRateioCustoProduto() {
  const status = document.getElementById('relatorioCustoProdutoStatus');
  if (!status) return;
  const requestId = ++custoRelatorioState.request;
  status.textContent = 'Carregando a memória de cálculo atual...';
  try {
    const response = await apiFetch('/api/custo-produto/dashboard');
    const data = await response.json();
    if (requestId !== custoRelatorioState.request) return;
    if (!response.ok) throw new Error(data.erro || 'Não foi possível carregar o relatório.');
    custoRelatorioState.data = data;
    renderRelatorioRateioCustoProduto();
    status.textContent = `Memória atualizada em ${data.data_referencia}.`;
  } catch (error) {
    if (requestId !== custoRelatorioState.request) return;
    custoRelatorioState.data = null;
    document.getElementById('relatorioCustoProdutoConteudo').innerHTML = `<div class="boxFrota custo-dashboard-alerta">${gestaoEsc(error.message)}</div>`;
    status.textContent = error.message;
  }
}

function imprimirRelatorioRateioCustoProduto() {
  const conteudo = document.getElementById('relatorioCustoProdutoConteudo');
  if (!conteudo || !custoRelatorioState.data) return;
  const folhas = [...conteudo.querySelectorAll('.custo-relatorio-folha')].map(folha=>folha.outerHTML).join('');
  if (!folhas) {
    document.getElementById('relatorioCustoProdutoStatus').textContent = 'Nenhuma fórmula no filtro atual para gerar o PDF.';
    return;
  }
  const janela = window.open('', '_blank');
  if (!janela) {
    document.getElementById('relatorioCustoProdutoStatus').textContent = 'O navegador bloqueou a janela de impressão. Libere pop-ups e tente novamente.';
    return;
  }
  janela.opener = null;
  janela.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Custo produto</title><style>
    @page{size:A4 landscape;margin:7mm}*{box-sizing:border-box}body{font:8px Arial,sans-serif;color:#172033;margin:0}.custo-relatorio-cabecalho{display:none}.custo-relatorio-folha{break-before:page;page-break-before:always;border-top:5px solid var(--custo-accent,#64748b);padding-top:5px}.custo-relatorio-folha:first-child{break-before:auto;page-break-before:auto}.custo-relatorio-folha-head{display:flex;justify-content:space-between;border-bottom:2px solid var(--custo-accent,#64748b);margin-bottom:4px}.custo-relatorio-folha-head h3{font-size:16px;margin:1px 0 4px}.custo-relatorio-folha-head div:last-child{text-align:right}.custo-relatorio-folha-head small{display:block}.custo-relatorio-bloco{margin:4px 0}.custo-relatorio-bloco h4,.custo-relatorio-produto h4,.custo-relatorio-produto h5{font-size:9px;margin:3px 0}.custo-relatorio-produto{break-inside:avoid-page;border-left:3px solid var(--custo-accent,#64748b);padding:3px 5px;margin:3px 0;background:#fff}.custo-relatorio-produto-head{display:flex;justify-content:space-between}.custo-relatorio-produto-head p{margin:1px 0}.custo-relatorio-resumo{display:grid;grid-template-columns:repeat(6,1fr);gap:2px;margin:3px 0}.custo-relatorio-resumo span{border:1px solid #dbe4ea;padding:2px}.custo-relatorio-resumo strong{display:block}.custo-relatorio-formula{background:#f8fafc;padding:3px;margin:3px 0}.custo-relatorio-tabela{overflow:visible}table{width:100%;border-collapse:collapse;table-layout:auto}th,td{border:1px solid #cbd5e1;padding:2px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#eef2f6;white-space:nowrap}.hint{color:#526273;margin:3px 0}.custo-dashboard-alerta{color:#9a3412}.custo-dashboard-vazio{padding:4px}
  </style></head><body>${folhas}</body></html>`);
  janela.document.close();
  janela.focus();
  setTimeout(()=>janela.print(), 250);
}

const custoRateioState = {data:null, carregando:false};
const custoRateioCategorias = {mao_obra:'Mão de obra', impostos:'Impostos', energia:'Energia', caldeira:'Caldeira / lenha', combustivel:'Combustível', agua:'Água', outros:'Outros'};
const custoRateioTipos = {mensal:'Valor mensal ÷ volume mensal', mensal_horas:'Valor mensal ÷ horas trabalhadas ÷ capacidade', abastecimentos:'Abastecimentos lançados ÷ volume produzido', hora:'Valor por hora (R$/h)', litro:'Valor por litro (R$/L)', percentual:'Percentual do custo direto (%)'};

async function carregarRateioCustoProduto() {
  if (custoRateioState.carregando) return;
  const status=document.getElementById('custoRateioStatus');
  const fields=document.getElementById('custoRateioCampos');
  custoRateioState.carregando=true;fields.disabled=true;status.textContent='Carregando rateio…';
  try {
    const response=await apiFetch('/api/custo-produto/rateio');const data=await response.json();
    if(!response.ok) throw new Error(data.erro || 'Não foi possível carregar o rateio.');
    custoRateioState.data=data;
    document.getElementById('custoRateioVolume').value=data.volume_mensal_litros || '';
    document.getElementById('custoRateioCapacidadeHora').value=data.capacidade_litros_hora || '';
    document.getElementById('custoRateioHorasSemanais').value=data.horas_semanais || 44;
    document.getElementById('custoRateioItens').innerHTML='';
    (data.itens || []).forEach(adicionarRateioCustoProduto);
    status.textContent=data.revisao ? `Rateio salvo · revisão ${data.revisao} · ${data.atualizado_por}` : 'Nenhum custo indireto cadastrado.';
    fields.disabled=false;
  } catch(error) {custoRateioState.data=null;status.textContent=error.message;}
  finally {custoRateioState.carregando=false;}
}

function adicionarRateioCustoProduto(item={}) {
  const body=document.getElementById('custoRateioItens');if(body.children.length>=100)return;
  const tr=document.createElement('tr');
  tr.innerHTML=`<td><select data-rateio="categoria" aria-label="Categoria do custo">${Object.entries(custoRateioCategorias).map(([key,label])=>`<option value="${key}" ${item.categoria===key?'selected':''}>${label}</option>`).join('')}</select></td>
    <td><input data-rateio="descricao" aria-label="Descrição do custo" maxlength="180" required value="${gestaoEsc(item.descricao || '')}" placeholder="Ex.: folha da produção"></td>
    <td><select data-rateio="tipo" aria-label="Forma de rateio" onchange="atualizarTipoRateioCustoProduto(this)">${Object.entries(custoRateioTipos).map(([key,label])=>`<option value="${key}" ${item.tipo===key?'selected':''}>${label}</option>`).join('')}</select></td>
    <td><input data-rateio="valor" aria-label="Valor do custo" type="number" min="0.000001" max="999999999.999999" step="0.000001" required value="${gestaoEsc(item.valor || '')}"><small data-rateio-origem>${item.tipo==='abastecimentos' ? gestaoEsc(`${item.registros_origem || 0} lançamentos · ${item.periodo_referencia || 'sem período'}`) : ''}</small></td>
    <td><button type="button" onclick="this.closest('tr').remove()">Remover</button></td>`;
  body.appendChild(tr);
  atualizarTipoRateioCustoProduto(tr.querySelector('[data-rateio="tipo"]'),true);
}

function atualizarTipoRateioCustoProduto(select,preservarValor=false) {
  const tr=select.closest('tr');
  const categoria=tr.querySelector('[data-rateio="categoria"]');
  const valor=tr.querySelector('[data-rateio="valor"]');
  const origem=tr.querySelector('[data-rateio-origem]');
  const automatico=select.value==='abastecimentos';
  if (automatico) categoria.value='combustivel';
  categoria.disabled=automatico;
  if (!preservarValor && automatico) valor.value='';
  if (!preservarValor && !automatico && valor.dataset.automatico==='true') valor.value='';
  valor.disabled=automatico;
  valor.required=!automatico;
  valor.placeholder=automatico?'Calculado pelos lançamentos':'';
  valor.dataset.automatico=automatico?'true':'false';
  if (!automatico && origem) origem.textContent='';
}

function dadosRateioCustoProduto() {
  return [...document.querySelectorAll('#custoRateioItens tr')].map(tr=>Object.fromEntries(
    [...tr.querySelectorAll('[data-rateio]')].map(input=>[input.dataset.rateio,input.value])));
}

async function salvarRateioCustoProduto(event) {
  event.preventDefault();if(!custoRateioState.data)return;
  const fields=document.getElementById('custoRateioCampos'),status=document.getElementById('custoRateioStatus');
  const payload={revisao:custoRateioState.data.revisao,
    volume_mensal_litros:document.getElementById('custoRateioVolume').value,
    capacidade_litros_hora:document.getElementById('custoRateioCapacidadeHora').value,
    horas_semanais:document.getElementById('custoRateioHorasSemanais').value,
    itens:dadosRateioCustoProduto()};
  fields.disabled=true;status.textContent='Salvando rateio…';
  try {
    const response=await apiFetch('/api/custo-produto/rateio',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await response.json();if(!response.ok)throw new Error(data.erro || 'Não foi possível salvar o rateio.');
    custoRateioState.data=data;custoProdutoState.rateio=data;
    status.textContent='Rateio salvo. O dashboard e as fórmulas passam a usar os novos custos.';
  } catch(error) {status.textContent=error.message;}
  finally {fields.disabled=false;}
}
