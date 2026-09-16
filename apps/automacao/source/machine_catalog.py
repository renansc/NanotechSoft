"""Catalogo versionado das maquinas industriais do Rio Branco.

As fontes incluem manuais fotografados e o protocolo de comunicacao da Cyklop
fornecidos pela operacao. Enderecos, modelos e parametros nao confirmados
permanecem fora do catalogo.
"""

import os

MACHINES = [
    {
        "slug": "empacotadora-rodighero-er1500",
        "nome": "Empacotadora Rodighero ER-1500",
        "tipo": "Empacotadora e tunel de encolhimento",
        "fabricante": "Rodighero Maquinas e Equipamentos Industriais Ltda.",
        "modelo": "ER-1500",
        "numero_serie": "104",
        "fabricacao": "03/2024",
        "setor": "Envase",
        "protocolo": "gateway_http",
        "resumo": "Empacotadora automatica com seladora e tunel eletrico, capacidade nominal de 1.500 pacotes/hora.",
        "especificacoes": [
            ("Capacidade nominal", "1.500 pacotes/h"),
            ("Alimentacao instalada", "220 V / 60 Hz"),
            ("Potencia instalada", "59 kVA"),
            ("Corrente de referencia em 220 V", "154 A"),
            ("Comando", "24 VCC"),
            ("Ar comprimido", "80 l/min a 6 bar"),
            ("Faixa indicada para inspecao", "4,5 a 6 bar"),
            ("Aquecimento do tunel", "Eletrico"),
        ],
        "pontos": [
            {
                "slug": "producao_pacotes_h",
                "nome": "Producao instantanea",
                "grupo": "Producao",
                "tipo": "numero",
                "unidade": "pacotes/h",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "Contador da IHM ou sensor de saida",
            },
            {
                "slug": "contador_pacotes",
                "nome": "Contador acumulado",
                "grupo": "Producao",
                "tipo": "contador",
                "unidade": "pacotes",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "Tela Contador da IHM",
            },
            {
                "slug": "pressao_ar_bar",
                "nome": "Pressao do ar comprimido",
                "grupo": "Utilidades",
                "tipo": "numero",
                "unidade": "bar",
                "limite_min": 4.5,
                "limite_max": 6.0,
                "alarme_quando": None,
                "origem": "Transmissor de pressao no conjunto pneumático",
            },
            {
                "slug": "temperatura_solda_c",
                "nome": "Temperatura da barra de solda",
                "grupo": "Temperaturas",
                "tipo": "numero",
                "unidade": "°C",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "Controlador de temperatura",
            },
            {
                "slug": "temperatura_tunel_c",
                "nome": "Temperatura do tunel",
                "grupo": "Temperaturas",
                "tipo": "numero",
                "unidade": "°C",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "Controlador de temperatura",
            },
            {
                "slug": "velocidade_seladora_m_min",
                "nome": "Velocidade da seladora",
                "grupo": "Movimento",
                "tipo": "numero",
                "unidade": "m/min",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "IHM / inversor da seladora",
            },
            {
                "slug": "velocidade_tunel_m_min",
                "nome": "Velocidade da esteira do tunel",
                "grupo": "Movimento",
                "tipo": "numero",
                "unidade": "m/min",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "IHM / inversor do tunel",
            },
            {
                "slug": "emergencia_acionada",
                "nome": "Emergencia acionada",
                "grupo": "Seguranca",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": True,
                "origem": "Circuito de seguranca",
            },
            {
                "slug": "alarme_maquina",
                "nome": "Alarme geral da maquina",
                "grupo": "Alarmes",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": True,
                "origem": "Tela Alarmes / CLP",
            },
        ],
        "documentacao": {
            "titulo": "Guia tecnico da Empacotadora Rodighero ER-1500",
            "arquivo": "documentos/manual-fotografado-rodighero-er1500.pdf",
            "fontes": "Fotos IMG_0929 a IMG_1010 e registros do painel IMG_0927/IMG_0928.",
            "operacao": [
                "A tela inicial da IHM concentra seladora, tunel, contador, alarmes, ajustes e comandos manuais.",
                "O processo automatico da seladora exige habilitacao e liberacao de entrada; o tunel possui automatico e tempo de resfriamento.",
                "Os ajustes documentados incluem velocidades, tempo de selagem, retardo de entrada, altura do pacote e parametros do servo da barra de solda.",
            ],
            "manutencao": [
                "Diariamente: inspecionar correntes, esteiras, guias, rolo de tracao, navalha, barra de solda, temperaturas e pressao do ar.",
                "Semanalmente, com a maquina desenergizada: conferir o aperto das conexoes das resistencias da barra e do tunel.",
                "Redutores GSA: oleo mineral apos 1 ano ou 2.000 h; sintetico apos 2 anos ou 20.000 h, conforme o manual.",
                "Sistema pneumatico: oleo classe C-10 e referencia de uma gota a cada 100 ciclos; corrigir vazamentos e reparos de cilindros.",
                "A cada 500 h: lubrificar correntes e partes moveis; mancais com rolamentos devem ser lubrificados mensalmente.",
            ],
            "seguranca": [
                "Intervencoes eletricas, mecanicas ou pneumaticas exigem bloqueio, desenergizacao e equipe habilitada.",
                "Os limites do monitoramento nao substituem protecoes, intertravamentos, relés de seguranca nem as instrucoes originais do fabricante.",
            ],
            "lacunas": [
                "As fotos nao informam IP do CLP, mapa de registradores ou protocolo liberado para telemetria.",
                "Setpoints de temperatura e velocidade dependem do produto e devem ser validados pela operacao antes de criar alarmes.",
            ],
        },
    },
    {
        "slug": "brix-zegla-unimix-20000l",
        "nome": "Brix Zegla Unimix 20.000 L",
        "tipo": "Unidade de mistura e desareacao",
        "fabricante": "Zegla Industria de Maquinas para Bebidas Ltda.",
        "modelo": "RZ-UC-20",
        "numero_serie": "",
        "fabricacao": "Projeto 2020 / revisao 2021",
        "setor": "Processo",
        "protocolo": "gateway_http",
        "resumo": "Unimix de 20.000 litros com tanque, agitacao, bomba desareadora, niveis e painel de comando.",
        "especificacoes": [
            ("Capacidade", "20.000 L"),
            ("Modelo", "RZ-UC-20"),
            ("Tensao de rede", "220 VCA"),
            ("Tensao de comando", "24 VCC"),
            ("Frequencia", "60 Hz"),
            ("Potencia instalada", "21 kW"),
            ("Corrente nominal", "72,6 A"),
            ("Codigo do desenho", "2000155283"),
            ("Numero do pedido", "PV.0078-02.06.20"),
        ],
        "pontos": [
            {
                "slug": "nivel_baixo",
                "nome": "Sensor de nivel baixo",
                "grupo": "Nivel",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "Instrumento de nivel baixo do diagrama",
            },
            {
                "slug": "nivel_alto",
                "nome": "Sensor de nivel alto",
                "grupo": "Nivel",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "Instrumento de nivel alto do diagrama",
            },
            {
                "slug": "agitador_ligado",
                "nome": "Agitador ligado",
                "grupo": "Acionamentos",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "Contator / retorno do agitador",
            },
            {
                "slug": "bomba_desareadora_ligada",
                "nome": "Bomba desareadora ligada",
                "grupo": "Acionamentos",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": None,
                "origem": "Contator / retorno da bomba",
            },
            {
                "slug": "falha_bomba_desareadora",
                "nome": "Falha da bomba desareadora",
                "grupo": "Alarmes",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": True,
                "origem": "Protecao revisada no diagrama eletrico",
            },
            {
                "slug": "corrente_total_a",
                "nome": "Corrente total",
                "grupo": "Eletrica",
                "tipo": "numero",
                "unidade": "A",
                "limite_min": None,
                "limite_max": 72.6,
                "alarme_quando": None,
                "origem": "Medidor de energia no alimentador",
            },
            {
                "slug": "emergencia_acionada",
                "nome": "Emergencia acionada",
                "grupo": "Seguranca",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": True,
                "origem": "Circuito de seguranca",
            },
            {
                "slug": "alarme_maquina",
                "nome": "Alarme geral da maquina",
                "grupo": "Alarmes",
                "tipo": "booleano",
                "unidade": "",
                "limite_min": None,
                "limite_max": None,
                "alarme_quando": True,
                "origem": "Painel / rele de alarme",
            },
        ],
        "documentacao": {
            "titulo": "Guia tecnico da Brix Zegla Unimix 20.000 L",
            "arquivo": "documentos/diagramas-fotografados-zegla-unimix-20000l.pdf",
            "fontes": "Fotos IMG_1014 a IMG_1035 do conjunto de desenhos eletricos e mecanicos.",
            "operacao": [
                "Os desenhos identificam tanque Unimix, circuito de nivel alto/baixo, acionamentos e bomba desareadora.",
                "O painel possui comando local com botoeiras e sinalizadores; os TAGs dos cabos seguem o padrao painel/regua/componente descrito no caderno.",
                "A telemetria proposta e somente de leitura e deve usar contatos auxiliares isolados ou gateway aprovado pela engenharia.",
            ],
            "manutencao": [
                "Registrar horas dos acionamentos e ocorrencias das protecoes para orientar manutencao preventiva.",
                "Conferir periodicamente sensores de nivel, contatores, relés termicos, ventilacao e aperto dos bornes com o painel desenergizado.",
                "Usar o codigo de desenho 2000155283 e o pedido PV.0078-02.06.20 ao localizar folhas e componentes.",
            ],
            "seguranca": [
                "Nao derivar alimentacao de sensores do circuito de seguranca e nao contornar protecoes da bomba, nivel ou emergencia.",
                "Intervencoes no painel de 220 V exigem bloqueio, verificacao de ausencia de tensao e profissional habilitado.",
            ],
            "lacunas": [
                "O conjunto fotografado nao fornece um mapa de comunicacao, IP de CLP ou registradores de telemetria.",
                "Correntes individuais, setpoints de nivel e logica de permissivos devem ser conferidos no equipamento antes da integracao definitiva.",
            ],
        },
    },
]


