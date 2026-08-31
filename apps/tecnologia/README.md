# Tecnologia

Módulo integrado ao portal para acompanhar a rede local, o link de internet,
roteadores, servidores e impressoras. O código da interface fica em
`apps/tecnologia/source`; as rotas, a coleta e o schema fazem parte do portal.

## Equipamentos iniciais

Na primeira criação do schema são cadastrados, sem substituir cadastros
existentes:

- link externo `1.1.1.1:443`;
- roteador/DHCP `192.168.200.1:80`;
- servidor Ubuntu `192.168.200.254:443`;
- servidor Windows `192.168.200.121:445`;
- impressoras encontradas em `192.168.200.138`, `.147` e `.196`, porta 9100.
- relógio ponto em `192.168.200.110`;
- NVR em `192.168.200.210`.

Administradores podem alterar os equipamentos, limites, portas e status ativo
pela aba **Equipamentos**. A exclusão do equipamento também exclui seu histórico
de medições.

Cada equipamento possui um IP/host principal e pode receber até 12 endereços
adicionais identificados por interface, por exemplo `Wi-Fi`, `Cabo` e
`Tailscale`. Informe um endereço por linha no formato `Nome = IP`. A coleta testa
os caminhos em paralelo, mantém um único equipamento no painel e usa
automaticamente um endereço disponível para alcançar o exporter. O card mostra
o estado de cada endereço e qual deles foi usado na coleta.

## Coleta e retenção

O monitor inicia quando o módulo é aberto e mede os equipamentos ativos a cada
60 segundos. O intervalo pode ser ajustado com `TECH_MONITOR_INTERVAL_SECONDS`,
com mínimo de 15 segundos. A coleta verifica:

- ICMP: alcance, latência média, perda e jitter;
- TCP: disponibilidade da porta configurada;
- DNS: resolução externa para o equipamento do tipo `INTERNET`.

O link também recebe um teste HTTP de download e upload a cada 30 minutos. O
intervalo pode ser alterado por `TECH_SPEED_INTERVAL_SECONDS` (mínimo de 300
segundos). O teste usa quatro fluxos e, por padrão, transfere 10 MB para download
e 4 MB para upload através dos endpoints do Cloudflare Speedtest. Ajustes:

- `TECH_SPEED_DOWNLOAD_BYTES` e `TECH_SPEED_UPLOAD_BYTES`;
- `TECH_SPEED_DOWNLOAD_URL` e `TECH_SPEED_UPLOAD_URL`;
- `TECH_SPEED_TIMEOUT_SECONDS`.

O botão **Testar velocidade** força uma nova medição. Os limites mínimos de
download e upload ficam no cadastro do equipamento do tipo `INTERNET`.

As métricas ficam em `tecnologia_metricas` por 90 dias. O cadastro permanece em
`tecnologia_dispositivos`. O botão **Verificar agora** força uma nova amostra.
As datas são armazenadas em UTC e a API informa explicitamente esse fuso; o
navegador converte o histórico para o horário local, inclusive
`America/Sao_Paulo`, sem o adiantamento de três horas.
Na visão geral e na aba **Equipamentos**, clicar em um equipamento abre um card
com a última coleta, os endereços configurados e o caminho ativo. Para exporters Prometheus, o card detalha CPU, memória,
discos, tráfego, hostname, sistema operacional, build, arquitetura, interfaces
e tempo ligado quando as respectivas séries estiverem habilitadas. O próprio
card permite atualizar somente aquele equipamento.

No popup de equipamentos do tipo **Impressora**, o contador acumulado do
Printer-MIB é comparado entre coletas para mostrar as páginas impressas no dia,
na semana atual e o histórico agregado das quatro últimas semanas, iniciadas no
domingo. Reduções do contador
após manutenção ou reinício não são contabilizadas como valores negativos. O
comparativo aparece antes da seção de suprimentos e exige ao menos duas leituras
SNMP com contador de páginas. Quando o monitoramento começou depois da meia-noite,
o popup informa o horário da primeira leitura, pois páginas anteriores a ela não
podem ser reconstruídas pelo contador acumulado.

## Wi-Fi

