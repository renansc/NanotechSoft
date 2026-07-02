# LG AWS / ASHK100G - Vinculo MWL x Estudo

## Resumo

No console LG AWS (`ASHK100G` / `X-Clever`), o vinculo entre o exame recebido da `Modality Worklist` e o "estudo selecionado" parece depender de uma camada local de mapeamento por `OCS code`, e nao apenas das tags DICOM padrao retornadas pela MWL.

## Evidencias encontradas

### 1. Documentacao publica da LG nao trouxe o Conformance Statement DICOM

- A pagina do `FDA 510(k)` confirma o produto `X-Clever (ASHK100G)`, mas nao publica o comportamento detalhado de MWL/OCS/tag mapping:
  - https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID=K233599
- A ficha oficial da LG confirma que o `ASHK100G` e o software da acquisition workstation:
  - https://www.lg.com/us/business/download/resources/CT41005931/10-14-17HQ701G_Spec%20Sheet_40323_LR%5B20230405_022429%5D.pdf

### 2. O manual encontrado para o ASHK100G aponta mapeamento local por codigo

Uma copia indexada do manual do `ASHK100G` apareceu em resultado de busca com os seguintes pontos:

- existe menu `Procedure`
- existe opcao `Code Mapping`
- existe cadastro de body parts por `Procedure Code (OCS)`
- existe comportamento de auto-registro do body part quando o `OCS code` esta presente
- existe `Import / Export`, mas o trecho exibido sugere importacao de protocolos/condicoes, nao ficou provado que existe importacao em massa do mapeamento `OCS code -> body part`

Fonte indexada:
- https://www.scribd.com/document/901473248/User-Manual-Ashk100g-Eng-210429-1

Observacao:
- essa fonte nao e um portal oficial da LG, entao deve ser tratada como indicio forte, nao como confirmacao final do fabricante

## Impacto pratico para o RaioxPacs

Hoje o RaioxPacs ja envia na MWL os campos mais relevantes para esse vinculo:

- `RequestedProcedureID`
- `RequestedProcedureDescription`
- `RequestedProcedureCodeSequence`
- `StudyDescription`

Se o AWS estiver configurado para vincular o exame pela tabela local de `OCS code`, o ideal e que o codigo recebido da MWL bata com o codigo cadastrado no equipamento, por exemplo `TE-003`, `TE-054`, etc.

## Hipotese mais provavel

O console LG tem uma lista interna de procedimentos/codigos e usa esse cadastro para:

- decidir qual body part deve aparecer no `Exam order`
- marcar o item como `Selected`
- agrupar varios body parts quando a MWL traz mais de um item relacionado

Isso sugere que o processo pode nao depender de um "arquivo automatico" vindo pela MWL. Em vez disso, a MWL envia o codigo, e o aparelho consulta a tabela local dele.

## O que ainda falta confirmar

Precisamos do `DICOM Conformance Statement` oficial do modelo/versao do console LG para confirmar:

- qual tag o AWS usa no `Code Mapping`
- se ele aceita `RequestedProcedureID`, `RequestedProcedureCodeSequence`, `Scheduled Procedure Step Description` ou outra tag como chave
- se existe importacao/exportacao do cadastro de `Procedure Code (OCS)`
- se o mapeamento fica em banco/arquivo local do Windows ou apenas na configuracao da aplicacao

## Recomendacao operacional

1. Verificar no AWS o menu `Procedure` e `Code Mapping`.
2. Conferir qual tag DICOM esta selecionada como chave para o `OCS code`.
3. Padronizar no RaioxPacs o envio dos codigos exatamente iguais aos codigos cadastrados no AWS.
4. Ver se o menu `Import / Export` exporta um arquivo da tabela de procedimentos; se exportar, isso pode permitir carga em lote em vez de cadastro manual exame por exame.
5. Solicitar para a LG o `DICOM Conformance Statement` exato da versao `AWS 3.06.16`.

## Observacao sobre o card automatico

O card do RaioxPacs nao vai para `executado` apenas porque o exame foi aberto/selecionado no AWS.
Ele sobe automaticamente quando o PACS local recebe o estudo (`C-STORE`) e popula o catalogo local (`public.study` / `public.objects`).
