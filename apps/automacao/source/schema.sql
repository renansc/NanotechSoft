PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS setores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    descricao TEXT
);

CREATE TABLE IF NOT EXISTS motores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    setor_id INTEGER,

    rpm_alerta REAL DEFAULT 1800,
    temperatura_alerta REAL DEFAULT 70,
    vibracao_alerta REAL DEFAULT 0.50,

    ativo INTEGER DEFAULT 1,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ultimo_contato DATETIME,

    FOREIGN KEY(setor_id)
        REFERENCES setores(id)
);

CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    motor_id INTEGER NOT NULL,

    rpm REAL,
    temperatura REAL,
    vibracao REAL,

    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(motor_id)
        REFERENCES motores(id)
);

CREATE TABLE IF NOT EXISTS alarmes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    motor_id INTEGER,

    tipo TEXT,
    valor REAL,
    limite REAL,

    reconhecido INTEGER DEFAULT 0,

    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(motor_id)
        REFERENCES motores(id)
);

CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    fabricante TEXT DEFAULT 'Kollmorgen',
    modelo TEXT DEFAULT 'AKD/AKD2G',
    protocolo TEXT DEFAULT 'kollmorgen_akd_modbus_tcp',

    ip TEXT NOT NULL,
    porta INTEGER DEFAULT 502,
    unit_id INTEGER DEFAULT 1,

    motor_id INTEGER,
    intervalo_segundos INTEGER DEFAULT 5,
    timeout_segundos REAL DEFAULT 3,
    ativo INTEGER DEFAULT 1,

    ultimo_status TEXT DEFAULT 'novo',
    ultimo_erro TEXT,
    ultimo_contato DATETIME,
    ultimo_poll DATETIME,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(motor_id)
        REFERENCES motores(id)
        ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS driver_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER NOT NULL,

    nome TEXT NOT NULL,
    endereco INTEGER NOT NULL,
    registradores INTEGER DEFAULT 2,
    tipo TEXT DEFAULT 'int32',
    escala REAL DEFAULT 1,
    unidade TEXT,
    ativo INTEGER DEFAULT 1,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(driver_id)
        REFERENCES drivers(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS driver_leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER NOT NULL,

    dados_json TEXT NOT NULL,
    raw_json TEXT,
    status TEXT DEFAULT 'ok',
    erro TEXT,

    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(driver_id)
        REFERENCES drivers(id)
        ON DELETE CASCADE
);
