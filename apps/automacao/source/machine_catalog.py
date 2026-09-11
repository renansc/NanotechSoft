"""Catalogo versionado das maquinas industriais do Rio Branco.

Os dados abaixo foram conferidos nos manuais fotografados entregues pela
operacao. Enderecos de CLP, IPs e setpoints de processo nao aparecem de forma
confiavel nas fotos e, por isso, ficam deliberadamente fora do catalogo.
"""

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


def machine_by_slug(slug):
    return next((machine for machine in MACHINES if machine["slug"] == slug), None)


def seed_machines(conn):
    """Cria o catalogo sem sobrescrever ajustes feitos pela operacao."""
    for machine in MACHINES:
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
