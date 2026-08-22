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

INSERT INTO portal_config (id, tema)
VALUES (1, 'rio_branco')
ON DUPLICATE KEY UPDATE id = id;