A sonda roda no servidor Ubuntu conectado por cabo. Assim, uma falha ou aumento
de perda até o gateway ajuda a identificar indisponibilidade geral, mas não mede
canal, interferência, potência, RSSI ou roaming dos clientes Wi-Fi. Esses dados
exigem SNMP/API do roteador ou uma sonda conectada ao Wi-Fi. Quando o modelo e o
acesso administrativo do roteador estiverem disponíveis, essa integração pode
ser adicionada sem mudar o cadastro atual.

## SNMP, exporters e inventário

O cadastro aceita quatro tipos de coleta:

- `ICMP`: disponibilidade, perda, latência e porta TCP opcional;
- `TCP`: mantém ICMP e exige uma porta de serviço;
- `SNMP`: usa SNMP v2c somente leitura para identificação, CPU e discos expostos
  pelo equipamento via HOST-RESOURCES-MIB e contadores de tráfego das interfaces. Em impressoras, também
  consulta o Printer-MIB para estado, número de série, contador de páginas e
  níveis de suprimentos disponibilizados pelo fabricante. Em NVRs compatíveis,
  consulta também o ramo empresarial anunciado pelo próprio agente para mostrar
  modelo, família, número de série, firmware, sistema e capacidade de canais;
- `PROMETHEUS`: consulta `/metrics` de Node Exporter (Linux) ou Windows Exporter
  e calcula CPU, memória, maior ocupação de disco e tráfego.

Comunidades SNMP não são devolvidas pela API ou pela interface. SNMP v2c não
criptografa a comunidade na rede, portanto use uma credencial exclusiva,
somente leitura, restrita ao IP `192.168.200.254`. O container inclui as
ferramentas Net-SNMP. Para máquinas, limite as portas dos exporters ao servidor
de monitoramento (Node Exporter costuma usar 9100 e Windows Exporter, 9182).
O Notebook Renan usa o Windows Exporter em
`http://192.168.200.122:9182/metrics`; o firewall do Windows deve aceitar essa
porta somente a partir do servidor `192.168.200.254`.

A porta `9090` pertence normalmente ao servidor Prometheus. O endpoint
`http://host:9090/metrics` descreve o próprio processo do Prometheus e não
substitui os exporters de sistema. Para este módulo, configure diretamente o
Node Exporter na porta `9100` em Linux e o Windows Exporter na porta `9182` em
Windows. Um endpoint que contenha somente séries `prometheus_*` é rejeitado com
um diagnóstico específico, evitando cards de recursos vazios.

GLPI Agent e Zabbix Agent não são tratados como o mesmo protocolo. O GLPI Agent
é indicado para inventário de hardware, números de série e programas e precisa
de um servidor GLPI. O Zabbix Agent precisa de um servidor/proxy Zabbix. Nesta
etapa o portal lê o formato aberto do ecossistema Prometheus sem exigir esses
servidores adicionais.

SNMP e exporters mostram tráfego total por interface. A aba **Configuração**
pode somar download e upload dos endpoints monitorados, comparar os totais com
a capacidade contratada do link e listar os maiores consumidores no instante
da coleta. Essa soma é uma estimativa: pode incluir tráfego interno e não cobre
máquinas sem agente. A identificação exata do IP que consome a internet exige
que o roteador exporte NetFlow, sFlow, IPFIX ou ofereça uma API equivalente;
isso não pode ser inferido apenas pelos contadores SNMP.

O relatório **Ocupação do link**, disponível em Relatórios, reutiliza essas
amostras por períodos de 24 horas, 7, 30 ou 90 dias. Ele apresenta a série
histórica de download/upload em relação às capacidades contratadas, médias e
picos de cada dispositivo e o detalhamento por intervalo. Períodos maiores são
agregados em intervalos mais largos para manter a consulta responsiva. Os
percentuais só são calculados quando as capacidades de download e upload estão
informadas na Configuração e continuam sendo uma estimativa das interfaces
monitoradas, não uma atribuição WAN exata.

