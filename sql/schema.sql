CREATE TABLE IF NOT EXISTS usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    login VARCHAR(80) NOT NULL UNIQUE,
    senha VARCHAR(255) NOT NULL,
    perfil VARCHAR(40) NOT NULL DEFAULT 'admin',
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

INSERT INTO portal_config (id, tema)
VALUES (1, 'rio_branco')
ON DUPLICATE KEY UPDATE id = id;
