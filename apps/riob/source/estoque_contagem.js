let contagemConferencia = null;
let contagemSalvando = false;
let relatorioContagensPagina = 1;
let relatorioContagensRequest = 0;

async function finalizarContagemEstoque(){
  if (contagemSalvando || contagemEstoque?.finalizada) return;
  const rows = (contagemEstoque?.produtos || []).filter(p => resultadoContagemEstoque(p));
  const status = document.getElementById('estoqueContagemStatus');
  if (!rows.length || rows.some(p => resultadoContagemEstoque(p).erro)) {
    status.textContent = 'Informe ao menos um produto e corrija as quantidades invalidas antes de conferir.';
    return;
  }
  contagemSalvando = true;
  document.getElementById('estoqueContagemFinalizar').disabled = true;
  status.textContent = 'Conferindo com o saldo atualizado...';
  try {
    const response = await apiFetch('/api/estoque/contagens/conferir', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      itens:rows.map(p => ({produto_id:p.id, ...p.contagem})),
      observacao:document.getElementById('estoqueContagemObservacao').value,
    })});
    const data = await response.json();
    if (!response.ok) throw new Error(data.erro || 'Falha ao conferir a contagem.');
    contagemConferencia = data;
    const missing = (contagemEstoque?.produtos.length || 0) - rows.length;
    document.getElementById('contagemConferenciaResumo').textContent = `${rows.length} produto(s) contado(s); ${missing} nao preenchido(s), fora do ajuste. Desperdicio: ${_estoqueFormatQtd(data.resumo.desperdicio)} uni. Sobras / possivel erro de contagem: ${_estoqueFormatQtd(data.resumo.sobra)} uni.`;
    const itensAgrupados = data.itens.map(i => ({
      ...(rows.find(p => Number(p.id) === Number(i.produto_id)) || {}), ...i,
    }));
    document.getElementById('contagemConferenciaBody').innerHTML = _estoqueLinhasAgrupadas(itensAgrupados, i => {
      const produto = i;
      const fatores = {porPallet:i.por_pallet, porVolume:i.por_volume};
      return `<tr data-produto-id="${Number(i.produto_id)}">
      <td>${_escHtml(i.nome_produto)}</td><td>${formatarQuantidadeContagem(produto, i.saldo_antes, fatores)}</td>
      <td>${formatarQuantidadeContagem(produto, i.quantidade_contada, fatores)}</td><td>${_escHtml(_estoqueFormatQtd(i.diferenca))}</td>
      <td>${i.desperdicio > 0 ? 'Desperdicio' : i.sobra > 0 ? 'Possivel erro de contagem' : 'Sem diferenca'}</td></tr>`;
    }, 5);
    document.getElementById('contagemConferenciaStatus').textContent = '';
    _abrirPopupBloqueante(document.getElementById('contagemConferenciaModal'));
    document.getElementById('contagemConferenciaVoltar').focus();
    status.textContent = 'Confira as quantidades no popup antes de confirmar o ajuste.';
  } catch (error) {
    status.textContent = error.message;
  } finally {
    contagemSalvando = false;
    document.getElementById('estoqueContagemFinalizar').disabled = !!contagemEstoque?.finalizada;
  }
}

function fecharConferenciaContagem(){
  if (contagemSalvando) return;
  _fecharPopupBloqueante(document.getElementById('contagemConferenciaModal'));
  contagemConferencia = null;
  document.getElementById('estoqueContagemFinalizar').focus();
}

