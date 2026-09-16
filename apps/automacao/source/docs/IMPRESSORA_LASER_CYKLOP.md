# Impressora a laser Cyklop — protocolo de comunicacao N8 V1.2

Fonte: `Laser communication protocol N8 V1.2.pdf`, fornecido pela operacao.
O PDF original de 19 paginas foi copiado integralmente para
`static/documentos/protocolo-comunicacao-laser-cyklop-n8-v1.2.pdf`.
A marca Cyklop foi informada pela operacao. N8 consta no nome do arquivo;
nao confirma o modelo fisico, numero de serie ou setor do equipamento.
Este documento e um protocolo, nao um manual de operacao/manutencao.

## Acesso e inventario

- DOCUMENTOS > Automacao > Manuais das maquinas > Impressora a laser Cyklop.
- Dashboard > Automacao > Maquinas Automacao > Impressora a laser Cyklop.
- Slug: `impressora-laser-cyklop`.
- Recurso existente em Config > Usuarios e acessos: `automacao:*`.

O manifest mantem o recurso existente; o portal valida sessao, contrato e acesso
para guia, PDF, ficha e APIs (GET e POST). Nao sao concedidas permissoes novas.
O startup inclui a ficha somente no cliente `rio-branco`, sem sobrescrever
cadastros ou leituras. O PDF e o guia integram o catalogo tecnico compartilhado.

## Comunicacao documentada (paginas 4 e 5)

TCP ou RS232 (User port / Service port), dados UTF-8. Estrutura documentada:
inicio, Device ID, conteudo e terminador. Os delimitadores sao configuraveis;
os exemplos do PDF nao usam prefixo visivel e terminam em `;;`. Conferir a
configuracao real antes de implementar o gateway. IP, porta TCP, parametros
seriais e Device ID nao sao informados para esta instalacao.

| Ponto do portal | Consulta de leitura | Interpretacao |
| --- | --- | --- |
| `placa_conectada` | `GetLinkStatus;;` | 1 = conectada, 0 = desconectada; conexao interna com a placa, nao conectividade TCP |
| `estado_marcacao` | `GetMarkStatus;;` | Codigo de estado 0 a 7 |
| `contador_total` | `GetCount;;`, campo 1 | Total de marcacoes |
| `contador_atual` | `GetCount;;`, campo 2 | Contagem atual |
| `marcacoes_perdidas` | `GetCount;;`, campo 3 | Contagem acumulada de perdas |
| `tempo_marcacao_ms` | `GetCount;;`, campo 4 | Tempo de uma marcacao em ms |

Exemplo do PDF: `GetCount;;` retorna `2,1,0,100;;`.
`GetMarkedCount;;` e `GetMissedCount;;` consultam contadores individualmente.
Estados: 0 ocioso; 1 simulacao; 2 marcacao; 3 pre-visualizacao; 4 correcao do
laser; 5 correcao da luz vermelha; 6 emissao forcada do laser; 7 marcacao rotativa.
Retornos espontaneos `MarkStatus`, `MarkCount` e `MissCount` dependem de
habilitacao na interface (paginas 18 e 19).

## Recebimento de telemetria

O cadastro fica `aguardando` ate receber leitura real. Esta entrega nao instala
um coletor TCP/RS232 nem estabelece conexao com o equipamento. Um gateway deve
consultar o protocolo, validar/decodificar as respostas e enviar ao portal:

```http
POST /apps/automacao/api/maquinas/impressora-laser-cyklop/leituras
Content-Type: application/json

{
  "pontos": {
    "placa_conectada": true,
    "estado_marcacao": 2,
    "contador_total": 2,
    "contador_atual": 1,
    "marcacoes_perdidas": 0,
    "tempo_marcacao_ms": 100
  }
}
```

A rota requer a sessao unica e o acesso de Automacao. A conexao da placa falsa
gera alarme; perdas acumuladas nao sao tratadas automaticamente como falha
ativa. Limites operacionais dependem de validacao. O protocolo inclui comandos
que alteram a maquina, mas o portal nao os implementa nem os executa.

Validacao: testes de inventario, estado inicial, leitura, alarme, reinicializacao
idempotente, isolamento de cliente, guia/PDF, links integrados e autorizacao no
servidor em `tests/test_machines.py` do app e `tests/test_menu_pdf.py` da raiz.
