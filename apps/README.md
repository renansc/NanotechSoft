# Apps do portal

Cada app pode ficar em uma subpasta dentro de `apps/`.

Para aparecer no menu dinamico, crie um arquivo `app.json` dentro da pasta do app:

```json
{
  "app_key": "financeiro",
  "nome": "Financeiro",
  "descricao": "Controle financeiro",
  "url": "/apps/financeiro",
  "standalone_url": "/apps/financeiro/original",
  "icone": "layout-dashboard",
  "ordem": 20,
  "ativo": true,
  "temas": ["rio_branco"],
  "menu_groups": {
    "dashboards": [{"nome": "Dashboard", "url": "/apps/financeiro"}],
    "cadastros": [],
    "workflow": [],
    "relatorios": [{"nome": "Relatorio", "url": "/apps/financeiro/relatorios"}]
  },
  "config_groups": {
    "automacao": []
  }
}
```

Tambem e possivel cadastrar apps diretamente na tabela `installed_apps`.

O arquivo `/srv/nanotechSoft/apps_liberados.txt` controla quais apps entram no deploy de um cliente.

## Metodologia de integracao

- `url` e sempre a entrada integrada ao portal, usando somente o menu principal.
- `standalone_url` e a entrada do card do app no portal; abre em outra aba e pode manter o menu original do app.
- Todo tema e global. Mesmo em `standalone_url`, o app deve receber o tema ativo do portal.
- Toda funcao que aparece no app original tambem deve aparecer em `menu_groups` ou `config_groups`, com o nome do app no rotulo do menu principal.
- Ao importar um app, conferir as telas/rotas/abas do modo original e mapear todas para os menus principais: `dashboards`, `cadastros`, `workflow`, `compras`, `financeiro`, `relatorios`, `import_export` ou `config_groups`.
