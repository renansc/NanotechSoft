# Brix Zegla Unimix 20.000 L

Guia de consulta preparado em 8 de setembro de 2026 a partir das fotos
`IMG_1014.JPG` a `IMG_1035.JPG` fornecidas pela operação. O PDF fotografado
fica disponível na tela **Automação > Documentação**.

## Identificação confirmada

- Fabricante: Zegla Indústria de Máquinas para Bebidas Ltda.
- Conjunto: Unimix 20.000 L.
- Modelo: RZ-UC-20.
- Código do desenho: 2000155283.
- Pedido: PV.0078-02.06.20.
- Liberação inicial dos diagramas: 10/11/2020; revisão da proteção da bomba
  desareadora: 07/10/2021.
- Tensão de rede: 220 VCA.
- Tensão de comando: 24 VCC.
- Frequência: 60 Hz.
- Potência: 21 kW.
- Corrente nominal: 72,6 A.

## Conteúdo do conjunto fotografado

As folhas cobrem vistas do skid/tanque, layout do painel, níveis alto e baixo,
acionamentos, identificação de cabos/TAGs, lista de materiais, diagramas de
comando e o painel real. A revisão do caderno destaca a proteção da bomba
desareadora.

## Monitoramento criado

A rota `POST /api/maquinas/brix-zegla-unimix-20000l/leituras` recebe nível
baixo/alto, estado do agitador, estado e falha da bomba desareadora, corrente
total, emergência e alarme geral. O serviço registra histórico e eleva o
status da máquina quando um ponto de falha fica ativo ou a corrente total
ultrapassa a referência nominal cadastrada.

O valor de 72,6 A é uma referência global de placa/desenho, não substitui os
ajustes individuais das proteções. Antes de ligar um gateway, a engenharia deve
confirmar a corrente normal em cada receita e os contatos auxiliares realmente
disponíveis.

## Padrão de TAGs do caderno

Os desenhos orientam a identificação de cabos pelo número sequencial, painel
e régua de origem, painel/régua de destino ou componente. Esse padrão deve ser
preservado ao instalar o gateway para que a nova fiação continue rastreável no
diagrama.

## Segurança e limites

A integração é somente de leitura e não pode contornar sensores de segurança,
níveis, proteção da bomba ou emergência. Trabalhos no painel de 220 V exigem
bloqueio, verificação de ausência de tensão e profissional habilitado. As fotos
não fornecem IP do CLP, mapa de registradores ou protocolo de telemetria; esses
dados devem ser levantados em campo ou obtidos com a Zegla.
