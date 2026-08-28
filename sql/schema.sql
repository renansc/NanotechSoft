CREATE TABLE IF NOT EXISTS usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    login VARCHAR(80) NOT NULL UNIQUE,
    senha VARCHAR(255) NOT NULL,
    perfil VARCHAR(40) NOT NULL DEFAULT 'admin',
    nanostore_perfil VARCHAR(40) NOT NULL DEFAULT '',
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    data_cadastro DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX (login),
    INDEX (ativo)
);

CREATE TABLE IF NOT EXISTS portal_config (
    id INT PRIMARY KEY DEFAULT 1,
    tema VARCHAR(80) NOT NULL DEFAULT 'rio_branco',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS installed_apps (
    id INT AUTO_INCREMENT PRIMARY KEY,
    app_key VARCHAR(80) NOT NULL UNIQUE,
    nome VARCHAR(160) NOT NULL,
    descricao VARCHAR(255) DEFAULT '',
    url VARCHAR(255) DEFAULT '',
    icone VARCHAR(80) DEFAULT 'grid',
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    ordem INT NOT NULL DEFAULT 100,
    origem VARCHAR(40) NOT NULL DEFAULT 'database',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX (ativo),
    INDEX (ordem)
);

CREATE TABLE IF NOT EXISTS usuario_app_permissoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    app_key VARCHAR(80) NOT NULL,
    recurso VARCHAR(120) NOT NULL DEFAULT '*',
    permitido TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_usuario_app_recurso (usuario_id, app_key, recurso),
    INDEX (usuario_id),
    INDEX (app_key),
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS financeiro_registros (
    id INT AUTO_INCREMENT PRIMARY KEY,
    colecao VARCHAR(80) NOT NULL,
    registro_id VARCHAR(120) NOT NULL,
    payload JSON NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_financeiro_registro (colecao, registro_id),
    INDEX (colecao)
);

CREATE TABLE IF NOT EXISTS financeiro_config (
    id INT PRIMARY KEY DEFAULT 1,
    payload JSON NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tecnologia_dispositivos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    tipo VARCHAR(30) NOT NULL DEFAULT 'OUTRO',
    host VARCHAR(253) NOT NULL,
    enderecos_adicionais JSON NULL,
    porta INT NULL,
    sonda VARCHAR(20) NOT NULL DEFAULT 'ICMP',
    localizacao VARCHAR(160) NOT NULL DEFAULT '',
    observacoes VARCHAR(500) NOT NULL DEFAULT '',
    critico TINYINT(1) NOT NULL DEFAULT 0,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    latencia_alerta_ms DECIMAL(10,2) NOT NULL DEFAULT 80,
    perda_alerta_pct DECIMAL(6,2) NOT NULL DEFAULT 5,
    download_alerta_mbps DECIMAL(10,2) NOT NULL DEFAULT 50,
    upload_alerta_mbps DECIMAL(10,2) NOT NULL DEFAULT 10,
    cpu_alerta_pct DECIMAL(6,2) NOT NULL DEFAULT 90,
    memoria_alerta_pct DECIMAL(6,2) NOT NULL DEFAULT 90,
    disco_alerta_pct DECIMAL(6,2) NOT NULL DEFAULT 90,
    trafego_alerta_mbps DECIMAL(10,2) NOT NULL DEFAULT 100,
    snmp_community VARCHAR(160) NOT NULL DEFAULT '',
    snmp_port INT NOT NULL DEFAULT 161,
    agente_porta INT NULL,
    agente_path VARCHAR(120) NOT NULL DEFAULT '/metrics',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_tecnologia_host_porta (host, porta),
    INDEX idx_tecnologia_tipo_ativo (tipo, ativo)
);

CREATE TABLE IF NOT EXISTS tecnologia_velocidade (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    dispositivo_id INT NOT NULL,
    verificado_em DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    status VARCHAR(20) NOT NULL,
    download_mbps DECIMAL(12,2) NULL,
    upload_mbps DECIMAL(12,2) NULL,
    latencia_ms DECIMAL(10,2) NULL,
    mensagem VARCHAR(255) NOT NULL DEFAULT '',
    detalhes JSON NULL,
    INDEX idx_tecnologia_velocidade_dispositivo_data (dispositivo_id, verificado_em),
    FOREIGN KEY (dispositivo_id) REFERENCES tecnologia_dispositivos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tecnologia_metricas (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    dispositivo_id INT NOT NULL,
    verificado_em DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    status VARCHAR(20) NOT NULL,
    latencia_ms DECIMAL(10,2) NULL,
    perda_pct DECIMAL(6,2) NOT NULL DEFAULT 0,
    jitter_ms DECIMAL(10,2) NULL,
    servico_ok TINYINT(1) NULL,
    mensagem VARCHAR(255) NOT NULL DEFAULT '',
    detalhes JSON NULL,
    INDEX idx_tecnologia_metricas_dispositivo_data (dispositivo_id, verificado_em),
    INDEX idx_tecnologia_metricas_status_data (status, verificado_em),
    FOREIGN KEY (dispositivo_id) REFERENCES tecnologia_dispositivos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tecnologia_alertas_recursos (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    dispositivo_id INT NOT NULL,
    recurso VARCHAR(20) NOT NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 0,
    valor_atual DECIMAL(6,2) NULL,
    limite_pct DECIMAL(6,2) NOT NULL DEFAULT 90,
    disparado_em DATETIME NULL,
    recuperado_em DATETIME NULL,
    ultimo_email_em DATETIME NULL,
    ultima_tentativa_em DATETIME NULL,
    ultimo_erro VARCHAR(500) NOT NULL DEFAULT '',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_tecnologia_alerta_recurso (dispositivo_id, recurso),
    INDEX idx_tecnologia_alerta_ativo (ativo, updated_at),
    FOREIGN KEY (dispositivo_id) REFERENCES tecnologia_dispositivos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tecnologia_backups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(160) NOT NULL,
    maquina VARCHAR(160) NOT NULL,
    agente_id VARCHAR(80) NOT NULL UNIQUE,
    agente_token_hash CHAR(64) NOT NULL,
    banco_tipo VARCHAR(24) NOT NULL DEFAULT 'MYSQL',
    banco_host VARCHAR(253) NOT NULL,
    banco_porta INT NOT NULL DEFAULT 3306,
    banco_nome VARCHAR(160) NOT NULL,
    banco_usuario VARCHAR(160) NOT NULL,
    senha_variavel VARCHAR(160) NOT NULL DEFAULT 'NANOTECH_BACKUP_DB_PASSWORD',
    origens_path JSON NULL,
    destino_path VARCHAR(1000) NOT NULL,
    nuvem_path VARCHAR(1000) NOT NULL DEFAULT '',
    horarios JSON NOT NULL,
    timezone VARCHAR(80) NOT NULL DEFAULT 'America/Sao_Paulo',
    retencao_diaria_dias INT NOT NULL DEFAULT 7,
    retencao_semanal_semanas INT NOT NULL DEFAULT 5,
    retencao_mensal_meses INT NOT NULL DEFAULT 12,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    ultimo_contato_em DATETIME(3) NULL,
    agente_versao VARCHAR(40) NOT NULL DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tecnologia_backups_ativo_contato (ativo, ultimo_contato_em)
);

CREATE TABLE IF NOT EXISTS tecnologia_backup_execucoes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    backup_id INT NOT NULL,
    execucao_id VARCHAR(120) NOT NULL,
    horario_programado VARCHAR(5) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL,
    iniciado_em DATETIME(3) NULL,
    concluido_em DATETIME(3) NULL,
    arquivo_path VARCHAR(1200) NOT NULL DEFAULT '',
    tamanho_bytes BIGINT NULL,
    sha256 CHAR(64) NOT NULL DEFAULT '',
    camadas VARCHAR(120) NOT NULL DEFAULT '',
    mensagem VARCHAR(1000) NOT NULL DEFAULT '',
    detalhes JSON NULL,
    recebido_em DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_tecnologia_backup_execucao (backup_id, execucao_id),
    INDEX idx_tecnologia_backup_execucoes_data (backup_id, recebido_em),
    INDEX idx_tecnologia_backup_execucoes_status (status, recebido_em),
    FOREIGN KEY (backup_id) REFERENCES tecnologia_backups(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chamados (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    protocolo VARCHAR(32) NOT NULL UNIQUE,
    titulo VARCHAR(180) NOT NULL,
    descricao TEXT NOT NULL,
    categoria VARCHAR(40) NOT NULL DEFAULT 'TI',
    subcategoria VARCHAR(100) NOT NULL DEFAULT '',
    prioridade VARCHAR(20) NOT NULL DEFAULT 'MEDIA',
    status VARCHAR(24) NOT NULL DEFAULT 'ABERTO',
    localizacao VARCHAR(160) NOT NULL DEFAULT '',
    sintomas TEXT NULL,
    causa_raiz TEXT NULL,
    solucao_resumo TEXT NULL,
    solicitante_id INT NULL,
    responsavel_id INT NULL,
    dispositivo_id INT NULL,
    criado_por_id INT NULL,
    encerrado_em DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_chamados_status_prioridade (status, prioridade, updated_at),
    INDEX idx_chamados_categoria (categoria, subcategoria),
    INDEX idx_chamados_solicitante (solicitante_id),
    INDEX idx_chamados_responsavel (responsavel_id),
    INDEX idx_chamados_dispositivo (dispositivo_id),
    FOREIGN KEY (solicitante_id) REFERENCES usuarios(id) ON DELETE SET NULL,
    FOREIGN KEY (responsavel_id) REFERENCES usuarios(id) ON DELETE SET NULL,
    FOREIGN KEY (criado_por_id) REFERENCES usuarios(id) ON DELETE SET NULL,
    FOREIGN KEY (dispositivo_id) REFERENCES tecnologia_dispositivos(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS chamados_intervencoes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chamado_id BIGINT NOT NULL,
    autor_id INT NULL,
    tipo VARCHAR(24) NOT NULL DEFAULT 'COMENTARIO',
    descricao TEXT NOT NULL,
    minutos_gastos INT NOT NULL DEFAULT 0,
    status_anterior VARCHAR(24) NULL,
    status_novo VARCHAR(24) NULL,
    solucao_aplicada TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_chamados_intervencoes_chamado_data (chamado_id, created_at),
    INDEX idx_chamados_intervencoes_autor (autor_id),
    FOREIGN KEY (chamado_id) REFERENCES chamados(id) ON DELETE CASCADE,
    FOREIGN KEY (autor_id) REFERENCES usuarios(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS chamados_documentos (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chamado_id BIGINT NULL,
    dispositivo_id INT NULL,
    criado_por_id INT NULL,
    categoria VARCHAR(40) NOT NULL DEFAULT 'GERAL',
    titulo VARCHAR(180) NOT NULL,
    descricao TEXT NULL,
    nome_arquivo VARCHAR(255) NOT NULL DEFAULT '',
    arquivo_armazenado VARCHAR(255) NOT NULL DEFAULT '',
    mime_type VARCHAR(120) NOT NULL DEFAULT '',
    tamanho_bytes BIGINT NOT NULL DEFAULT 0,
    url_externa VARCHAR(1000) NOT NULL DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_chamados_documentos_chamado (chamado_id, created_at),
    INDEX idx_chamados_documentos_dispositivo (dispositivo_id),
    INDEX idx_chamados_documentos_categoria (categoria),
    FOREIGN KEY (chamado_id) REFERENCES chamados(id) ON DELETE CASCADE,
    FOREIGN KEY (dispositivo_id) REFERENCES tecnologia_dispositivos(id) ON DELETE SET NULL,
    FOREIGN KEY (criado_por_id) REFERENCES usuarios(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS chamados_agenda (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chamado_id BIGINT NULL,
    criado_por_id INT NULL,
    tipo VARCHAR(24) NOT NULL DEFAULT 'TAREFA',
    titulo VARCHAR(180) NOT NULL,
    descricao TEXT NULL,
    agendado_em DATETIME NOT NULL,
    avisar_em DATETIME NOT NULL,
    destinatarios VARCHAR(1000) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'PENDENTE',
    email_enviado_em DATETIME NULL,
    ultima_tentativa_em DATETIME NULL,
    tentativas INT NOT NULL DEFAULT 0,
    ultimo_erro VARCHAR(500) NOT NULL DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_chamados_agenda_aviso (status, avisar_em, email_enviado_em),
    INDEX idx_chamados_agenda_chamado (chamado_id, agendado_em),
    FOREIGN KEY (chamado_id) REFERENCES chamados(id) ON DELETE SET NULL,
    FOREIGN KEY (criado_por_id) REFERENCES usuarios(id) ON DELETE SET NULL
);

INSERT INTO portal_config (id, tema)
VALUES (1, 'rio_branco')
ON DUPLICATE KEY UPDATE id = id;
