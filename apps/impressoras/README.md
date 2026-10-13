# Impressoras

Modulo integrado ao portal para operar as filas do CUPS da maquina fisica. No
deploy Nanotech ele aparece como aplicativo; no Rio Branco suas tarefas entram
nos menus globais. Login, sessao, senha e autorizacoes continuam exclusivamente
no portal.

## Funcoes

- **Workflow > Impressoras > Fila segura** recebe tanto arquivos enviados pela
  tela quanto trabalhos enviados por computadores clientes para as filas do
  servidor. O trabalho so e retomado depois que o proprio usuario informa
  novamente a senha do portal. Para trabalhos externos, o usuario CUPS precisa
  corresponder ao login do portal ou possuir um vinculo administrativo.
- **Monitor > Impressoras > Estado das impressoras** consulta dinamicamente as
  filas existentes, modelo, local, estado e aceitacao de trabalhos.
- **Relatorios > Impressoras > Historico de impressoes** registra quem enviou,
  documento, impressora, paginas solicitadas/concluidas expostas pelo driver,
  copias, tamanho, estado, data e hora.
- **Configurar > Impressoras > Gerenciar filas CUPS** pausa/retoma a impressora
  e aceita/rejeita novos trabalhos. Essas acoes exigem autorizacao administrativa
  no CUPS e o recurso `impressoras:gerenciar`. A mesma tela vincula o nome de
  usuario enviado pelo computador/CUPS a uma conta ativa do portal e reaplica o
  vinculo aos trabalhos anteriores.

Recursos em Config > Usuarios e acessos: `fila`, `monitor`, `historico` e
`gerenciar`. Nenhum acesso e concedido automaticamente. APIs e itens individuais
do menu verificam as mesmas autorizacoes no servidor.

## Conexao com CUPS

Por padrao, o container recebe o socket Unix do CUPS da maquina fisica. Isso
evita expor o IPP na rede e evita a rejeicao de hostnames externos pelo `cupsd`:

```dotenv
CUPS_SOCKET=/run/cups/cups.sock
CUPS_SERVER=/run/cups/cups.sock
CUPS_PORT=
CUPS_USER=root
CUPS_PASSWORD=
CUPS_GUARD_INTERVAL_SECONDS=10
```

O socket e montado com `create_host_path: false`, portanto o deploy falha de
forma explicita se o CUPS nao estiver instalado ou ativo. Em uma instalacao
remota, `CUPS_SERVER` e `CUPS_PORT` podem apontar para um servidor IPP que aceite
o hostname do container. Se a politica exigir senha, grave-a somente no `.env`
local; ela nao aparece na interface nem no banco. O modulo nao cadastra, exclui
ou altera impressoras automaticamente.

As filas sao descobertas pelo CUPS em tempo real e nao ficam fixadas no codigo.

O servico `cups-guard` executa a operacao IPP `Hold-New-Jobs` e configura
`job-hold-until-default=indefinite` em todas as filas encontradas. Ele reaplica
a politica periodicamente para cobrir filas recriadas pelo `cups-browsed`. A
liberacao de um trabalho nao desativa a retencao dos trabalhos seguintes.

## Retencao e auditoria

`impressoras_trabalhos` guarda metadados e eventos, nunca o conteudo enviado. O
arquivo temporario e removido assim que o CUPS confirma o spool. A senha digitada
na liberacao e comparada ao hash do usuario e nunca e persistida. Cinco erros em
cinco minutos bloqueiam temporariamente novas tentativas naquele processo.

O numero real de paginas depende de o filtro/driver CUPS publicar
`job-impressions-completed` ou `job-media-sheets-completed`; quando ele nao
publica, a tela mostra o valor solicitado ou indisponivel, sem inventar contagem.
Para nao perder trabalhos externos, mantenha o historico de jobs habilitado no
CUPS. A sincronizacao ocorre ao consultar o modulo.

Clientes Windows/Linux precisam apontar para as filas compartilhadas deste
servidor CUPS. Trabalhos enviados diretamente ao IP da impressora fisica nao
passam pelo servidor e, portanto, nao podem ser retidos pelo portal. O nome de
usuario informado pelo cliente CUPS deve ser igual ao login no portal para que
o trabalho apareca na fila pessoal correta, ou deve existir um vinculo em
**Configurar > Impressoras > Gerenciar filas CUPS**. Quando a consulta IPP omite
o proprietario por privacidade, o portal recupera somente o nome do usuario pelo
`lpstat` local; o conteudo do documento nao e lido. O cliente deve herdar o padrao da
fila e nao pode ser configurado por um administrador para forcar `-H immediate`
ou `job-hold-until=no-hold`: o CUPS define `Hold-New-Jobs` como retencao por
padrao e permite que uma solicitacao IPP explicita substitua esse padrao.

O futuro totem RFID deve identificar um usuario do portal e chamar o mesmo
servico de liberacao; nao deve criar outro login ou armazenar a senha do usuario.

## Rotas

- `GET /apps/impressoras/api/overview` — filas, estado e trabalhos do usuario;
- `GET /apps/impressoras/api/jobs?scope=mine|all` — fila pessoal ou historico;
- `POST /apps/impressoras/api/jobs` — envia arquivo retido;
- `POST /apps/impressoras/api/jobs/release-all` — libera todos com senha;
- `POST /apps/impressoras/api/jobs/<id>/release|cancel` — libera/cancela;
- `GET|POST /apps/impressoras/api/user-links` — consulta ou salva vinculos;
- `DELETE /apps/impressoras/api/user-links/<id>` — remove um vinculo;
- `POST /apps/impressoras/api/printers/<fila>/<pause|resume|accept|reject>` —
  administra a fila.

Escritas permanecem bloqueadas no modo cloud somente leitura.