Alguns NVRs não implementam a tabela moderna `ifXTable`, embora respondam
normalmente ao SNMP. Nesses casos, a coleta usa automaticamente a `ifTable`
clássica para nomes, velocidade e contadores de rede e ignora respostas
`No Such Object` em vez de apresentá-las como interfaces.
Alguns firmwares de NVR também não publicam CPU ou armazenamento na
HOST-RESOURCES-MIB. O card identifica explicitamente essas métricas como não
expostas, sem tratá-las como zero ou como falha da coleta.

## Alertas

O diagnóstico sinaliza indisponibilidade, porta/DNS com falha, perda, latência,
download/upload abaixo dos mínimos e CPU, memória, disco ou tráfego acima dos
limites do equipamento. Os eventos aparecem na visão geral e as amostras ficam
no histórico por 90 dias.

Na aba **Configuração**, o administrador escolhe separadamente quais eventos
geram e-mail neste ambiente:

- queda do equipamento cadastrado como `INTERNET`;
- gateway offline ou instável por perda, latência ou porta indisponível;
- download ou upload abaixo do mínimo configurado no teste de velocidade;
- CPU, memória RAM ou disco no limite cadastrado (90% por padrão);
- uso da capacidade da interface de rede em 90% ou mais, quando SNMP ou o
  exporter informar a velocidade da interface.
- ocupação estimada do link no percentual configurado (80% como valor inicial),
  usando as capacidades contratadas de download e upload. O aviso pode listar
  até os cinco maiores consumidores monitorados com IP, download, upload e
  horário da amostra.

As preferências são salvas em `tecnologia_alertas_config`, no banco de cada
ambiente. Portanto, é possível acompanhar internet, velocidade e ocupação em
uma instalação e desativar todos os alertas de link em outra, sem variáveis ou
alterações de código. O alerta de ocupação começa desligado e só pode ser
ativado depois que as capacidades contratadas de download e upload forem
informadas.

Com exceção do gateway, quedas de equipamentos internos continuam visíveis no
painel e no histórico, mas não enviam e-mail. O alerta não é reenviado a cada minuto:
enquanto o problema continuar, há lembrete a cada 6 horas. A recuperação dos
recursos percentuais é avisada depois de cair 5 pontos abaixo do limite,
evitando mensagens repetidas por pequenas oscilações.

Os avisos do diagnóstico identificam a causa da última amostra, informam quando
o evento é somente interno e podem ser clicados para abrir diretamente o
histórico do equipamento correto. A tabela histórica mantém a mensagem da
coleta na coluna **Motivo**, como perda, latência ou porta fechada.

Por padrão, o módulo reutiliza como remetente a primeira conta habilitada do
RioB que tenha servidor SMTP, usuário e senha preenchidos em
`riobranco.gestor_email_config`. As contas POP3/IMAP continuam responsáveis
pelo recebimento; o envio usa o SMTP cadastrado na mesma conta. O endereço
abaixo é somente o destinatário do alerta:

```dotenv
TECH_ALERT_EMAIL_TO=solucoestecnologicasrenan@gmail.com
```

Quando houver mais de uma conta com SMTP, `TECH_ALERT_EMAIL_ACCOUNT_ID`
seleciona o ID desejado. As variáveis `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM` e `SMTP_USE_TLS` permanecem como substituição
opcional para ambientes que não usam as contas do RioB; quando `SMTP_HOST`
estiver vazio, a conta do RioB é usada automaticamente.

O painel **Alertas por e-mail** mostra se a configuração está pronta, a
quantidade de alertas ativos, o último envio e eventual erro. Administradores
podem usar **Enviar e-mail de teste**. O painel distingue remetente e
destinatário, e a senha nunca é devolvida pela API.
Uma recusa temporária `4xx` do provedor fica visível com o destinatário e o
código SMTP. Depois que um alerta ou teste for entregue com sucesso, as falhas
anteriores do mesmo canal são limpas para o painel não continuar exibindo um
erro já resolvido.
`TECH_ALERT_REMINDER_HOURS` altera o lembrete e
`TECH_ALERT_RECOVERY_MARGIN_PCT` altera a margem de recuperação.

## Descoberta de impressoras

