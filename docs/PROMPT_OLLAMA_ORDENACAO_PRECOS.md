Escreva somente uma funcao JavaScript pura, sem Markdown ou explicacoes:

function ordenarResultados(linhas, campo, direcao = "asc")

Ela sera usada na tela "preço med.varia". Voce nao precisa conhecer o
repositorio, editar arquivos, acessar banco, alterar permissoes ou criar tela.
Outro executor integrara e testara sua resposta.

Entrada: array de objetos normalizados, por exemplo:
[
  {id: "a", grupo: "PET 2L", cidade: "Londrina", valor: 12.5},
  {id: "b", grupo: "Agua", cidade: "Apucarana", valor: 9},
  {id: "c", grupo: "PET 2L", cidade: "Londrina", valor: null}
]

Regras:
1. Retorne um novo array ordenado. Nao altere o array recebido nem seus objetos.
2. campo aceita somente "valor", "grupo" ou "cidade". direcao aceita somente
   "asc" ou "desc". Parametro invalido deve lancar TypeError.
3. valor e numero finito ou ausente. Compare numericamente; zero e valido.
   null, undefined, NaN e Infinity sao ausentes. Nao converta texto em numero.
4. grupo e cidade sao strings. Compare com
   Intl.Collator("pt-BR", {numeric: true, sensitivity: "base"}).
   String vazia ou somente espacos, null e undefined sao ausentes.
5. Ausentes ficam sempre no final, inclusive na ordem decrescente.
6. Empates preservam a ordem original das linhas, inclusive entre ausentes.
7. Nao use bibliotecas externas, DOM, fetch, eval ou comandos shell.

Resultados esperados para o exemplo (apenas os ids):
- valor asc: b, a, c
- valor desc: a, b, c
- cidade asc: b, a, c
- grupo asc: b, a, c

Mais casos: 2 vem antes de 10; valor zero vem antes de 9; linha sem valor fica
no final em ambas as direcoes; "Grupo 2" vem antes de "Grupo 10".

Retorne somente a funcao completa. Nao repita as instrucoes ou os exemplos.
