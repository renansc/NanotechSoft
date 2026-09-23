/* Lancamento e consulta da apuracao diaria; sem movimentar o estoque. */
const custoDiaState = {data:null, catalogo:[], dirty:false, request:0};
const custoDiaCategorias = {formula:'Fórmula / insumos', pessoal:'Pessoal', embalagem:'Embalagem adicional', agua:'Água', energia:'Energia', outras:'Outras despesas', desperdicio:'Desperdício'};
function custoDiaHoje(){return new Intl.DateTimeFormat('en-CA',{timeZone:'America/Sao_Paulo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
function custoDiaValor(value){return value == null ? 'Pendente' : custoProdutoMoeda(value);}
function custoDiaGrupos(){return [...new Set(custoDiaState.catalogo.map(p=>p.grupo_estoque.trim().toUpperCase()))];}
function custoDiaGrupoOptions(value=''){return '<option value="">Compartilhado (por litros)</option>'+custoDiaGrupos().map(g=>`<option value="${gestaoEsc(g)}" ${g===value?'selected':''}>${g==='GFA'?'Retornável':gestaoEsc(g)}</option>`).join('');}

async function carregarCustoDiario(){
  const date=document.getElementById('custoDiaData');
  if(!date.value) date.value=custoDiaHoje();
  if(custoDiaState.dirty && !confirm('Descartar as alterações não salvas e carregar o dia?')) {date.value=custoDiaState.data?.data || date.value;return;}
  const status=document.getElementById('custoDiaStatus');
  const requestId=++custoDiaState.request;
  const fields=document.getElementById('custoDiaCampos');fields.disabled=true;
  status.textContent='Carregando o dia e as referências de custo…';
  try{
    const response=await apiFetch('/api/custo-diario?data='+date.value);const data=await response.json();
    if(requestId!==custoDiaState.request)return;
    if(!response.ok)throw new Error(data.erro || 'Não foi possível carregar o dia.');
    custoDiaState.data=data;custoDiaState.catalogo=data.catalogo;custoDiaState.dirty=false;
    for(const kind of ['producao','despesas']){
      document.getElementById('custoDia'+kind).innerHTML='';
      data.dados[kind].forEach(item=>adicionarLinhaCustoDia(kind,item));
    }
    document.getElementById('custoDiaContagens').innerHTML=contagensCustoDia(data.contagens || []);
    custoDiaState.dirty=false;
    status.textContent=data.revisao?`Dia salvo · revisão ${data.revisao} · ${data.atualizado_por}`:'Novo dia: informe a produção boa e os gastos.';
    fields.disabled=false;
  }catch(error){status.textContent=error.message;custoDiaState.data=null;}
}
function adicionarLinhaCustoDia(kind,item={}){
  if(!['producao','despesas'].includes(kind))return;
  const body=document.getElementById('custoDia'+kind);
  if(body.children.length>=200)return;
  const tr=document.createElement('tr');
  const field=(key,label,opts='')=>`<input data-dia="${key}" aria-label="${label}" value="${gestaoEsc(item[key] ?? '')}" ${opts}>`;
  const money=key=>field(key,'Valor total em reais','type="number" min="0" max="999999999.999999" step="0.000001" required');
  if(kind==='producao'){
    const product=custoDiaState.catalogo.find(p=>p.produto_id===Number(item.produto_id));
    const historic=custoDiaState.data?.resultado?.produtos.find(p=>p.produto_id===Number(item.produto_id));
    tr.innerHTML=`<td><select data-dia="produto_id" aria-label="Produto produzido" required onchange="produtoCustoDia(this)"><option value="">Selecione o produto</option>${!product && item.produto_id?`<option selected value="${Number(item.produto_id)}">${gestaoEsc(historic?.nome_produto || 'Produto inativo: revise')}</option>`:''}${custoDiaState.catalogo.map(p=>`<option value="${p.produto_id}" ${p.produto_id===Number(item.produto_id)?'selected':''}>${gestaoEsc(p.nome_produto)}</option>`).join('')}</select></td>
      <td>${field('embalagens','Embalagens boas produzidas','type="number" min="1" max="999999999" step="1" required')}</td>
      <td>${field('volume_ml','Volume da embalagem em ml','type="number" min="0.000001" max="999999999" step="0.000001" required')}</td>
      <td>${field('por_pacote','Embalagens por pacote','type="number" min="1" max="999999999" step="1" required')}</td>`;
  }else{
    tr.innerHTML=`<td><select data-dia="grupo" aria-label="Grupo de custo">${custoDiaGrupoOptions(item.grupo)}</select></td>
      <td>${field('setor','Setor','maxlength="180" list="custoDiaSetores" required')}</td>
      <td>${field('descricao','Descrição','maxlength="180" required')}</td>`;
    tr.innerHTML+=`<td><select data-dia="categoria" aria-label="Categoria">${['pessoal','embalagem','agua','energia','outras'].map(k=>`<option value="${k}" ${item.categoria===k?'selected':''}>${custoDiaCategorias[k]}</option>`).join('')}</select></td><td>${money('valor')}</td>`;
  }
  tr.innerHTML+='<td><button type="button" aria-label="Remover linha" onclick="this.closest(\'tr\').remove();custoDiaState.dirty=true">Remover</button></td>';
  body.appendChild(tr);custoDiaState.dirty=true;
}
function produtoCustoDia(select){
  const p=custoDiaState.catalogo.find(p=>p.produto_id===Number(select.value));const row=select.closest('tr');
  row.querySelector('[data-dia=volume_ml]').value=p?.volume_ml || '';
  row.querySelector('[data-dia=por_pacote]').value=p?.por_pacote_sugerido || '';
}
function dadosCustoDia(){return Object.fromEntries(['producao','despesas'].map(kind=>[kind,[...document.querySelectorAll('#custoDia'+kind+' tr')].map(tr=>Object.fromEntries([...tr.querySelectorAll('[data-dia]')].map(el=>[el.dataset.dia,el.value])))]));}
async function salvarCustoDia(event){
  event.preventDefault();if(!custoDiaState.data)return;
  const fields=document.getElementById('custoDiaCampos'),date=document.getElementById('custoDiaData'),status=document.getElementById('custoDiaStatus');
  const payload={revisao:custoDiaState.data.revisao,dados:dadosCustoDia()};
  fields.disabled=true;date.disabled=true;status.textContent='Apurando e salvando…';
  try{
    const response=await apiFetch('/api/custo-diario?data='+custoDiaState.data.data,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await response.json();if(!response.ok)throw new Error(data.erro || 'Não foi possível salvar.');
    custoDiaState.data=data;custoDiaState.dirty=false;
    status.textContent=`Dia salvo. Total: ${custoDiaValor(data.resultado.resumo.total)}. Consulte os detalhes no dashboard.`;
  }catch(error){status.textContent=error.message;}
  finally{fields.disabled=false;date.disabled=false;}
}

async function abrirVisaoCustoDashboard(){
  const mode=document.getElementById('custoDashboardVisao').value;
  document.getElementById('custoDashboardMensal').classList.toggle('hidden',mode!=='mensal');
  document.getElementById('custoDashboardDiario').classList.toggle('hidden',mode!=='diario');
  if(mode==='mensal')return carregarDashboardCustoProduto();
  return carregarDashboardCustoDia();
}
let custoDiaDashboard=null;
async function carregarDashboardCustoDia(){
  const date=document.getElementById('custoDiaDashData');if(!date.value)date.value=custoDiaHoje();
  const status=document.getElementById('custoDiaDashStatus');status.textContent='Consultando custo do dia…';
  const requested=date.value;
  try{
    const response=await apiFetch('/api/custo-diario/dashboard?data='+requested);const data=await response.json();
    if(date.value!==requested)return;
    if(!response.ok)throw new Error(data.erro || 'Não foi possível consultar o dia.');
    custoDiaDashboard=data;
    const groups=document.getElementById('custoDiaDashGrupo'),previous=groups.value;
    groups.innerHTML='<option value="">Todos os grupos</option>'+(data.resultado?.grupos || []).map(g=>`<option value="${gestaoEsc(g.grupo)}">${g.grupo==='GFA'?'Retornável':gestaoEsc(g.grupo)}</option>`).join('');groups.value=previous;
    renderDashboardCustoDia();
    status.textContent=data.revisao?`Apuração salva em ${data.atualizado_em} por ${data.atualizado_por}. Média por grupo; confira cada apresentação abaixo.`:'Dia sem produção e gastos salvos. As contagens disponíveis aparecem abaixo. Cadastre a produção e os gastos em Gestão > Custos diários por grupo.';
  }catch(error){custoDiaDashboard=null;renderDashboardCustoDia();status.textContent=error.message;}
}
function renderDashboardCustoDia(){
  const box=document.getElementById('custoDiaDashResultado');const result=custoDiaDashboard?.resultado;
  if(!result){box.innerHTML='';return;}
  const group=document.getElementById('custoDiaDashGrupo').value,unit=document.getElementById('custoDiaDashUnidade').value;
  const groups=result.grupos.filter(g=>!group || g.grupo===group),products=result.produtos.filter(p=>!group || p.grupo===group);
  const per=row=>unit==='total'?{...row.componentes,total:row.total}:row.por_unidade[unit];
  box.innerHTML=`<p>${gestaoEsc(result.metodologia)}</p>
    <div class="table-responsive" style="overflow-x:auto"><table><thead><tr><th>Grupo</th><th>Litros</th><th>Embalagens</th><th>Pacotes equivalentes</th>${Object.values(custoDiaCategorias).map(s=>`<th>${s}</th>`).join('')}<th>Total</th></tr></thead><tbody>${groups.map(g=>`<tr><td>${gestaoEsc(g.grupo)}</td><td>${gestaoNumero(g.litros)}</td><td>${gestaoNumero(g.embalagens)}</td><td>${gestaoNumero(g.pacotes)}</td>${Object.keys(custoDiaCategorias).map(k=>`<td>${custoDiaValor(per(g)[k])}</td>`).join('')}<td>${custoDiaValor(per(g).total)}</td></tr>`).join('') || '<tr><td colspan="12">Sem produção informada.</td></tr>'}</tbody></table></div>
    <h3>Custo por produto e apresentação</h3><div class="table-responsive" style="overflow-x:auto"><table><thead><tr><th>Produto</th><th>ml / embalagem</th><th>Embalagens / pacote</th><th>Custo / litro</th><th>Custo / embalagem</th><th>Custo / pacote</th><th>Total do dia</th><th>Pendências</th></tr></thead><tbody>${products.map(p=>`<tr><td>${gestaoEsc(p.nome_produto)}</td><td>${gestaoNumero(p.volume_ml)}</td><td>${gestaoNumero(p.por_pacote)}</td><td>${custoDiaValor(p.por_unidade.litros.total)}</td><td>${custoDiaValor(p.por_unidade.embalagens.total)}</td><td>${custoDiaValor(p.por_unidade.pacotes.total)}</td><td>${custoDiaValor(p.total)}</td><td>${gestaoEsc(p.pendencias.join(' '))}</td></tr>`).join('')}</tbody></table></div>
    <h3>Desperdício por setor${group?' — '+gestaoEsc(group):''}</h3>${desperdicioCustoDia(group)}
    ${result.nao_rateado.length?'<h3>Gastos sem produção para ratear</h3><p>'+result.nao_rateado.map(e=>`${gestaoEsc(e.grupo || 'Compartilhado')} · ${gestaoEsc(e.setor)} · ${gestaoEsc(e.descricao)}: ${custoDiaValor(e.valor)}`).join('<br>')+'</p>':''}`;
}
function desperdicioCustoDia(group){
  const losses=custoDiaDashboard.resultado.perdas.filter(p=>!group || !p.grupo || p.grupo===group);
  const sums={};for(const p of losses){const key=JSON.stringify([p.setor,p.unidade]);const row=sums[key] ||= {setor:p.setor,unidade:p.unidade,quantidade:0,valor:0};row.quantidade+=Number(p.quantidade);row.valor=row.valor===null || p.valor===null ? null : row.valor+Number(p.valor);}
  return '<p>Perdas compartilhadas aparecem por inteiro nesta conferência; o rateio financeiro está no custo do grupo.</p><table><thead><tr><th>Setor</th><th>Quantidade</th><th>Unidade</th><th>Valor perdido</th></tr></thead><tbody>'+Object.values(sums).map(p=>`<tr><td>${gestaoEsc(p.setor)}</td><td>${gestaoNumero(p.quantidade)}</td><td>${gestaoEsc(p.unidade)}</td><td>${custoDiaValor(p.valor)}</td></tr>`).join('')+'</tbody></table>';
}

function contagensCustoDia(losses){
  if(!losses.length)return '<p>Nenhuma falta em contagem finalizada nesta data.</p>';
  return '<table><thead><tr><th>Contagem</th><th>Produto</th><th>Setor de estoque</th><th>Falta</th><th>Valor</th></tr></thead><tbody>'+losses.map(p=>`<tr><td>#${Number(p.contagem_id)}</td><td>${gestaoEsc(p.descricao)}</td><td>${gestaoEsc(p.setor)}</td><td>${gestaoNumero(p.quantidade)} ${gestaoEsc(p.unidade)}</td><td>${custoDiaValor(p.valor)}</td></tr>`).join('')+'</tbody></table>';
}
