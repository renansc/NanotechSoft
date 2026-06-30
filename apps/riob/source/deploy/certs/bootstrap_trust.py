#!/usr/bin/env python3
import ipaddress
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
from urllib.parse import urlparse

import paramiko


def log(message):
    print(f"[cert-bootstrap] {message}", flush=True)


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def split_csv(raw):
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def unique_hosts(values):
    out = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except Exception:
        return False


def build_host_list(primary_hosts, extra_hosts=None):
    items = list(primary_hosts)
    if extra_hosts:
        items.extend(extra_hosts)
    items.extend(["localhost", "127.0.0.1"])
    return unique_hosts(items)


def derive_app_hosts():
    hosts = []
    server_name = (os.environ.get("RB_SERVER_NAME") or "").strip()
    if server_name and server_name != "_":
        hosts.append(server_name)

    public_base_url = (os.environ.get("RB_PUBLIC_BASE_URL") or "").strip()
    if public_base_url:
        parsed = urlparse(public_base_url)
        if parsed.hostname:
            hosts.append(parsed.hostname)

    return build_host_list(hosts, split_csv(os.environ.get("RB_CERT_APP_HOSTS")))


def derive_pbx_hosts():
    hosts = []
    pbx_host = (os.environ.get("RB_FREEPBX_HOST") or "").strip()
    if pbx_host:
        hosts.append(pbx_host)
    return build_host_list(hosts, split_csv(os.environ.get("RB_CERT_PBX_HOSTS")))


def run(cmd, cwd=None):
    log("run: " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or "comando falhou")
    return result


def write_text(path, content, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    os.chmod(path, mode)


def write_binary(path, content, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    os.chmod(path, mode)


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_openssl_req_config(common_name, hosts):
    dns_entries = []
    ip_entries = []
    for host in unique_hosts(hosts):
        if is_ip(host):
            ip_entries.append(host)
        else:
            dns_entries.append(host)

    alt_lines = []
    index = 1
    for host in dns_entries:
        alt_lines.append(f"DNS.{index} = {host}")
        index += 1
    index = 1
    for host in ip_entries:
        alt_lines.append(f"IP.{index} = {host}")
        index += 1

    return "\n".join(
        [
            "[req]",
            "default_bits = 2048",
            "distinguished_name = req_distinguished_name",
            "prompt = no",
            "req_extensions = v3_req",
            "",
            "[req_distinguished_name]",
            f"CN = {common_name}",
            "",
            "[v3_req]",
            "basicConstraints = critical,CA:FALSE",
            "keyUsage = critical,digitalSignature,keyEncipherment",
            "extendedKeyUsage = serverAuth",
            "subjectAltName = @alt_names",
            "",
            "[alt_names]",
            *alt_lines,
            "",
        ]
    )


def ensure_ca(cert_dir, ca_cn, ca_days):
    ca_cert_path = os.path.join(cert_dir, "riobranco-ca.crt")
    ca_key_path = os.path.join(cert_dir, "riobranco-ca.key")
    ca_serial_path = os.path.join(cert_dir, "riobranco-ca.srl")

    cert_exists = os.path.exists(ca_cert_path)
    key_exists = os.path.exists(ca_key_path)
    if cert_exists and key_exists:
        log(f"reutilizando CA existente em {ca_cert_path}")
        return ca_cert_path, ca_key_path, ca_serial_path
    if cert_exists != key_exists:
        raise RuntimeError("estado inconsistente da CA: certificado/chave ausente")

    run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            str(ca_days),
            "-subj",
            f"/CN={ca_cn}",
            "-keyout",
            ca_key_path,
            "-out",
            ca_cert_path,
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:1",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-addext",
            "subjectKeyIdentifier=hash",
        ]
    )
    os.chmod(ca_key_path, 0o600)
    os.chmod(ca_cert_path, 0o644)
    log(f"CA interna criada em {ca_cert_path}")
    return ca_cert_path, ca_key_path, ca_serial_path


