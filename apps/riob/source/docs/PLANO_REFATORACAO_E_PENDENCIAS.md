# Plano de Refatoracao e Pendencias

Revisao em 2026-06-13.

Este documento registra o plano de saneamento tecnico do sistema RioBranco: refatoracao, comentarios, remocao de codigo desnecessario, atualizacao de documentacao e dependencias pendentes. A ideia e reduzir risco operacional sem trocar a arquitetura de uma vez.

## Estado Atual

- A arvore pode conter alteracoes operacionais locais; qualquer refatoracao deve preservar trabalho nao relacionado.
- A validacao Python deve continuar cobrindo `compileall`, testes unitarios e `pip check`.
- A cobertura automatizada cresceu, mas ainda nao cobre todos os fluxos integrados e de navegador.
- O sistema principal esta concentrado em arquivos grandes:
  - `server.py`: 20890 linhas.
  - `script.js`: 13040 linhas depois da primeira limpeza.
  - `style.css`: 3556 linhas.
  - `RioBranco.html`: 2434 linhas.
- Ha tambem um modulo ESXi separado com tamanho relevante:
  - `esxi/vsphere_portal/services/vsphere.py`: 1996 linhas.
  - `esxi/vsphere_portal/static/app.js`: 2586 linhas.

## Pendencias Encontradas

### Frontend Principal

Primeira limpeza executada em 2026-05-11:

- removidas funcoes antigas sobrescritas em `script.js`;
- removido o stub instrucional de `renderDashboardFrota`;
- consolidado `limparFiltrosRelatorioVendas`, preservando limpeza de mes, vendedor, cliente e datas;
- validado que nao ha mais nomes de funcao duplicados na busca por declaracoes `function`/`async function`;
- reduzidas 637 linhas do `script.js`.

Limpeza complementar executada em 2026-06-13:

- removidos helpers Python sem referencias no backend e no agente web;
- consolidada a criacao de alarmes de RPM, temperatura e vibracao no monitor industrial;
- removidos do Git o SQLite e os segmentos HLS gerados pelo monitor de cameras;
- removidos um HTML de camera sem rota, um CSS externo sem referencia e uma chave SSH privada versionada;
- adicionadas regras no `.gitignore` para impedir novo versionamento de chaves privadas;
- mantidos backups, fotos, PDFs e snapshots operacionais por serem dados, nao codigo morto.

Pendencias restantes do frontend:

- quebrar `script.js` por dominio;
- criar validacao automatizada de navegador para as funcoes globais chamadas por `onclick`;
- revisar handlers inline em `RioBranco.html` antes da migracao para modulos ES.

### Backend Principal

`server.py` mistura muitas responsabilidades:

- bootstrap, schema e migracoes leves;
- parsing de CSV, PDF, XML, OCR e HTML do portal NF-e;
- estoque e conferencias;
- fretes, frota, abastecimento, lavagem e comissao;
- SIP, FreePBX, certificados, backup e relatorios;
- rotas Flask e serializacao publica.

Essa concentracao aumenta risco de regressao e dificulta testar regras isoladas. A prioridade e extrair modulos por dominio mantendo as rotas antigas intactas.

### Comentarios e Logs

Itens para limpeza:

- Comentarios legados ainda em uso:
  - `script.js:14`: compatibilidade com APIs antigas de `motoristas`.
  - `server.py:11134`: fallback para senhas legadas em texto puro.
- Logs operacionais com `print` no backend:
  - `server.py:1848`, `server.py:6453`, `server.py:7881`, `server.py:7895`, `server.py:12993`, `server.py:13625`, `server.py:17140`.
  - `nfe_ws.py:244`.
- Logs de debug no frontend:
  - `console.log` removido da busca atual; os casos encontrados foram convertidos para `console.error` ou `console.info`.

Nem todo `console.warn` precisa sair, mas `console.log` de erro operacional deve virar feedback de UI ou log padronizado.

### Dependencias

`pip list --outdated` apontou atualizacoes disponiveis. As mais importantes:

- Flask `3.1.0` -> `3.1.3`.
- mysql-connector-python `9.2.0` -> `9.7.0`.
- reportlab `4.2.5` -> `4.5.0`.
- cryptography `43.0.3` -> `48.0.0`.
- pyOpenSSL `24.2.1` -> `26.2.0`.
- signxml `3.2.2` -> `4.4.0`.
- lxml `5.4.0` -> `6.1.0`.
- Pillow `11.3.0` -> `12.2.0`.
- paramiko `3.5.1` -> `5.0.0`.
- rapidocr `2.1.0` -> `3.8.1`.
- onnxruntime `1.25.1` -> `1.26.0`.