async function confirmarFinalizacaoContagem(){
  if (contagemSalvando || !contagemConferencia) return;
  contagemSalvando = true;
  const controls = document.querySelectorAll('#contagemConferenciaModal button');
  controls.forEach(b => b.disabled = true);
  const status = document.getElementById('contagemConferenciaStatus');
  status.textContent = 'Salvando contagem e ajustando saldos...';
  try {
    const response = await apiFetch(`/api/estoque/contagens/${contagemConferencia.id}/finalizar`, {method:'POST'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.erro || 'Nao foi possivel finalizar a contagem.');
    contagemEstoque.finalizada = data.id;
    contagemEstoque.resultado = data;
    renderContagemEstoque();
    document.getElementById('estoqueContagemStatus').textContent = `Contagem #${data.id} finalizada. Saldos ajustados e historico registrado. Desperdicio: ${_estoqueFormatQtd(data.resumo.desperdicio)} uni; sobras: ${_estoqueFormatQtd(data.resumo.sobra)} uni.${data.aviso ? ' '+data.aviso : ''}`;
    document.getElementById('estoqueContagemIndicadores').textContent = `Ultima contagem: desperdicio ${_estoqueFormatQtd(data.resumo.desperdicio)} uni | possivel erro de contagem ${_estoqueFormatQtd(data.resumo.sobra)} uni.`;
    document.getElementById('estoqueContagemFinalizar').disabled = true;
    _fecharPopupBloqueante(document.getElementById('contagemConferenciaModal'));
    contagemConferencia = null;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    contagemSalvando = false;
    controls.forEach(b => b.disabled = false);
  }
}

function filtrosRelatorioContagens(){
  const params = new URLSearchParams();
  for (const [key,id] of [['inicio','relContInicio'],['fim','relContFim'],['q','relContBusca'],['tipo','relContTipo']]) {
    const value = document.getElementById(id).value;
    if (value) params.set(key,value);
  }
  return params;
}

async function carregarRelatorioContagens(pagina=1){
  const rid = ++relatorioContagensRequest;
  const params = filtrosRelatorioContagens(); params.set('pagina',pagina);
  const status = document.getElementById('relContStatus');
  const prev = document.getElementById('relContAnterior'), next = document.getElementById('relContProxima');
  prev.disabled = next.disabled = true;
  status.textContent = 'Consultando contagens finalizadas...';
  try {
    const response = await apiFetch('/api/estoque/contagens/relatorio?'+params);
    const data = await response.json();
    if (rid !== relatorioContagensRequest) return;
    if (!response.ok) throw new Error(data.erro || 'Falha ao consultar relatorio.');
    relatorioContagensPagina = data.pagina;
    document.getElementById('relContResumo').textContent = `${data.resumo.total} registro(s) | Desperdicio: ${_estoqueFormatQtd(data.resumo.desperdicio)} uni | Sobras / possivel erro de contagem: ${_estoqueFormatQtd(data.resumo.sobra)} uni`;
    document.getElementById('relContBody').innerHTML = data.itens.map(i => `<tr>
      <td>#${Number(i.contagem_id)}<br>${_escHtml(new Date(i.finalizado_em).toLocaleString('pt-BR'))}</td>
      <td>${_escHtml(i.nome_produto)}<br><small>${_escHtml(i.observacao || '')}</small></td>
      <td>${_escHtml(_estoqueFormatQtd(i.saldo_antes))}</td><td>${_escHtml(_estoqueFormatQtd(i.quantidade_contada))}</td>
      <td>${_escHtml(_estoqueFormatQtd(i.desperdicio))}</td><td>${_escHtml(_estoqueFormatQtd(i.sobra))}</td>
      <td>${_escHtml(i.usuario)}</td></tr>`).join('') || '<tr><td colspan="7">Nenhuma contagem finalizada para os filtros.</td></tr>';
    status.textContent = `Pagina ${data.pagina}. Totais referentes a todos os registros filtrados.`;
    prev.disabled = data.pagina <= 1;
    next.disabled = data.pagina * data.limite >= data.resumo.total;
  } catch (error) {
    if (rid !== relatorioContagensRequest) return;
    document.getElementById('relContBody').innerHTML = '';
    document.getElementById('relContResumo').textContent = '';
    status.textContent = error.message;
  }
}

function imprimirRelatorioContagens(){
  window.open('/apps/riob/api/estoque/contagens/relatorio/pdf?'+filtrosRelatorioContagens(), '_blank', 'noopener');
}
