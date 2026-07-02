# LG AWS - Checklist de Vinculacao por Requested Procedure ID

Use esta lista no menu de mapeamento do AWS quando a chave de vinculacao estiver configurada como `Requested Procedure ID`.

| Requested Procedure ID | Nome do exame |
| --- | --- |
| TE-002 | ABDOMEN |
| TE-003 | ACROMIO |
| TE-004 | ADENOIDE |
| TE-005 | ANTE-PE |
| TE-006 | ANTEBRAÇO |
| TE-007 | ARCOS COSTAIS |
| TE-008 | ARCOS ZIGOMÁTICOS |
| TE-009 | ARTICULAÇÃO ACROMIOCLAVICULAR |
| TE-010 | ARTICULAÇÃO ACROMIOCLAVICULAR |
| TE-011 | ARTICULAÇÃO COXOFEMORAL |
| TE-012 | ARTICULAÇÃO ESCAPULO-UMERAL |
| TE-013 | ARTICULAÇÃO ESTERNOCLAVICULAR |
| TE-014 | ARTICULAÇÃO SACROILÍACA |
| TE-015 | ATM |
| TE-016 | BACIA |
| TE-017 | BACIA PARA IDADE ÓSSEA |
| TE-018 | BRAÇO |
| TE-019 | CALCÃNEO |
| TE-020 | CAVUM |
| TE-021 | CLAVÍCULA |
| TE-022 | CÓCCIX |
| TE-023 | COLUNA CERVICAL |
| TE-024 | COLUNA CERVICO-TORACO-LOMBAR |
| TE-025 | COLUNA CERVICOTORÁCICA |
| TE-026 | COLUNA DORSAL |
| TE-027 | COLUNA DORSO-LOMBAR |
| TE-028 | COLUNA LOMBAR |
| TE-029 | COLUNA LOMBO-SACRA |
| TE-030 | COLUNA SACRO |
| TE-031 | COLUNA SACRO-CÓCCIX |
| TE-032 | COLUNA TORÁCICA |
| TE-033 | COLUNA TORACOLOMBAR |
| TE-034 | COLUNA TOTAL |
| TE-035 | CORAÇÃO E VASOS DA BASE |
| TE-036 | COSTELAS |
| TE-037 | COTOVELO |
| TE-038 | COXA |
| TE-039 | COXOFEMORAL |
| TE-040 | CRÂNIO |
| TE-041 | DEDOS DA MÃO |
| TE-042 | DEDOS DO PÉ |
| TE-043 | DEGLUTOGRAMA |
| TE-044 | ESCÁPULA |
| TE-045 | ESTERNO |
| TE-046 | ESTERNOCLAVICULAR |
| TE-047 | FACE |
| TE-048 | FÊMUR |
| TE-049 | FIBULA |
| TE-050 | JOELHO |
| TE-051 | MANDÍBULA |
| TE-052 | MÃO |
| TE-053 | MÃOS E PUNHOS |
| TE-054 | MÃOS E PUNHOS PARA IDADE ÓSSEA |
| TE-055 | MASTOIDE |
| TE-056 | MAXILAR INFERIOR |
| TE-057 | OMBRO |
| TE-058 | ÓRBITAS |
| TE-059 | OSSO NASAL |
| TE-060 | OSSOS DA FACE |
| TE-061 | OSSOS LONGOS |
| TE-062 | PATELA |
| TE-063 | PÉ |
| TE-064 | PELVE |
| TE-065 | PERNA |
| TE-066 | PESCOÇO |
| TE-067 | PULSO |
| TE-068 | PUNHO |
| TE-069 | QUADRIL |
| TE-070 | RÁDIO |
| TE-071 | SEIOS DA FACE |
| TE-072 | SELA |
| TE-073 | SELA TURCICA |
| TE-074 | TÍBIA |
| TE-075 | TORACO-ABDOMINAL |
| TE-076 | TÓRAX |
| TE-077 | TÓRAX OIT |
| TE-078 | TORNOZELO |
| TE-079 | ÚMERO |

## Uso recomendado

1. No AWS, abrir o cadastro de `Procedure` ou `Code Mapping`.
2. Selecionar a chave `Requested Procedure ID`.
3. Criar ou ajustar cada item usando o codigo `TE-xxx` da coluna da esquerda.
4. Associar esse codigo ao body part/procedure equivalente no aparelho.

## Observacoes

- `TE-009` e `TE-010` possuem a mesma descricao textual. Vale conferir se no AWS eles precisam apontar para o mesmo body part ou para protocolos diferentes.
- Depois do mapeamento, o teste ideal e chamar um exame da MWL com codigo conhecido, por exemplo `TE-003` ou `TE-054`, e verificar se o estudo ja entra selecionado.