Atualizacoes major devem ser feitas em lote separado, com backup e teste de fluxos NF-e, OCR, PDF, SIP/SSH e relatorios. Nao atualizar tudo de uma vez em producao.

## Plano Prioritario

### Fase 1 - Limpeza Segura e Baixo Risco

1. Concluido: remover stubs e funcoes sobrescritas em `script.js`, comecando por `renderDashboardFrota`.
2. Concluido: consolidar funcoes duplicadas de filtros e relatorios, mantendo apenas a versao usada pela UI atual.
3. Concluido: remover comentarios instrucionais que sobraram de edicao manual.
4. Concluido: trocar `console.log` de erro por `console.warn`/`console.error` consistente ou por feedback de tela.
5. Pendente: adicionar testes de smoke para endpoints principais sem depender do banco real, usando mocks como o teste de backup ja faz.

Validacao minima da fase:

- `compileall`.
- `unittest discover`.
- Validar sintaxe JavaScript quando houver `node` disponivel.
- Abrir `RioBranco.html` e validar dashboard frota, fretes, vendas e estoque.

### Fase 2 - Modularizar Backend sem Mudar Contrato

Extrair modulos mantendo os mesmos endpoints:

- `core/config.py`: env, paths e carga de `.env`.
- `core/db.py`: conexao, helpers de schema e tipos.
- `domains/nfe.py`: XML, DF-e, portal, OCR e cache.
- `domains/estoque.py`: produtos, saldo, movimentos e conferencias.
- `domains/fretes.py`: fretes, escala, historico e baixa de estoque.
- `domains/vendas.py`: importacao, cache e relatorios.
- `domains/sip.py`: usuarios SIP, FreePBX, perfis e certificados.
- `services/backup.py`: backup SQL e full backup.

Cada extracao deve ser pequena: mover funcoes, manter nomes publicos quando possivel e testar antes da proxima fatia.

### Fase 3 - Separar Frontend por Dominio

Quebrar `script.js` em modulos carregados pela tela principal:

- `static/js/core/api.js`: `apiFetch`, conversores e escape.
- `static/js/core/navigation.js`: menus e troca de views.
- `static/js/modules/fretes.js`.
- `static/js/modules/estoque.js`.
- `static/js/modules/vendas.js`.
- `static/js/modules/frota.js`.
- `static/js/modules/chat-sip.js`.
- `static/js/modules/config.js`.

Antes disso, criar um teste de smoke com navegador ou uma pagina de verificacao local para garantir que as funcoes globais chamadas por `onclick` continuam expostas.

### Fase 4 - Dependencias e Runtime

1. Atualizar patch/minor primeiro:
   - Flask, mysql-connector-python, reportlab, onnxruntime, idna, urllib3 e pip.
2. Atualizar familias de seguranca com teste dedicado:
   - cryptography, pyOpenSSL, signxml e lxml.
3. Atualizar OCR/imagem em ambiente isolado:
   - Pillow e rapidocr.
4. Avaliar major de SSH:
   - paramiko 5.x pode afetar FreePBX/ESXi e precisa de teste real de conexao.
5. Registrar resultado em `requirements.txt` e nesta documentacao.

### Fase 5 - Documentacao Viva

1. Atualizar `API_E_DADOS.md` depois de cada extracao de dominio.
2. Criar uma tabela de "rotas por modulo" para orientar manutencao.
3. Marcar fluxos que dependem de ambiente real:
   - MariaDB, FreePBX, SEFAZ, OCR, cameras e ESXi.
4. Adicionar um checklist de pre-deploy em `OPERACAO_E_DEPLOY.md`.
5. Manter este arquivo como backlog tecnico ate as pendencias serem resolvidas.

## Ordem Recomendada de Execucao

1. Limpar duplicatas obvias de `script.js`.
2. Criar testes de smoke para fretes, estoque, vendas, NF-e e backup.
3. Extrair backup e helpers comuns do backend.
4. Extrair NF-e/estoque, porque sao areas grandes e com regras repetidas.
5. Extrair vendas e relatorios.
6. Atualizar dependencias em lotes pequenos.
7. Atualizar documentacao de API e operacao apos cada lote.

## Criterio de Conclusao

Uma etapa so deve ser considerada concluida quando:

- nao houver funcao duplicada nova no dominio mexido;
- testes automatizados estiverem verdes;
- a tela correspondente abrir e executar o fluxo principal;
- a documentacao indicar onde o codigo daquele dominio mora;
- nenhum arquivo de configuracao local, cache, backup ou dado operacional tiver sido incluido por engano.
