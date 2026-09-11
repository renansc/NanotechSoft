# Instruções obrigatórias para agentes

Antes de analisar, alterar, testar ou publicar este projeto, leia integralmente:

1. `docs/AI_RESEARCH_MANUAL.md`
2. `README.md`
3. a documentação específica do app que será alterado

As regras do manual são pressupostos permanentes do repositório. Não crie novos
scripts de deploy dentro dos apps, não restaure/sincronize bancos em comandos
comuns e não reintroduza login próprio no RioB.

Toda criacao ou alteracao de funcao deve atualizar a documentacao e o catalogo
de acessos em Config > Usuarios e acessos, incluindo recursos do manifest,
autorizacao no servidor e testes. Login e sessao sao unicos; somente Nanotech
e Render exibem o portal de apps. Demais deploys abrem a aplicacao diretamente.