A descoberta é manual e restrita a uma rede IPv4 privada com até 254 hosts. Ela
testa apenas as portas 9100, 631 e 515 e não cadastra nada automaticamente. O
usuário administrador escolhe quais resultados deseja cadastrar. Como a porta
9100 também é o padrão do Node Exporter, a varredura consulta `/metrics` e não
classifica exporters Linux/Windows como impressoras. Endereços principais ou
adicionais já vinculados a qualquer equipamento também ficam fora das sugestões.

O gráfico do histórico exibe marcações de hora no eixo horizontal. Em períodos
superiores a 36 horas, as marcações incluem também dia e mês.

## Descoberta de computadores

A aba **Equipamentos** também oferece uma varredura manual de computadores na
rede privada. Ela combina ICMP, consulta NetBIOS e portas comuns de SSH, SMB,
RDP, WinRM e exporters. Equipamentos encontrados não são cadastrados
automaticamente; o administrador confirma cada inclusão. Para computadores e
notebooks, a resposta NetBIOS também pode confirmar que a máquina está ligada
quando o firewall bloqueia ICMP.

A varredura e as rotas de cadastro comparam o IP principal, todos os endereços
adicionais e a identidade NetBIOS/exporter já coletada. Assim, cabo, Wi-Fi e
Tailscale do mesmo computador permanecem em um único equipamento; tentar
cadastrar ou atribuir a outro equipamento um endereço já vinculado retorna
conflito em vez de criar uma duplicata.

A família Windows/Linux e o nome de rede podem ser inferidos, mas Windows 10 e
Windows 11 têm comportamento de rede muito semelhante. A versão exata deve ser
confirmada localmente ou por inventário de um agente.

## Rotas

- `GET /apps/tecnologia/api/overview`: equipamentos, última medição e resumo de 24h.
- `POST /apps/tecnologia/api/probe`: força uma coleta.
- `POST /apps/tecnologia/api/alerts/test-email`: testa o SMTP (admin).
- `POST /apps/tecnologia/api/speed-test`: força download/upload do link.
- `GET /apps/tecnologia/api/speed-history`: histórico da velocidade do link.
- `GET /apps/tecnologia/api/link-usage-history`: relatório histórico da ocupação estimada do link e participação por dispositivo.
- `GET /apps/tecnologia/api/history`: histórico por equipamento e período.
- `GET /apps/tecnologia/api/devices/<id>/print-usage`: páginas impressas no dia, semana e últimas quatro semanas.
- `POST /apps/tecnologia/api/devices`: cadastra um equipamento (admin).
- `PUT|DELETE /apps/tecnologia/api/devices/<id>`: altera ou exclui (admin).
- `POST /apps/tecnologia/api/discover-printers`: descoberta manual (admin).
- `POST /apps/tecnologia/api/discover-computers`: descoberta manual de estações (admin).

O login é sempre o do portal. Não existe autenticação própria no módulo.

## Backups externos

A aba **Backup** mantém os planos executados por máquinas locais. O portal não
executa dumps durante startup, deploy ou atualização: cada plano possui um
agente independente, autenticado por token, que consulta a configuração e
reporta suas execuções em JSON.

O cadastro informa banco MySQL/MariaDB, máquina executora, pasta externa,
horários, fuso e retenções. A senha do banco não é armazenada nem devolvida pelo
portal; o agente lê a variável de ambiente indicada em `passwordEnv` na própria
máquina. Ao criar um plano, o navegador baixa uma única vez um JSON com o token.
O botão **Novo JSON** rotaciona o token e invalida o arquivo anterior.

O tipo **Arquivos e pastas** recebe até 20 caminhos locais, um por linha, e não
solicita host, banco, usuário ou senha. Esse tipo usa um repositório incremental:
a primeira execução armazena todo o conteúdo e gera um manifesto
`.files.json.gz`; as seguintes comparam tamanho e data de alteração com o último
manifesto e gravam somente arquivos novos ou alterados. Arquivos inalterados
reutilizam o objeto já existente, enquanto exclusões deixam de aparecer no novo
ponto de recuperação. O manifesto preserva a árvore, metadados e SHA-256 de cada
conteúdo. Planos MySQL/MariaDB não usam esse formato e continuam gerando um
`mysqldump` completo em `.sql.gz`. No Windows, use caminhos como
`C:\CTA\DADOS`. No Linux, um destino SMB precisa estar montado antes e deve ser
informado como `/mnt/...`; caminhos `//servidor/share` não são tratados como
montagem pelo sistema de arquivos.

