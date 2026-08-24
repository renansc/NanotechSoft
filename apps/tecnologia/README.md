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
Printer-MIB é comparado entre coletas para mostrar as páginas impressas no dia
e uma linha diária da semana corrente, iniciada no domingo. Reduções do contador
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
- `SNMP`: usa SNMP v2c somente leitura para identificação, CPU exposta pelo
  equipamento e contadores de tráfego das interfaces. Em impressoras, também
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

SNMP e exporters mostram tráfego total por interface. A identificação do IP
local ou externo que causa o consumo exige que o roteador exporte NetFlow,
sFlow, IPFIX ou ofereça uma API equivalente; isso não pode ser inferido apenas
pelos contadores SNMP.

Alguns NVRs não implementam a tabela moderna `ifXTable`, embora respondam
normalmente ao SNMP. Nesses casos, a coleta usa automaticamente a `ifTable`
clássica para nomes, velocidade e contadores de rede e ignora respostas
`No Such Object` em vez de apresentá-las como interfaces.

## Alertas

O diagnóstico sinaliza indisponibilidade, porta/DNS com falha, perda, latência,
download/upload abaixo dos mínimos e CPU, memória, disco ou tráfego acima dos
limites do equipamento. Os eventos aparecem na visão geral e as amostras ficam
no histórico por 90 dias.

O e-mail é restrito aos eventos prioritários desta etapa:

- queda do equipamento cadastrado como `INTERNET`;
- gateway offline ou instável por perda, latência ou porta indisponível;
- download ou upload abaixo do mínimo configurado no teste de velocidade;
- CPU, memória RAM ou disco no limite cadastrado (90% por padrão);
- uso da capacidade da interface de rede em 90% ou mais, quando SNMP ou o
  exporter informar a velocidade da interface.

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
- `GET /apps/tecnologia/api/history`: histórico por equipamento e período.
- `GET /apps/tecnologia/api/devices/<id>/print-usage`: páginas impressas no dia e na semana.
- `POST /apps/tecnologia/api/devices`: cadastra um equipamento (admin).
- `PUT|DELETE /apps/tecnologia/api/devices/<id>`: altera ou exclui (admin).
- `POST /apps/tecnologia/api/discover-printers`: descoberta manual (admin).
- `POST /apps/tecnologia/api/discover-computers`: descoberta manual de estações (admin).

O login é sempre o do portal. Não existe autenticação própria no módulo.