MACHINES.append({
    "slug": "impressora-laser-cyklop",
    "nome": "Impressora a laser Cyklop",
    "tipo": "Impressora / marcadora a laser",
    "fabricante": "Cyklop",
    "modelo": "Nao informado",
    "numero_serie": "",
    "fabricacao": "",
    "setor": "A confirmar",
    "cliente_deploy_id": "rio-branco",
    "protocolo": "gateway_http",
    "resumo": "Marcadora a laser Cyklop com protocolo N8 V1.2 (TCP ou RS232). Monitoramento preparado para receber estado e contadores pelo gateway.",
    "especificacoes": [
        ("Marca informada pela operacao", "Cyklop"),
        ("Documento", "Laser communication protocol N8 V1.2.pdf"),
        ("Versao do protocolo", "V1.2"),
        ("Interfaces documentadas", "TCP e RS232 (User port / Service port)"),
        ("Codificacao", "UTF-8"),
        ("Terminador padrao", ";; (configuravel na interface)"),
        ("Modelo, serie e setor", "A confirmar no equipamento; N8 consta no nome do arquivo"),
    ],
    "pontos": [
        {
            "slug": "placa_conectada", "nome": "Conexao com a placa",
            "grupo": "Comunicacao", "tipo": "booleano", "unidade": "",
            "limite_min": None, "limite_max": None, "alarme_quando": False,
            "origem": "GetLinkStatus: 1 = conectada; 0 = desconectada (nao e teste de rede)",
        },
        {
            "slug": "estado_marcacao", "nome": "Estado de marcacao (0 a 7)",
            "grupo": "Estado", "tipo": "numero", "unidade": "",
            "limite_min": None, "limite_max": None, "alarme_quando": None,
            "origem": "GetMarkStatus / MarkStatus; legenda no guia de comunicacao",
        },
        {
            "slug": "contador_total", "nome": "Total de marcacoes",
            "grupo": "Producao", "tipo": "contador", "unidade": "marcacoes",
            "limite_min": None, "limite_max": None, "alarme_quando": None,
            "origem": "GetCount (campo 1), GetMarkedCount ou MarkCount",
        },
        {
            "slug": "contador_atual", "nome": "Contagem atual de marcacoes",
            "grupo": "Producao", "tipo": "contador", "unidade": "marcacoes",
            "limite_min": None, "limite_max": None, "alarme_quando": None,
            "origem": "GetCount (campo 2)",
        },
        {
            "slug": "marcacoes_perdidas", "nome": "Marcacoes perdidas (acumulado)",
            "grupo": "Producao", "tipo": "contador", "unidade": "marcacoes",
            "limite_min": None, "limite_max": None, "alarme_quando": None,
            "origem": "GetCount (campo 3), GetMissedCount ou MissCount",
        },
        {
            "slug": "tempo_marcacao_ms", "nome": "Tempo de uma marcacao",
            "grupo": "Producao", "tipo": "numero", "unidade": "ms",
            "limite_min": None, "limite_max": None, "alarme_quando": None,
            "origem": "GetCount (campo 4)",
        },
    ],
    "documentacao": {
        "titulo": "Protocolo de comunicacao da impressora a laser Cyklop — N8 V1.2",
        "arquivo": "documentos/protocolo-comunicacao-laser-cyklop-n8-v1.2.pdf",
        "rotulo_pdf": "Protocolo de comunicação em PDF",
        "fontes": "Laser communication protocol N8 V1.2.pdf, fornecido pela operacao (19 paginas). Marca Cyklop informada pela operacao; o PDF nao confirma o modelo fisico.",
        "operacao": [
            "Comunicacao TCP ou RS232, dados UTF-8 e terminador padrao ;;. Inicio, Device ID e fim devem corresponder a configuracao da interface.",
            "Consultas previstas: GetLinkStatus;;, GetMarkStatus;; e GetCount;;. GetCount retorna total, atual, perdidas e tempo de uma marcacao em ms, separados por virgula.",
            "GetMarkStatus: 0 = ocioso; 1 = simulacao; 2 = marcacao; 3 = pre-visualizacao; 4 = correcao do laser; 5 = correcao da luz vermelha; 6 = emissao forcada do laser; 7 = marcacao rotativa.",
            "MarkStatus, MarkCount e MissCount sao retornos espontaneos e dependem de habilitacao na interface da maquina.",
            "O cadastro recebe leituras pelo gateway HTTP existente. Nao existe coletor TCP/RS232 automatico para a Cyklop nesta entrega; permanece aguardando ate receber telemetria real.",
        ],
        "manutencao": [
            "Este arquivo e um protocolo de comunicacao; nao contem plano de manutencao mecanica, eletrica ou optica da impressora.",
        ],
        "seguranca": [
            "A integracao de monitoramento utiliza consultas de leitura. Comandos de acionamento, configuracao, limpeza de contadores e alteracao de mensagens descritos no PDF nao sao executados pelo portal.",
        ],
        "lacunas": [
            "Confirmar modelo, numero de serie, setor, IP/porta TCP ou parametros RS232, Device ID e delimitadores configurados.",
            "Implementar e validar o gateway de leitura antes da coleta. Contadores acumulados de perdas nao representam, por si, uma falha ativa; limites dependem de validacao operacional.",
        ],
    },
})


