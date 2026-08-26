# GPS Musical

Aplicação estática do catálogo global Nanotech para organizar repertório,
fontes de áudio e marcações de execução. O código fica em
`apps/gpsmusical/source` e é servido pelo Portal.

Os metadados locais usam `localStorage` e os arquivos de áudio locais usam
IndexedDB. Tokens OAuth e configurações nunca devem ser preenchidos no código
versionado. Arquivos exportados pela tela de backup são dados de execução e não
entram no Git.

O módulo é obrigatório no perfil `nanotech` e não faz parte do contrato da Rio
Branco, do Senhor ou do Render.
