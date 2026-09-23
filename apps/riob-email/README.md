# Email integrado

O portal publica `/apps/riob-email/riob/...` e encaminha as requisicoes para o
blueprint `/gestor-emails/...` de `apps/riob/source/legacy_services.py`. O arquivo
`source/gerenciador_email.py` e referencia legada; nao iniciar outro importador.
Login e autorizacao permanecem no portal. Usar apenas os comandos operacionais
da raiz; dados, anexos e credenciais sao persistentes e nao entram no Git.

No Rio Branco, Dashboard abre Resumo e Monitor abre Status. Gestao reune
mensagens, anexos, recuperacao, historico e backup; Dados possui Importar e-mails.
Contas ficam em Configurar e Fornecedores em Cadastro. A pagina inicial abre
somente Resumo. `GET /importacao` apresenta o formulario da operacao existente,
executada somente ao enviar `POST /importar`.

Configurar > Usuarios e acessos usa `operacao` nas tarefas existentes e `backup`
para download do ZIP. Nenhuma concessao e feita pela reorganizacao. O proxy
preserva o prefixo nas paginas, links internos e redirecionamentos. Testes em
`tests/test_riob_xml_proxy.py` cobrem os dois blueprints integrados, sem acessar
contas externas ou importar dados.

Consulte `docs/AUDITORIA_NAVEGACAO_RIO_BRANCO.md` na raiz para a matriz completa.

## Shell e identidade do deploy (15/09/2026)

O cabecalho compartilhado mantem o nome do contrato do deploy, usuario, marca e
Sair ao navegar. O proxy integra as paginas XML/Email como tarefas isoladas,
removendo a navegacao legada; links e formularios voltam pelo portal. Previews,
APIs e downloads nao recebem shell. Recursos de acesso permanecem nos manifests
e no servidor. Documentacao RioB fica em Documentos (`riob:config`); o antigo
modo completo redireciona para a aplicacao integrada. Ver README da raiz e
`tests/test_riob_xml_proxy.py`, `tests/test_header_navigation.py`.