# Documentos de equipamentos que ainda nao possuem pontos de monitoramento.
# Nao entram em seed_machines nem reutilizam a identidade de outra maquina.
DOCUMENTATION_ONLY_MACHINES = [
    {
        "slug": "envasadora-zegla-40-50-10-ga",
        "nome": "Envasadora Zegla 40/50/10 GA",
        "tipo": "Enchedora de garrafas",
        "fabricante": "Zegla",
        "modelo": "RZ-RET-G-40/50/10-GA-GII",
        "somente_documentacao": True,
        "resumo": "Documentacao fotografada da enchedora de garrafas Zegla, identificada pelo desenho 2000164575.",
        "especificacoes": [
            ("Equipamento", "Enchedora de garrafas"),
            ("Fabricante", "Zegla"),
            ("Modelo na capa", "RZ-RET-G-40/50/10-GA-GII"),
            ("Codigo do desenho", "2000164575"),
            ("Pedido", "PV.0078-01.06.20"),
            ("Data na capa", "16/02/2021"),
        ],
        "pontos": [],
        "documentacao": {
            "titulo": "Manual da Envasadora Zegla 40/50/10 GA",
            "arquivo": "documentos/envasadora-zegla-40-50-10-ga.pdf",
            "fontes": "PDF fotografado existente em ProjetoEnchedora (14 paginas). Identificacao conferida na foto da capa IMG_0849.JPG e confirmada pela operacao.",
        },
    },
]

