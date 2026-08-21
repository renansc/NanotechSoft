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

Administradores podem alterar os equipamentos, limites, portas e status ativo
pela aba **Equipamentos**. A exclusão do equipamento também exclui seu histórico
de medições.

## Coleta e retenção

O monitor inicia quando o módulo é aberto e mede os equipamentos ativos a cada
60 segundos. O intervalo pode ser ajustado com `TECH_MONITOR_INTERVAL_SECONDS`,
com mínimo de 15 segundos. A coleta verifica:

- ICMP: alcance, latência média, perda e jitter;
- TCP: disponibilidade da porta configurada;
- DNS: resolução externa para o equipamento do tipo `INTERNET`.

As métricas ficam em `tecnologia_metricas` por 90 dias. O cadastro permanece em
`tecnologia_dispositivos`. O botão **Verificar agora** força uma nova amostra.

## Wi-Fi

A sonda roda no servidor Ubuntu conectado por cabo. Assim, uma falha ou aumento
de perda até o gateway ajuda a identificar indisponibilidade geral, mas não mede
canal, interferência, potência, RSSI ou roaming dos clientes Wi-Fi. Esses dados
exigem SNMP/API do roteador ou uma sonda conectada ao Wi-Fi. Quando o modelo e o
acesso administrativo do roteador estiverem disponíveis, essa integração pode
ser adicionada sem mudar o cadastro atual.

## Descoberta de impressoras

A descoberta é manual e restrita a uma rede IPv4 privada com até 254 hosts. Ela
testa apenas as portas 9100, 631 e 515 e não cadastra nada automaticamente. O
usuário administrador escolhe quais resultados deseja cadastrar.

## Rotas

- `GET /apps/tecnologia/api/overview`: equipamentos, última medição e resumo de 24h.
- `POST /apps/tecnologia/api/probe`: força uma coleta.
- `GET /apps/tecnologia/api/history`: histórico por equipamento e período.
- `POST /apps/tecnologia/api/devices`: cadastra um equipamento (admin).
- `PUT|DELETE /apps/tecnologia/api/devices/<id>`: altera ou exclui (admin).
- `POST /apps/tecnologia/api/discover-printers`: descoberta manual (admin).

O login é sempre o do portal. Não existe autenticação própria no módulo.
