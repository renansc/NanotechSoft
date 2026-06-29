# NanotechSoft

Portal Flask + MySQL para centralizar apps instalados dinamicamente.

## Acesso inicial

- Usuario: `admin`
- Senha: `admin`

No primeiro acesso o sistema cria o banco `notechsoft`, as tabelas base e o usuario admin.

## Rodar localmente

```bash
cd NanotechSoft
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Abra `http://127.0.0.1:5600`.

## MySQL com Docker

```bash
cd NanotechSoft
cp .env.example .env
docker compose up -d mysql
```

Esse compose publica o banco na porta `3307` por padrao para nao conflitar com outros MySQL locais.

Com o banco do compose, mantenha `NS_DB_PORT=3307` no `.env`.

## Apps dinamicos

Os apps ficam dentro de `apps/`. Cada subpasta pode ter um `app.json`; tambem existe a tabela `installed_apps` para cadastro via banco.

O arquivo `apps_liberados.txt` define quais apps aparecem no portal e devem ser carregados no deploy do cliente. Nesta etapa, os apps liberados sao `automacao` e `financeiro`.

## Codigo dos apps

Esta plataforma nao deve depender de codigo em outros diretorios do servidor. O codigo de cada app deve ficar dentro da propria pasta do projeto:

- apps Flask/servicos: `apps/<app>/source`
- apps estaticos: `apps/<app>/source`
- Financeiro integrado: `apps/financeiro`
- RioB e modulos locais: `apps/riob/source`, `apps/riob-cameras/source`, `apps/riob-email/source`, `apps/riob-esxi/source` e `apps/riob-xml/source`

Arquivos operacionais gerados em uso, como bancos SQLite, anexos, XMLs enviados, uploads e streams `.m3u8`, ficam ignorados pelo Git.

Os manifests podem separar atalhos em `dashboards`, `cadastros`, `workflow`, `compras`, `financeiro`, `relatorios` e `import_export`; configuracoes especificas entram em `config_groups`.

## Permissoes por usuario

Usuarios com `perfil='admin'` acessam todos os apps e funcoes.

Usuarios comuns dependem da tabela `usuario_app_permissoes`:

- `app_key`: app liberado, como `financeiro` ou `automacao`
- `recurso`: funcao do app, como `dashboard`, `contas`, `categorias`, `compras`, `pagar`, `receber`, `config`; use `*` para liberar o app inteiro
- `permitido`: `1` libera o recurso

O menu principal e as abas internas do financeiro ocultam recursos sem permissao.

## Financeiro

O app financeiro fica em `apps/financeiro` e roda integrado ao shell do NanotechSoft. Os dados foram migrados do backup JSON inicial para MySQL nas tabelas `financeiro_registros` e `financeiro_config`.

O tema padrao do portal continua sendo `Rio Branco`. O tema original do financeiro fica disponivel como `Fin Blue` no seletor de temas, sem ser aplicado automaticamente ao abrir o app.
