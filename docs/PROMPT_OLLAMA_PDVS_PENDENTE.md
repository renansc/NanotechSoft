# Correcao do total de PDVs pendente apos importar PDF

Tarefa solicitada pelo usuario: investigar e corrigir o total de PDVs que continua
como Pendente depois da importacao. Repositorio: /srv/nanotechsoft.

Antes de executar no repositorio, ler AGENTS.md, docs/AI_RESEARCH_MANUAL.md,
README.md, apps/riob/source/docs/AI_CONTEXT.md e PDVS_POR_VENDEDOR.md no mesmo
diretorio. Preservar todas as alteracoes existentes, sem reset/checkout em massa.

## Diagnostico confirmado por GET no servico local

A importacao id=1 persistiu 10 vendedores, soma 4297, em vendas_pdvs_totais.
O PDF /srv/REDE/SETEMBRO.pdf foi importado corretamente pelo usuario.
No GET /api/vendas/relatorio?tipo_relatorio=grupos_embalagem&data_inicio=2026-09-01&data_fim=2026-09-30:
- Sem vendedor: total_carteira=null, pdvs=3396, pendentes=[012 - NORIVAL VIGNOTO,
  014 - LUIZ HUMBERTO, 033 - LUIS CARLOS PIRES]. Esses autonomos nao estao no PDF.
- Vendedor 006 - VINICIUS: total_carteira=408, pdvs=334, pdvs_6=8; funciona.
- Vendedor 022 - RICARDO: total_carteira=434; funciona.

Causa: vendas_pdvs.base_carteira retorna None para o total quando existe qualquer
vendedor sem carteira. O frontend usa esse mesmo campo para exibir o cadastro,
confundindo denominador incompleto com importacao ausente.

## Correcao esperada

Separar soma conhecida das carteiras e denominador valido para percentuais.
1. Acrescentar total_carteira_importada (4297 no exemplo geral), sem fabricar
   totais, sem alterar dados e sem eliminar os autonomos das vendas.
2. Preservar total_carteira como denominador completo: None se faltam carteiras.
   Nao dividir vendas de todos os vendedores por carteira parcial. Continuar
   percentual=null no geral incompleto e explicar os tres vendedores faltantes.
3. No card, mostrar total conhecido como "PDVs importados (parcial)" quando
   faltarem carteiras. Para vendedor com carteira mostrar seu total normal e
   calcular faixa/total*100. 8/408=1,96%; 8/400=2%.
4. Vendedor sem carteira continua pendente. Zero importado e diferente de ausencia.
   Chaves diferentes com o mesmo codigo compartilham uma carteira. Ricardo 11
   nao herda Ricardo 22. Filtros de data, PDV e grupo nao reduzem carteira.
5. Preservar base_carteira e seus consumidores; preferir helper resumo_carteira.
   Integrar no payload do mix e no frontend comum ao relatorio/dashboard.
6. Testar geral parcial, completo, sem importacao, zero, vendedor com/sem total,
   aliases por codigo, revisao do cache, frontend e permissoes. Atualizar docs e
   descricao do recurso vendas no manifest/catalogo, sem conceder acessos.
7. Aplicar localmente apenas apos testes por ./up.sh. Conferir GET real e hashes.
   Nao importar novamente o PDF, nao editar dados, nao sincronizar/restaurar bancos,
   nao criar scripts de deploy, nao publicar Git/Render nem alterar login.

## Subtarefa para esta chamada ao modelo

A execucao de arquivos, testes e deploy sera feita pelo executor apos revisao.
Voce deve gerar apenas um JSON valido com as chaves "diagnostico" (string) e
"codigo" (string com UMA funcao Python completa chamada resumo_carteira).
Assinatura: resumo_carteira(totais, vendedores, filtro='').
Nao incluir imports, comandos shell ou afirmar que executou arquivos/testes.
A funcao deve chamar base_carteira, reutilizar identidade e retornar dict:
- total_carteira: denominador retornado por base_carteira;
- total_carteira_importada: soma dos totais conhecidos por identidade no escopo,
  ou None se nenhum cadastro correspondente; preservar zero real;
- carteiras_pendentes: lista retornada por base_carteira.
Sem filtro, soma todas as carteiras salvas uma vez por codigo. Com filtro,
considera somente a identidade escolhida. Nao modificar argumentos.
As funcoes existentes estao abaixo e nao devem ser alteradas nesta resposta.

```python
def identidade(key):
    match = re.match(r'^(\d+)\s*-', str(key).strip())
    return str(int(match[1])) if match else str(key).upper()

def base_carteira(totais, vendedores, filtro=''):
    saved = {identidade(r['vendedor_key']): int(r['total']) for r in totais}
    required = {identidade(v['chave']): v['chave'] for v in vendedores}
    required.update({identidade(r['vendedor_key']): r['vendedor_key'] for r in totais})
    if filtro:
        required = {identidade(filtro): filtro}
    missing = sorted(required[k] for k in required if k not in saved)
    total = None if missing or not required else sum(saved[k] for k in required)
    return total, missing
```
