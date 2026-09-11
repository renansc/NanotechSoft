# Empacotadora Rodighero ER-1500

Guia de consulta preparado em 8 de setembro de 2026 a partir das fotos
`IMG_0927.JPG` a `IMG_1010.JPG` fornecidas pela operação. O PDF fotografado
fica disponível na tela **Automação > Documentação**.

## Identificação confirmada

- Tipo: empacotadora com seladora e túnel de encolhimento.
- Fabricante: Rodighero Máquinas e Equipamentos Industriais Ltda.
- Modelo: ER-1500.
- Série: 104.
- Fabricação: março de 2024.
- Produção nominal: 1.500 pacotes/hora.
- Alimentação do equipamento fotografado: 220 V, 60 Hz.
- Potência instalada: 59 kVA; corrente de referência em 220 V: 154 A.
- Tensão auxiliar: 24 VCC.
- Aquecimento do túnel: elétrico.
- Ar comprimido: consumo aproximado de 80 l/min a 6 bar.

O manual informa 6 bar como pressão nominal e, na inspeção diária, a faixa de
4,5 a 6 bar. O monitoramento usa essa faixa como referência inicial; qualquer
mudança deve ser validada pela manutenção.

## Monitoramento criado

A rota `POST /api/maquinas/empacotadora-rodighero-er1500/leituras` recebe um
objeto `pontos` com produção, contador, pressão, temperaturas, velocidades,
emergência e alarme geral. Ela é somente de leitura do ponto de vista da
máquina: não há endpoint que escreva no CLP.

As fotos mostram CLP, IHM, inversores e servoacionamento, mas não apresentam
um mapa confirmado de registradores, IP ou protocolo liberado. A aquisição
deve ser feita por gateway isolado, contatos auxiliares ou interface oficial
aprovada pelo fabricante. Não se deve sondar ou escrever registradores por
tentativa.

## Operação resumida

A IHM documentada oferece os comandos de esvaziar a esteira, liberar entrada,
aquecer a barra de solda, automático da seladora, automático do túnel,
contador, alarmes, ajustes e manual. Os ajustes incluem velocidade da seladora,
tempo de selagem, retardo das bandeiras de entrada, tempo da solda de emenda,
desembaraçador, altura do pacote, velocidade e resfriamento do túnel e perfil
do servo da barra de solda.

## Plano de manutenção extraído do manual

- Diária: correntes e esteiras, guias, rolo de tração, navalha, barra de solda,
  temperaturas e pressão pneumática.
- Semanal, com bloqueio e máquina desenergizada: aperto das conexões elétricas
  das resistências da barra e do túnel.
- Redutores GSA: troca de óleo mineral após um ano ou 2.000 horas; óleo
  sintético após dois anos ou 20.000 horas.
- Pneumática: óleo classe C-10, referência de uma gota a cada 100 ciclos e
  correção de vazamentos/reparos dos cilindros.
- A cada 500 horas: lubrificar correntes e partes móveis; mancais com rolamento
  devem ser lubrificados mensalmente.

## Segurança e limites

Este resumo não substitui o manual do fabricante, análise de risco, NR-10,
NR-12, bloqueio e etiquetagem. Setpoints de temperatura e velocidade variam
com produto e filme; por isso, ficaram sem alarmes numéricos até a validação em
campo. Proteções e intertravamentos nunca podem depender do portal.
