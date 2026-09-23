# XML integrado

O modulo e atendido pelo blueprint `XML_BP` de
`apps/riob/source/legacy_services.py`, integrado ao RioB em `/importar-xml/`.
O arquivo `source/importador_xml_homologacao.py` e uma referencia legada;
nao e iniciado como um segundo importador. O proxy do portal publica o modulo
em `/apps/riob-xml/riob`. Login, contrato do cliente e autorizacao sao os do portal.
Use somente os comandos operacionais da raiz; dados e arquivos ficam no ambiente.

No Rio Branco, DADOS > XML > Importar XML abre a pagina inicial do importador.
Esse atalho foi restaurado em 14/09/2026, com o recurso existente `*`, depois de
ter sido omitido na reorganizacao. Gestao conserva Arquivos XML e Revisao de
abastecimentos; Estoque conserva Estoque e Abastecimentos; Cadastro conserva a
configuracao da empresa. Abrir um atalho nao importa nem altera dados.

O teste de preservacao de destinos em `tests/test_menu_pdf.py` compara o menu
publicado com os manifests e suas equivalencias documentadas em
`docs/MENU_RIO_BRANCO_PDF.md`.

## Rotas do importador

O proxy preserva o prefixo `/importar-xml/` ao encaminhar subpaginas, inclusive
`estoque`, `abastecimentos`, `arquivos`, `config`, exportacoes e progresso de
importacao. Antes da correcao de 14/09/2026, subpaginas eram encaminhadas para a
raiz do RioB, provocando 404. Links internos e redirecionamentos do importador
permanecem sob `/apps/riob-xml/riob/`, preservando filtros e a autorizacao XML.

Config > Usuarios e acessos usa o recurso existente `riob-xml:*` (Todas as
funcoes), explicitado tambem no atalho base do manifest. A correcao nao concede
acessos. `tests/test_riob_xml_proxy.py` verifica paginas reais do blueprint,
filtros, exportacao, links de importacao, redirecionamentos e bloqueios por
sessao, permissao e contrato do deploy, sem importar XMLs ou escrever dados.


## Auditoria de navegacao e tarefas (14/09/2026)

A configuracao da empresa fica em Configurar > XML; as operacoes e o recurso `riob-xml:*` permanecem. A auditoria completa de rotas e tarefas fica em `docs/AUDITORIA_NAVEGACAO_RIO_BRANCO.md` na raiz.

## Shell e identidade do deploy (15/09/2026)

O cabecalho compartilhado mantem o nome do contrato do deploy, usuario, marca e
Sair ao navegar. O proxy integra as paginas XML/Email como tarefas isoladas,
removendo a navegacao legada; links e formularios voltam pelo portal. Previews,
APIs e downloads nao recebem shell. Recursos de acesso permanecem nos manifests
e no servidor. Documentacao RioB fica em Documentos (`riob:config`); o antigo
modo completo redireciona para a aplicacao integrada. Ver README da raiz e
`tests/test_riob_xml_proxy.py`, `tests/test_header_navigation.py`.