DOCUMENTED_MACHINES = [*MACHINES, *DOCUMENTATION_ONLY_MACHINES]


def documented_machine_by_slug(slug):
    return next((machine for machine in DOCUMENTED_MACHINES if machine["slug"] == slug), None)


def machine_by_slug(slug):
    return next((machine for machine in MACHINES if machine["slug"] == slug), None)


def seed_machines(conn):
    """Cria o catalogo sem sobrescrever ajustes feitos pela operacao."""
    for machine in MACHINES:
        cliente = machine.get("cliente_deploy_id", "rio-branco")
        if cliente and cliente != (os.getenv("CLIENTE_DEPLOY_ID") or os.getenv("NANOTECH_DEPLOY_PROFILE")):
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO maquinas(
                slug, nome, tipo, fabricante, modelo, numero_serie,
                fabricacao, setor, protocolo, resumo
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                machine["slug"],
                machine["nome"],
                machine["tipo"],
                machine["fabricante"],
                machine["modelo"],
                machine["numero_serie"],
                machine["fabricacao"],
                machine["setor"],
                machine["protocolo"],
                machine["resumo"],
            ),
        )
        row = conn.execute(
            "SELECT id FROM maquinas WHERE slug = ?",
            (machine["slug"],),
        ).fetchone()
        for point in machine["pontos"]:
            conn.execute(
                """
                INSERT OR IGNORE INTO maquina_pontos(
                    maquina_id, slug, nome, grupo, tipo, unidade,
                    limite_min, limite_max, alarme_quando, origem
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["id"],
                    point["slug"],
                    point["nome"],
                    point["grupo"],
                    point["tipo"],
                    point["unidade"],
                    point["limite_min"],
                    point["limite_max"],
                    None
                    if point["alarme_quando"] is None
                    else int(point["alarme_quando"]),
                    point["origem"],
                ),
            )