Backups de arquivos antigos em `.tar.gz` não são convertidos nem removidos na
atualização do agente; eles vencem normalmente conforme a retenção do plano.
Para restaurar um ponto incremental em uma pasta nova ou vazia, execute a
operação separadamente e informe o manifesto desejado:

```bash
python3 technology_backup_agent.py \
  --restore-manifest "/backup/diario/2026-08-28/arquivos_12-00-00.files.json.gz" \
  --restore-to "/tmp/restaurado"
```

O agente valida o SHA-256 durante a restauração e não sobrescreve arquivos já
existentes. A restauração continua exigindo autorização operacional explícita;
ela nunca é chamada por execução comum, startup ou deploy.

O agente versionado fica em `tools/technology_backup_agent.py`. Na máquina
executora, instale Python 3 e `mysqldump`, copie o agente e o JSON baixado e
proteja o arquivo para que somente a conta do serviço consiga lê-lo. Exemplo:

```bash
export NANOTECH_BACKUP_DB_PASSWORD='senha-local-do-usuario-de-backup'
python3 technology_backup_agent.py --config nanotech-backup-backup-xxxx.json --validate
python3 technology_backup_agent.py --config nanotech-backup-backup-xxxx.json
```

Cada ambiente deve definir no seu próprio `.env`, não versionado, uma URL do
portal alcançável pelas máquinas executoras. Endereços de Rio Branco,
NanotechSoft, laboratório e cloud não devem ser copiados entre ambientes:

```dotenv
TECH_BACKUP_AGENT_BASE_URL=http://IP-LOCAL-DO-PORTAL:5600
```

Quando a variável fica vazia, o portal usa o mesmo protocolo, host e porta da
requisição atual. Depois de alterar a URL, gere um **Novo JSON** para o plano.
Em rede local, a comunicação HTTP não depende da CA interna, mas a porta deve
ficar restrita no firewall às máquinas executoras, pois o token do agente
trafega nesse canal. O agente aceita HTTP somente para IP privado, loopback ou
nome `.local`; não publique esse canal na internet. Em cloud ou acesso público,
use a URL HTTPS própria daquele ambiente. `--ca-file` ou a variável
`NANOTECH_BACKUP_CA_FILE` permite informar uma CA interna sem ignorar a
validação TLS.

Planos, tokens, senhas, montagens e unidades de serviço também pertencem ao
ambiente onde foram criados. Eles não são iniciados por `up.sh`, `update.sh` ou
outro deploy comum do portal; o agente é instalado separadamente em cada host.
Assim, publicar o mesmo código em outro cliente não executa nem recebe a
configuração de backup deste servidor.

No Windows, instale também o pacote de fusos com `python -m pip install tzdata`,
defina a variável no ambiente da conta do serviço e use o mesmo comando com
`python`. O caminho do HDD pode ser UNC, por exemplo
`\\192.168.200.10\e\backup Nanotechsoft`, desde que o compartilhamento `e`
exista e a conta do serviço tenha permissão de gravação. Mapas como `E:` podem
não existir para serviços; por isso UNC é preferível. No Linux, monte primeiro
o compartilhamento e configure o caminho montado.

O agente consulta o portal a cada 60 segundos e mantém a última configuração
válida em seu arquivo local de estado para continuar protegendo o banco durante
uma indisponibilidade temporária do portal. Para testar uma execução real fora
do horário, use `--run-now`; `--once` executa apenas o horário já vencido e
encerra. Instale o comando contínuo como serviço do sistema operacional, não
como parte dos comandos canônicos de deploy do repositório.

