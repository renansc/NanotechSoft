# Chamados

Módulo integrado ao portal para registrar requisições e manutenções de TI,
predial, elétrica, hidráulica, mecânica, segurança e outras áreas. O frontend
fica em `apps/chamados/source`; rotas e tabelas fazem parte do portal.

## Dados reutilizados

- solicitantes, responsáveis e autores vêm de `usuarios`;
- equipamentos vêm de `tecnologia_dispositivos`;
- um chamado pode existir sem equipamento, para ocorrências prediais;
- documentos podem ser gerais, vinculados a um equipamento ou anexados a um chamado.

## Fluxo

1. Abra o chamado com categoria, prioridade, descrição e sintomas.
2. Vincule solicitante, responsável e equipamento quando aplicável.
3. Registre diagnóstico, trabalho executado, tempo gasto e mudanças de status.
4. Para resolver ou fechar, informe obrigatoriamente a medida resolutiva.
5. O histórico passa a alimentar a busca de casos semelhantes. Chamados com
   medida resolutiva registrada aparecem no Histórico de soluções, mesmo antes
   do fechamento; somente casos resolvidos ou fechados alimentam as sugestões
   automáticas apresentadas durante o atendimento.

Os dados do chamado e os registros de intervenção podem ser corrigidos pela
tela de detalhes. Ao editar uma solução no histórico, o resumo resolutivo do
chamado é atualizado a partir da solução mais recente.

Manuais e documentações gerais também podem ser editados. É possível corrigir
metadados e links ou substituir o arquivo; sem um novo arquivo, o anexo atual é
preservado.

Status disponíveis: `ABERTO`, `TRIAGEM`, `EM_ATENDIMENTO`, `AGUARDANDO`,
`RESOLVIDO`, `FECHADO` e `CANCELADO`.

## Sugestões e base de conhecimento

A busca local compara categoria, subcategoria, equipamento, tipo do equipamento
e termos relevantes do problema. Somente chamados resolvidos ou fechados são
usados como solução sugerida. Manuais gerais ou ligados ao equipamento também
aparecem nas recomendações. O cálculo não envia dados a serviços externos.

## Documentos

São aceitos PDF, imagens, texto, Markdown, documentos e planilhas com até 15 MB,
além de links HTTP/HTTPS. Arquivos de execução ficam em
`apps/chamados/uploads`, ignorados pelo Git. Eles devem entrar na rotina de
backup de dados do servidor separadamente do código.

## Rotas principais

- `GET /apps/chamados/api/bootstrap`: usuários, equipamentos e indicadores.
- `GET|POST /apps/chamados/api/tickets`: lista ou abre chamados.
- `GET|PUT /apps/chamados/api/tickets/<id>`: detalhe e atualização.
- `POST /apps/chamados/api/tickets/<id>/interventions`: histórico e tempo.
- `PUT /apps/chamados/api/tickets/<id>/interventions/<intervention_id>`: corrige
  um registro do histórico e sua solução.
- `GET /apps/chamados/api/similar`: casos e documentos semelhantes.
- `GET|POST /apps/chamados/api/documents`: manuais e anexos.
- `PUT /apps/chamados/api/documents/<id>`: edita metadados, link ou arquivo.
- `GET /apps/chamados/api/documents/<id>/download`: arquivo ou link protegido.

O login e as permissões são sempre os do portal.
