const perdasEstoque = {produtos: [], motivos: {}, conferencia: null, ocupada: false, abertura: null, pagina: 1, consulta: 0};
const perdaEl = id => document.getElementById(id);
const perdaNumero = value => Number(value || 0).toLocaleString('pt-BR', {maximumFractionDigits: 3});
const perdaData = value => String(value || '').slice(0, 10).split('-').reverse().join('/');

async function perdaApi(url, options) {
  const response = await apiFetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.erro || 'Não foi possível consultar as baixas.');
  return data;
}

async function abrirPerdasEstoque() {
  if (perdasEstoque.abertura) return perdasEstoque.abertura;
  perdasEstoque.abertura = (async () => {
    perdaEl('perdaNova').disabled = true;
    try {
      const data = await perdaApi('/api/estoque/perdas/produtos');
      perdasEstoque.produtos = data.produtos;
      perdasEstoque.motivos = data.motivos;
      perdasEstoque.hoje = data.hoje;
      for (const id of ['perdaMotivo', 'perdaFiltroMotivo']) {
        const select = perdaEl(id), selected = select.value;
        select.innerHTML = `<option value="">${id === 'perdaMotivo' ? 'Selecione' : 'Todos'}</option>` + Object.entries(data.motivos).map(([key, name]) => `<option value="${_escAttr(key)}">${_escHtml(name)}</option>`).join('');
        select.value = selected;
      }
      filtrarProdutosPerda();
      await carregarHistoricoPerdas(1);
      perdaEl('perdaNova').disabled = false;
    } catch (error) {
      perdaEl('perdaStatus').textContent = error.message;
    }
  })();
  try { await perdasEstoque.abertura; } finally { perdasEstoque.abertura = null; }
}

function filtrarProdutosPerda() {
  const select = perdaEl('perdaProduto'), selected = select.value;
  const normalize = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const query = normalize(perdaEl('perdaBuscaProduto').value);
  const products = perdasEstoque.produtos.filter(p => String(p.produto_id) === selected || normalize([p.nome_produto, p.codigo_produto_nfe, p.codigo_barras].join(' ')).includes(query));
  select.innerHTML = '<option value="">Selecione</option>' + products.map(p => `<option value="${Number(p.produto_id)}">${_escHtml(p.nome_produto)}${p.codigo_produto_nfe ? ' — ' + _escHtml(p.codigo_produto_nfe) : ''}</option>`).join('');
  select.value = selected;
  atualizarQuantidadePerda();
}

function atualizarQuantidadePerda() {
  const product = perdasEstoque.produtos.find(p => String(p.produto_id) === perdaEl('perdaProduto').value);
  for (const [id, key] of [['perdaPallets','por_pallet'], ['perdaVolumes','por_volume']]) {
    perdaEl(id).disabled = !product || !Number(product[key]);
    if (perdaEl(id).disabled) perdaEl(id).value = '';
  }
  const total = Number(perdaEl('perdaPallets').value || 0) * Number(product?.por_pallet || 0)
    + Number(perdaEl('perdaVolumes').value || 0) * Number(product?.por_volume || 0)
    + Number(perdaEl('perdaUnidades').value || 0);
  perdaEl('perdaQuantidadeInfo').textContent = product
    ? `Saldo consultado: ${perdaNumero(product.saldo)} ${product.unidade || 'UN'}. Perda: ${perdaNumero(total)} ${product.unidade || 'UN'}. Cada pallet: ${perdaNumero(product.por_pallet)}; cada caixa/pacote: ${perdaNumero(product.por_volume)} unidades de estoque. O saldo será conferido novamente antes da confirmação.`
    : 'Selecione um produto. Informe a perda em pallets, caixas/pacotes e/ou unidades de estoque.';
}

function novaPerdaEstoque() {
  if (perdasEstoque.ocupada) return;
  perdaEl('perdaFormulario').reset();
  perdasEstoque.conferencia = null;
  perdaEl('perdaCampos').disabled = false;
  perdaEl('perdaData').value = perdasEstoque.hoje;
  perdaEl('perdaData').max = perdasEstoque.hoje;
  perdaEl('perdaConferencia').classList.add('hidden');
  perdaEl('perdaAcoesEdicao').classList.remove('hidden');
  perdaEl('perdaFormulario').classList.remove('hidden');
  perdaEl('perdaStatus').textContent = '';
  filtrarProdutosPerda();
  perdaEl('perdaBuscaProduto').focus();
}

function cancelarPerdaEstoque() {
  if (perdasEstoque.ocupada) return;
  perdasEstoque.conferencia = null;
  perdaEl('perdaFormulario').classList.add('hidden');
  perdaEl('perdaStatus').textContent = 'Conferência cancelada. Nenhuma baixa foi realizada.';
}

function voltarPerdaEstoque() {
  if (perdasEstoque.ocupada) return;
  perdasEstoque.conferencia = null;
  perdaEl('perdaCampos').disabled = false;
  perdaEl('perdaConferencia').classList.add('hidden');
  perdaEl('perdaAcoesEdicao').classList.remove('hidden');
  perdaEl('perdaStatus').textContent = 'Revise os dados e confira novamente.';
}