Cada plano também define os dias e as janelas em que uma execução pode começar.
Um horário vencido só é recuperado enquanto o agente ainda estiver dentro da
janela daquele dia; depois do encerramento ele aguarda o próximo dia permitido.
Isso evita iniciar uma cópia longa quando o servidor de origem já está perto de
ser desligado. `--run-now` continua ignorando a janela por ser uma ação manual.
Para o CTA, cuja primeira carga observada levou até 2h35, o plano operacional
usa início às 07:00, janela de segunda a sexta 07:00–17:00, sábado 07:00–11:00
e domingo sem execução. Backups de arquivos usam o repositório incremental;
planos MySQL/MariaDB continuam com `mysqldump` completo.

### Inicialização automática

No Linux, instale uma unidade `systemd` com `After=network-online.target`,
`Restart=always` e `WantedBy=multi-user.target`. Quando o destino usa
`x-systemd.automount` com tempo de inatividade, não use `RequiresMountsFor=`: o
acesso ao caminho já aciona a montagem e uma dependência rígida encerraria o
agente quando o CIFS fosse desmontado por ociosidade. A senha do banco fica em
um `EnvironmentFile` com permissão `600`; planos do tipo arquivos não precisam
dessa variável.

No Windows, crie uma tarefa no Agendador de Tarefas acionada **Ao iniciar o
computador**, executando `python.exe technology_backup_agent.py --config
plano.json`. Configure reinício automático em caso de falha e execute pela conta
que tenha leitura nas origens COBOL e gravação no compartilhamento de destino.
O botão **Instalador Windows** baixa o PowerShell que automatiza essa instalação.
Abra o PowerShell como administrador e execute, na pasta dos três arquivos:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_technology_backup_windows.ps1 -Agent .\technology_backup_agent.py -Config .\nanotech-backup-backup-xxxx.json
```

O instalador pede a credencial da conta do serviço sem gravá-la no plano, copia
o agente para `C:\ProgramData\NanotechSoft\Backup`, restringe o token a SYSTEM e
administradores, valida o JSON e inicia uma tarefa com gatilho de boot e reinício
automático. Ele também pode ser executado novamente para atualizar uma instalação:
nesse caso, encerra a tarefa anterior antes de substituir o agente e a inicia com
a nova versão ao final.

### Organização e retenção

- `diario/YYYY-MM-DD`: todas as execuções, como 08:00, 12:00 e 17:00;
- `semana/AAAA-Wnn`: cópia do último backup de cada dia;
- `mes/AAAA-MM`: cópia do último backup de domingo de cada semana;
- pasta de nuvem opcional: recebe somente a promoção mensal.

Quando `diario`, `semana` e `mes` pertencem ao mesmo volume, o agente tenta usar
hard links nas promoções. Para banco, as pastas continuam apresentando dumps
completos. Para arquivos, cada pasta apresenta um manifesto completo que aponta
para o depósito deduplicado `arquivos_incrementais/objetos`; objetos deixam de
ser removidos enquanto algum manifesto retido ainda os referencia. Se o volume
não suportar hard links, o agente faz uma cópia normal do manifesto. Na promoção
mensal para nuvem, o primeiro envio copia os objetos necessários e os seguintes
enviam somente objetos ainda ausentes, além do novo manifesto.

Cada dump é comprimido como `.sql.gz`; cada ponto de arquivos usa um manifesto
comprimido `.files.json.gz`. Ambos são calculados com SHA-256 antes de serem
reportados como concluídos. A retenção remove arquivos expirados apenas dentro
das três pastas gerenciadas e, no modo incremental, coleta somente objetos que
nenhum manifesto retido referencia. Se algum manifesto estiver ilegível, essa
coleta é ignorada para não arriscar conteúdo ainda necessário. Excluir um plano
no portal não remove arquivos do HDD. O plano registra a produção do backup,
mas testes periódicos de restauração continuam sendo uma operação separada e
explicitamente autorizada.

Rotas administrativas e do agente:

- `GET|POST /apps/tecnologia/api/backup/jobs`;
- `PUT|DELETE /apps/tecnologia/api/backup/jobs/<id>`;
- `POST /apps/tecnologia/api/backup/jobs/<id>/rotate-token`;
- `GET /apps/tecnologia/api/backup/agent-script`;
- `GET /apps/tecnologia/api/backup/agent/<agent_id>/config` com Bearer token;
- `POST /apps/tecnologia/api/backup/agent/<agent_id>/report` com Bearer token e JSON.
