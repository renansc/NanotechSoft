# raioXPacs Docs

## 1. Objetivo deste portal

Este portal existe para deixar a operacao do raioXPacs menos dependente de memoria oral e mais dependente de
documentacao versionada junto do codigo. Tudo o que esta aqui pode ser aberto pelo navegador em `/docs/index.html`
ou pelo botao `Docs` do menu lateral da aplicacao.

## 2. Ordem de leitura recomendada

### Para implantacao ou manutencao tecnica

1. [Arquitetura](ARQUITETURA_SISTEMA.md)
2. [Operacao e Deploy](OPERACAO_E_DEPLOY.md)
3. [API e Dados](API_E_DADOS.md)
4. [Diagramas e Processos](DIAGRAMAS_E_PROCESSOS.md)

### Para uso diario da clinica

1. [Uso e Fluxos Funcionais](USO_E_FLUXOS_FUNCIONAIS.md)
2. [Diagramas e Processos](DIAGRAMAS_E_PROCESSOS.md)
3. [Operacao e Deploy](OPERACAO_E_DEPLOY.md) na parte de backup, troubleshooting e rotina operacional

## 3. Mapa dos documentos

| Arquivo | Foco |
| --- | --- |
| `README.md` | Visao geral do portal e ordem de leitura |
| `ARQUITETURA_SISTEMA.md` | Componentes, runtime, pastas, integracoes e storage |
| `USO_E_FLUXOS_FUNCIONAIS.md` | Manual funcional do cockpit e das rotinas da clinica |
| `DIAGRAMAS_E_PROCESSOS.md` | Fluxogramas Mermaid dos processos principais |
| `OPERACAO_E_DEPLOY.md` | Bootstrap, variaveis, Docker, Render, backup e troubleshooting |
| `API_E_DADOS.md` | Rotas HTTP, servicos DICOM/MWL e modelo de dados |

## 4. O que esta coberto

- cockpit web com Dashboard, Kanban, Pacientes, Exames, Relatorio, Laudos & Viewer, Financeiro, Comunicacao,
  Painel, Worklist, Storage, Config e Docs;
- login por departamento e desbloqueio admin para a aba Config;
- backend Flask com rotas JSON e paginas HTML;
- servidor DICOM proprio para `C-ECHO`, `C-STORE`, `C-FIND`, `C-GET` e `C-MOVE`;
- servidor MWL proprio para `Modality Worklist C-FIND`;
- bootstrap automatico do schema `raiox` e das tabelas `public.*` usadas pelo PACS;
- persistencia de anexos, imagens DICOM e backups no runtime local;
- deploy local, Docker e web-only no Render com PACS/MWL podendo ficar externos.

## 5. Limites conhecidos que precisam ser entendidos

- o cockpit interno nao tem camada completa de autenticacao por usuario; a protecao atual e mais forte no portal de
  compartilhamento externo do paciente do que no uso interno do cockpit;
- em hospedagem web publica, o comum e deixar apenas a interface HTTP exposta e apontar PACS/MWL externos pela tela
  `Config`;
- o portal `/docs` serve HTML e Markdown estaticos do proprio repositorio, sem pipeline de build separado.

## 6. Quando atualizar a documentacao

Atualize estes arquivos sempre que houver mudanca relevante em pelo menos um destes pontos:

- estrutura do menu ou dos fluxos operacionais;
- rotas HTTP ou payloads principais;
- schema `raiox.*` ou tabelas `public.*`;
- estrategia de deploy, backup, `PORT`, `DATABASE_URL` ou `RUNTIME_ROOT`;
- AE Titles, portas DICOM/MWL ou politica de integracao externa;
- comportamento do viewer, compartilhamento e painel.

## 7. Atalhos importantes

- `/docs`
- `/docs/`
- `/docs/index.html`
- `/docs/documentacao.html`
- `/docs/diagramas.html`
- `/api/ping`
- `/api/health`

## 8. Resultado esperado para a equipe

Ao final da leitura, a equipe deve conseguir:

- entender onde cada modulo do raioXPacs vive;
- operar a clinica no dia a dia usando o menu correto;
- subir o projeto localmente, em Docker ou em um servico web;
- diagnosticar problemas comuns de banco, porta, MWL, PACS e backups;
- abrir rapidamente os fluxogramas sem depender de ferramentas externas.