def ensure_server_cert(ca_cert_path, ca_key_path, ca_serial_path, common_name, hosts, cert_path, key_path, fullchain_path, days, force=False):
    if not force and os.path.exists(cert_path) and os.path.exists(key_path) and os.path.exists(fullchain_path):
        log(f"reutilizando certificado existente para {common_name}: {fullchain_path}")
        return False

    tmpdir = tempfile.mkdtemp(prefix="riobranco-cert-")
    try:
        cfg_path = os.path.join(tmpdir, "req.cnf")
        csr_path = os.path.join(tmpdir, "server.csr")
        leaf_path = os.path.join(tmpdir, "server.crt")
        key_tmp_path = os.path.join(tmpdir, "server.key")

        write_text(cfg_path, build_openssl_req_config(common_name, hosts), 0o600)
        run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", key_tmp_path, "-out", csr_path, "-config", cfg_path])
        run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                csr_path,
                "-CA",
                ca_cert_path,
                "-CAkey",
                ca_key_path,
                "-CAcreateserial",
                "-CAserial",
                ca_serial_path,
                "-out",
                leaf_path,
                "-days",
                str(days),
                "-sha256",
                "-extensions",
                "v3_req",
                "-extfile",
                cfg_path,
            ]
        )

        leaf_pem = read_text(leaf_path)
        ca_pem = read_text(ca_cert_path)
        with open(key_tmp_path, "rb") as f:
            key_bytes = f.read()
        write_text(cert_path, leaf_pem, 0o644)
        write_text(fullchain_path, leaf_pem + ("" if leaf_pem.endswith("\n") else "\n") + ca_pem, 0o644)
        write_binary(key_path, key_bytes, 0o600)
        log(f"certificado emitido para {common_name}: {fullchain_path}")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def install_freepbx_cert(host, port, user, password, local_ca_path, local_key_path, local_cert_path, local_fullchain_path):
    if not host or not user or not password:
        log("credenciais do FreePBX ausentes; pulando instalacao remota do certificado WSS")
        return

    remote_ca_path = "/etc/asterisk/keys/riobranco-ca.crt"
    remote_key_path = "/etc/asterisk/keys/riobranco-wss.key"
    remote_cert_path = "/etc/asterisk/keys/riobranco-wss.crt"
    remote_fullchain_path = "/etc/asterisk/keys/riobranco-wss-fullchain.pem"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password, timeout=20, banner_timeout=20, auth_timeout=20)
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(local_ca_path, remote_ca_path)
            sftp.put(local_key_path, remote_key_path)
            sftp.put(local_cert_path, remote_cert_path)
            sftp.put(local_fullchain_path, remote_fullchain_path)
        finally:
            sftp.close()

        commands = [
            f"chown asterisk:asterisk {remote_ca_path} {remote_key_path} {remote_cert_path} {remote_fullchain_path}",
            f"chmod 640 {remote_ca_path} {remote_key_path} {remote_cert_path} {remote_fullchain_path}",
            f"fwconsole setting HTTPTLSCERTFILE {remote_fullchain_path}",
            f"fwconsole setting HTTPTLSPRIVATEKEY {remote_key_path}",
            "nohup fwconsole restart >/tmp/riobranco-cert-bootstrap.log 2>&1 < /dev/null &",
        ]
        cmd = " && ".join(commands)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=20)
        output = stdout.read().decode("utf-8", errors="ignore")
        error = stderr.read().decode("utf-8", errors="ignore").strip()
        if output:
            log(output.strip())
        if error:
            raise RuntimeError(error)
        wait_for_tls(host, 8089, timeout=120)
        log(f"certificado WSS instalado no FreePBX {host}")
    finally:
        client.close()


def wait_for_tls(host, port, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=host):
                    return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"timeout aguardando TLS em {host}:{port}")


def main():
    cert_bootstrap = env_bool("RB_CERT_BOOTSTRAP", True)
    https_enabled = env_bool("RB_ENABLE_HTTPS", False)
    cert_dir = os.environ.get("RB_CERT_DIR", "/certs")
    os.makedirs(cert_dir, exist_ok=True)

    if not cert_bootstrap:
        log("bootstrap de certificados desabilitado; saindo")
        return 0

    app_hosts = derive_app_hosts()
    pbx_hosts = derive_pbx_hosts()
    if not https_enabled and not pbx_hosts:
        log("HTTPS e FreePBX sem bootstrap; nada para fazer")
        return 0

    ca_cn = (os.environ.get("RB_CA_CERT_CN") or "RioBranco Internal CA").strip()
    ca_days = env_int("RB_CA_CERT_DAYS", 3650)
    server_days = env_int("RB_SERVER_CERT_DAYS", 825)
    force_reissue = env_bool("RB_CERT_FORCE_REISSUE", False)
    ca_cert_path, ca_key_path, ca_serial_path = ensure_ca(cert_dir, ca_cn, ca_days)

    if app_hosts:
        app_common_name = app_hosts[0]
        ensure_server_cert(
            ca_cert_path,
            ca_key_path,
            ca_serial_path,
            app_common_name,
            app_hosts,
            os.path.join(cert_dir, "riobranco-app.crt"),
            os.path.join(cert_dir, "privkey.pem"),
            os.path.join(cert_dir, "fullchain.pem"),
            server_days,
            force=force_reissue,
        )
    else:
        log("RB_SERVER_NAME/RB_PUBLIC_BASE_URL nao definidos; pulando certificado do app")

    pbx_host = (os.environ.get("RB_FREEPBX_HOST") or "").strip()
    if pbx_hosts and pbx_host:
        local_pbx_cert_path = os.path.join(cert_dir, "riobranco-freepbx.crt")
        local_pbx_key_path = os.path.join(cert_dir, "riobranco-freepbx.key")
        local_pbx_fullchain_path = os.path.join(cert_dir, "riobranco-freepbx-fullchain.pem")
        pbx_changed = ensure_server_cert(
            ca_cert_path,
            ca_key_path,
            ca_serial_path,
            pbx_hosts[0],
            pbx_hosts,
            local_pbx_cert_path,
            local_pbx_key_path,
            local_pbx_fullchain_path,
            server_days,
            force=force_reissue,
        )
        if pbx_changed or force_reissue:
            install_freepbx_cert(
                pbx_host,
                env_int("RB_FREEPBX_SSH_PORT", 22),
                (os.environ.get("RB_FREEPBX_SSH_USER") or "").strip(),
                os.environ.get("RB_FREEPBX_SSH_PASS") or "",
                ca_cert_path,
                local_pbx_key_path,
                local_pbx_cert_path,
                local_pbx_fullchain_path,
            )
        else:
            log("certificado WSS do FreePBX ja existe localmente; pulando reinstalacao remota")
    else:
        log("host do FreePBX nao configurado; pulando certificado WSS remoto")

    log("bootstrap de certificados concluido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