async function conferirPerdaEstoque(event) {
  event.preventDefault();
  if (perdasEstoque.ocupada) return;
  perdasEstoque.ocupada = true;
  perdaEl('perdaConferir').disabled = true;
  perdaEl('perdaStatus').textContent = 'Conferindo saldo e quantidade...';
  const payload = {
    produto_id: Number(perdaEl('perdaProduto').value), data_ocorrencia: perdaEl('perdaData').value,
    motivo: perdaEl('perdaMotivo').value, justificativa: perdaEl('perdaJustificativa').value,
    pallets: perdaEl('perdaPallets').value, volumes: perdaEl('perdaVolumes').value, unidades: perdaEl('perdaUnidades').value,
  };
  try {
    const data = await perdaApi('/api/estoque/perdas/conferir', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    perdasEstoque.conferencia = data;
    perdaEl('perdaConferenciaTexto').textContent = `${data.nome_produto}: baixar ${perdaNumero(data.quantidade)} ${data.unidade}. Saldo atual: ${perdaNumero(data.saldo_antes)} → após a baixa: ${perdaNumero(data.saldo_depois)} ${data.unidade}. Ocorrência: ${perdaData(data.data_ocorrencia)}. ${perdasEstoque.motivos[data.motivo]}: ${data.justificativa}`;
    perdaEl('perdaCampos').disabled = true;
    perdaEl('perdaAcoesEdicao').classList.add('hidden');
    perdaEl('perdaConferencia').classList.remove('hidden');
    perdaEl('perdaStatus').textContent = 'Conferência pronta. O estoque será alterado somente ao confirmar.';
  } catch (error) {
    perdaEl('perdaStatus').textContent = error.message;
  } finally {
    perdasEstoque.ocupada = false;
    perdaEl('perdaConferir').disabled = false;
  }
}

async function confirmarPerdaEstoque() {
  if (perdasEstoque.ocupada || !perdasEstoque.conferencia) return;
  perdasEstoque.ocupada = true;
  perdaEl('perdaConfirmar').disabled = true;
  perdaEl('perdaVoltar').disabled = true;
  perdaEl('perdaStatus').textContent = 'Registrando baixa...';
  try {
    const data = await perdaApi(`/api/estoque/perdas/${perdasEstoque.conferencia.id}/finalizar`, {method: 'POST'});
    perdasEstoque.conferencia = null;
    perdaEl('perdaFormulario').classList.add('hidden');
    perdaEl('perdaStatus').textContent = `Baixa #${data.id} confirmada. ${data.nome_produto}: saldo ${perdaNumero(data.saldo_antes)} → ${perdaNumero(data.saldo_depois)} ${data.unidade}. ${data.aviso || ''}`;
    // Contagem aberta sera reconferida no servidor; nao altera seu rascunho.
    await abrirPerdasEstoque();
  } catch (error) {
    // Conserva o ID: repetir apos falha de rede nao repete o movimento.
    perdaEl('perdaStatus').textContent = error.message;
  } finally {
    perdasEstoque.ocupada = false;
    perdaEl('perdaConfirmar').disabled = false;
    perdaEl('perdaVoltar').disabled = false;
  }
}

async function carregarHistoricoPerdas(page = 1) {
  const requestId = ++perdasEstoque.consulta;
  const params = new URLSearchParams({pagina: String(page)});
  for (const [id,key] of [['perdaInicio','inicio'],['perdaFim','fim'],['perdaFiltroMotivo','motivo'],['perdaBusca','q']]) {
    if (perdaEl(id).value) params.set(key, perdaEl(id).value);
  }
  perdaEl('perdaHistoricoStatus').textContent = 'Carregando histórico...';
  try {
    const data = await perdaApi('/api/estoque/perdas?' + params);
    if (requestId !== perdasEstoque.consulta) return;
    perdasEstoque.pagina = data.pagina;
    perdaEl('perdaHistoricoBody').innerHTML = data.itens.length ? data.itens.map(row => `<tr>
      <td>#${Number(row.id)}</td><td>${_escHtml(perdaData(row.data_ocorrencia))}</td>
      <td>${_escHtml(row.nome_produto)}<br><small>${_escHtml(row.codigo_produto_nfe || row.codigo_barras || '')}</small></td>
      <td>${_escHtml(perdasEstoque.motivos[row.motivo] || row.motivo)}<br><span class="perda-justificativa">${_escHtml(row.justificativa)}</span></td>
      <td>${perdaNumero(row.quantidade)} ${_escHtml(row.unidade)}</td><td>${perdaNumero(row.saldo_antes)} → ${perdaNumero(row.saldo_depois)} ${_escHtml(row.unidade)}</td>
      <td>${_escHtml(row.usuario)}</td><td>${_escHtml(String(row.finalizado_em || '').replace('T',' '))}</td></tr>`).join('') : '<tr><td colspan="8">Nenhuma baixa confirmada nos filtros selecionados.</td></tr>';
    perdaEl('perdaHistoricoStatus').textContent = `${data.total} baixa(s). ` + data.totais_unidade.map(row => `${perdaNumero(row.quantidade)} ${row.unidade}`).join(' · ');
    perdaEl('perdaPagina').textContent = `Página ${data.pagina} de ${Math.max(1,Math.ceil(data.total / data.limite))}`;
    perdaEl('perdaAnterior').disabled = data.pagina <= 1;
    perdaEl('perdaProxima').disabled = data.pagina * data.limite >= data.total;
  } catch (error) {
    if (requestId !== perdasEstoque.consulta) return;
    perdaEl('perdaHistoricoStatus').textContent = error.message;
    perdaEl('perdaHistoricoBody').replaceChildren();
    perdaEl('perdaAnterior').disabled = true;
    perdaEl('perdaProxima').disabled = true;
  }
}
