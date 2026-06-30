from __future__ import annotations

import os
import uuid
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, render_template, request, session

from .docker_session_store import DockerConnectionRecord, docker_connection_store
from .terminal_store import TerminalError, terminal_store
from .services.docker_host import DockerError, DockerHostService
from .services.vsphere import VsphereError, VsphereService
from .session_store import ConnectionRecord, connection_store


bp = Blueprint("portal", __name__)


class ConnectionRequiredError(VsphereError):
    pass


class DockerConnectionRequiredError(DockerError):
    pass


def _ui_logged_in() -> bool:
    return session.get("ui_logged_in") is True


def _get_default_vsphere_config() -> dict[str, Any]:
    host = str(os.getenv("VSPHERE_DEFAULT_HOST", os.getenv("ESXI_HOST", "")) or "").strip()
    username = str(os.getenv("VSPHERE_DEFAULT_USERNAME", os.getenv("ESXI_USER", "")) or "").strip()
    password = str(os.getenv("VSPHERE_DEFAULT_PASSWORD", os.getenv("ESXI_PASS", "")) or "")
    port_value = os.getenv("VSPHERE_DEFAULT_PORT", os.getenv("ESXI_VSPHERE_PORT", "443"))

    try:
        port = int(str(port_value or "443").strip() or "443")
    except (TypeError, ValueError):
        port = 443

    return {
        "host": host,
        "username": username,
        "password": password,
        "port": port,
        "verify_ssl": _as_bool(os.getenv("VSPHERE_DEFAULT_VERIFY_SSL", os.getenv("ESXI_VERIFY_SSL", "0")), default=False),
        "auto_connect": _as_bool(os.getenv("VSPHERE_AUTO_CONNECT", "0"), default=False),
    }


def _ensure_default_vsphere_connection() -> ConnectionRecord | None:
    record = connection_store.get(session.get("vsphere_sid"))
    if record is not None:
        return record

    defaults = _get_default_vsphere_config()
    if not defaults["auto_connect"] or session.get("disable_vsphere_auto_connect"):
        return None
    if not _ui_logged_in():
        return None
    if not defaults["host"] or not defaults["username"] or not defaults["password"]:
        return None

    try:
        service_instance, endpoint = VsphereService.connect(
            host=defaults["host"],
            username=defaults["username"],
            password=defaults["password"],
            port=defaults["port"],
            verify_ssl=defaults["verify_ssl"],
        )
    except Exception as exc:
        current_app.logger.warning("Falha no auto-connect vSphere: %s", exc)
        return None

    record = connection_store.create(
        service_instance,
        host=defaults["host"],
        port=defaults["port"],
        username=defaults["username"],
        verify_ssl=defaults["verify_ssl"],
        endpoint_name=endpoint["endpoint_name"],
        api_type=endpoint["api_type"],
        api_version=endpoint["api_version"],
        product_line=endpoint["product_line"],
    )
    session["vsphere_sid"] = record.sid
    session.modified = True
    return record


def _get_web_session_id() -> str:
    web_sid = session.get("web_sid")
    if web_sid:
        return web_sid
    web_sid = uuid.uuid4().hex
    session["web_sid"] = web_sid
    session.modified = True
    return web_sid


def _json_ok(**payload: Any):
    return jsonify({"ok": True, **payload})


def _json_error(message: str, status_code: int):
    return jsonify({"ok": False, "error": message}), status_code


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "on", "yes", "sim"}


def _get_payload() -> dict[str, Any]:
    return request.get_json(silent=True) or {}


def _get_record() -> ConnectionRecord:
    record = _ensure_default_vsphere_connection()
    if record is None:
        raise ConnectionRequiredError("Nenhuma conexao ativa. Conecte em um ESXi ou vCenter.")
    return record


def _get_service() -> tuple[VsphereService, ConnectionRecord]:
    record = _get_record()
    return VsphereService(record.service_instance), record


def _get_docker_record() -> DockerConnectionRecord:
    record = docker_connection_store.get(session.get("docker_sid"))
    if record is None:
        raise DockerConnectionRequiredError("Nenhuma conexao Docker ativa. Conecte em um host com Docker.")
    return record


def _get_docker_service() -> tuple[DockerHostService, DockerConnectionRecord]:
    record = _get_docker_record()
    return DockerHostService(
        host=record.host,
        port=record.port,
        username=record.username,
        password=record.password,
        legacy_compat=record.legacy_compat,
    ), record


@bp.before_app_request
def require_ui_authentication():
    if request.endpoint in {"static", "portal.index", "portal.api_login", "portal.api_logout", "portal.api_session", "portal.api_docker_session"}:
        return None
    if request.path.startswith("/static/"):
        return None
    if _ui_logged_in():
        return None
    if request.path.startswith("/api/"):
        return _json_error("Login requerido para usar o monitor.", 401)

    defaults = _get_default_vsphere_config()
    return render_template(
        "index.html",
        logged_in=False,
        default_host=defaults["host"],
        default_port=defaults["port"],
        default_username=defaults["username"],
        default_verify_ssl=defaults["verify_ssl"],
    )


@bp.errorhandler(VsphereError)
def handle_vsphere_error(exc: VsphereError):
    status_code = 401 if isinstance(exc, ConnectionRequiredError) else 400
    return _json_error(str(exc), status_code)


@bp.errorhandler(TerminalError)
def handle_terminal_error(exc: TerminalError):
    return _json_error(str(exc), 400)


@bp.errorhandler(DockerError)
def handle_docker_error(exc: DockerError):
    status_code = 401 if isinstance(exc, DockerConnectionRequiredError) else 400
    return _json_error(str(exc), status_code)


@bp.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    current_app.logger.exception("Erro nao tratado", exc_info=exc)
    if request.path.startswith("/api/"):
        return _json_error("Erro interno do servidor.", 500)
    return "Erro interno do servidor.", 500


@bp.get("/")
def index():
    defaults = _get_default_vsphere_config()
    return render_template(
        "index.html",
        logged_in=_ui_logged_in(),
        default_host=defaults["host"],
        default_port=defaults["port"],
        default_username=defaults["username"],
        default_verify_ssl=defaults["verify_ssl"],
    )


@bp.post("/api/login")
def api_login():
    payload = _get_payload()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    defaults = _get_default_vsphere_config()
    ui_user = str(os.getenv("UI_USER", "admin")).strip()
    ui_pass = str(os.getenv("UI_PASS", "admin123"))

    valid_ui_login = username == ui_user and password == ui_pass
    valid_vsphere_login = (
        defaults["username"]
        and defaults["password"]
        and username == defaults["username"]
        and password == defaults["password"]
    )

    if not (valid_ui_login or valid_vsphere_login):
        return _json_error("Usuario ou senha invalidos.", 401)

    session["ui_logged_in"] = True
    session["ui_username"] = username
    session.pop("disable_vsphere_auto_connect", None)
    session.modified = True
    return _json_ok(message="Login realizado com sucesso.", username=username)


@bp.post("/api/logout")
def api_logout():
    terminal_store.remove_for_owner(session.get("web_sid"))
    connection_store.remove(session.get("vsphere_sid"))
    docker_connection_store.remove(session.get("docker_sid"))
    session.clear()
    return _json_ok(message="Logout realizado.")


@bp.get("/api/session")
def api_session():
    if not _ui_logged_in():
        return _json_ok(authenticated=False, connected=False, connection=None)

    record = _ensure_default_vsphere_connection()
    if record is None:
        return _json_ok(authenticated=True, connected=False, connection=None)
    return _json_ok(authenticated=True, connected=True, connection=record.to_public_dict())


@bp.get("/api/docker/session")
def api_docker_session():
    if not _ui_logged_in():
        return _json_ok(authenticated=False, connected=False, connection=None)

    record = docker_connection_store.get(session.get("docker_sid"))
    if record is None:
        return _json_ok(authenticated=True, connected=False, connection=None)
    return _json_ok(authenticated=True, connected=True, connection=record.to_public_dict())


@bp.post("/api/session/connect")
def api_connect():
    payload = _get_payload()
    host = str(payload.get("host", "")).strip()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    port_value = payload.get("port")
    verify_ssl = _as_bool(payload.get("verify_ssl"), default=False)

    if not host or not username or not password:
        raise VsphereError("Host, usuario e senha sao obrigatorios.")
    host, port = VsphereService.normalize_endpoint(host, port_value)

    service_instance, endpoint = VsphereService.connect(
        host=host,
        username=username,
        password=password,
        port=port,
        verify_ssl=verify_ssl,
    )

    old_sid = session.get("vsphere_sid")
    connection_store.remove(old_sid)

    record = connection_store.create(
        service_instance,
        host=host,
        port=port,
        username=username,
        verify_ssl=verify_ssl,
        endpoint_name=endpoint["endpoint_name"],
        api_type=endpoint["api_type"],
        api_version=endpoint["api_version"],
        product_line=endpoint["product_line"],
    )
    session["vsphere_sid"] = record.sid
    session.pop("disable_vsphere_auto_connect", None)
    session.modified = True

    return _json_ok(
        message="Conexao estabelecida com sucesso.",
        connection=record.to_public_dict(),
    )


@bp.post("/api/docker/session/connect")
def api_docker_connect():
    payload = _get_payload()
    host = str(payload.get("host", "")).strip()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    port_value = payload.get("port", 22)
    legacy_compat = _as_bool(payload.get("legacy_compat"), default=True)

    if not host or not username or not password:
        raise DockerError("Host, usuario e senha Docker sao obrigatorios.")

    normalized_host, normalized_port = DockerHostService.normalize_endpoint(host, port_value)
    info, _ = DockerHostService.probe_connection(
        host=normalized_host,
        port=normalized_port,
        username=username,
        password=password,
        legacy_compat=legacy_compat,
    )

    old_sid = session.get("docker_sid")
    docker_connection_store.remove(old_sid)

    record = docker_connection_store.create(
        host=normalized_host,
        port=normalized_port,
        username=username,
        password=password,
        legacy_compat=legacy_compat,
        engine_name=info.engine_name,
        server_version=info.server_version,
        operating_system=info.operating_system,
    )
    session["docker_sid"] = record.sid
    session.modified = True

    return _json_ok(
        message="Conexao Docker estabelecida com sucesso.",
        connection=record.to_public_dict(),
    )


@bp.post("/api/session/disconnect")
def api_disconnect():
    terminal_store.remove_for_owner(_get_web_session_id())
    connection_store.remove(session.get("vsphere_sid"))
    session.pop("vsphere_sid", None)
    session["disable_vsphere_auto_connect"] = True
    session.modified = True
    return _json_ok(message="Conexao encerrada.")


@bp.post("/api/docker/session/disconnect")
def api_docker_disconnect():
    docker_connection_store.remove(session.get("docker_sid"))
    session.pop("docker_sid", None)
    return _json_ok(message="Conexao Docker encerrada.")


@bp.get("/api/inventory")
def api_inventory():
    service, _ = _get_service()
    return _json_ok(inventory=service.get_inventory())


@bp.get("/api/vms")
def api_vms():
    service, _ = _get_service()
    return _json_ok(vms=service.list_virtual_machines())


@bp.get("/api/vms/<moid>")
def api_vm_details(moid: str):
    service, record = _get_service()
    vm = service.get_virtual_machine_details(moid)
    vm["remote_access"] = service.get_virtual_machine_remote_access(
        moid,
        management_host=record.host,
        management_port=record.port,
        management_username=record.username,
    )
    return _json_ok(vm=vm)


@bp.get("/api/vms/<moid>/remote-access/rdp")
def api_vm_rdp(moid: str):
    service, _ = _get_service()
    guest_username = str(request.args.get("username", "")).strip() or None
    filename, content = service.build_rdp_file(moid, guest_username=guest_username)
    response = Response(content, mimetype="application/x-rdp")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@bp.post("/api/vms")
def api_vm_create():
    payload = _get_payload()
    try:
        cpu_count = int(payload.get("cpu") or 1)
        memory_mb = int(payload.get("memory_mb") or 1024)
        disk_gb = int(payload.get("disk_gb") or 20)
    except (TypeError, ValueError) as exc:
        raise VsphereError("CPU, memoria e disco da nova VM precisam ser numeros inteiros.") from exc

    service, _ = _get_service()
    vm = service.create_virtual_machine(
        name=str(payload.get("name", "")).strip(),
        guest_id=str(payload.get("guest_id", "")).strip(),
        cpu_count=cpu_count,
        memory_mb=memory_mb,
        disk_gb=disk_gb,
        host_moid=str(payload.get("host_moid", "")).strip() or None,
        folder_moid=str(payload.get("folder_moid", "")).strip() or None,
        resource_pool_moid=str(payload.get("resource_pool_moid", "")).strip() or None,
        datastore_moid=str(payload.get("datastore_moid", "")).strip(),
        network_moid=str(payload.get("network_moid", "")).strip() or None,
        power_on=_as_bool(payload.get("power_on"), default=False),
        iso_datastore_moid=str(payload.get("iso_datastore_moid", "")).strip() or None,
        iso_path=str(payload.get("iso_path", "")).strip() or None,
    )
    return _json_ok(message="Nova VM criada com sucesso.", vm=vm)


@bp.get("/api/datastores/<moid>/isos")
def api_datastore_isos(moid: str):
    service, _ = _get_service()
    folder_path = str(request.args.get("folder", "")).strip() or None
    return _json_ok(isos=service.list_datastore_isos(moid, folder_path=folder_path))


@bp.post("/api/datastores/<moid>/isos")
def api_datastore_upload_iso(moid: str):
    service, record = _get_service()
    upload = request.files.get("file")
    source_url = str(request.form.get("source_url", "")).strip()
    folder_path = str(request.form.get("folder", "")).strip() or "iso"
    overwrite = _as_bool(request.form.get("overwrite"), default=False)

    if (upload is None or not getattr(upload, "filename", "")) and not source_url:
        raise VsphereError("Selecione um arquivo ISO local ou informe uma URL HTTP/HTTPS.")

    if upload is None or not getattr(upload, "filename", ""):
        file_info = service.upload_iso_from_url(
            moid,
            source_url=source_url,
            management_host=record.host,
            management_port=record.port,
            verify_ssl=record.verify_ssl,
            overwrite=overwrite,
            folder_path=folder_path,
        )
        return _json_ok(message="ISO enviada com sucesso a partir da URL.", iso=file_info)

    stream = upload.stream
    try:
        current_position = stream.tell()
        stream.seek(0, 2)
        content_length = int(stream.tell())
        stream.seek(current_position)
    except Exception:
        content_length = getattr(upload, "content_length", None)

    file_info = service.upload_iso_to_datastore(
        moid,
        file_stream=stream,
        filename=upload.filename,
        content_length=content_length,
        management_host=record.host,
        management_port=record.port,
        verify_ssl=record.verify_ssl,
        overwrite=overwrite,
        folder_path=folder_path,
    )
    return _json_ok(message="ISO enviada com sucesso.", iso=file_info)


@bp.post("/api/vms/<moid>/media/iso")
def api_vm_mount_iso(moid: str):
    payload = _get_payload()
    service, _ = _get_service()
    vm = service.mount_virtual_machine_iso(
        moid,
        datastore_moid=str(payload.get("datastore_moid", "")).strip(),
        iso_path=str(payload.get("iso_path", "")).strip(),
        connect_at_power_on=_as_bool(payload.get("connect_at_power_on"), default=True),
    )
    return _json_ok(message="ISO montada na VM.", vm=vm)


@bp.delete("/api/vms/<moid>/media/iso")
def api_vm_eject_iso(moid: str):
    service, _ = _get_service()
    vm = service.eject_virtual_machine_iso(moid)
    return _json_ok(message="Midia ISO ejetada da VM.", vm=vm)


@bp.post("/api/terminals")
def api_create_terminal():
    _get_record()
    payload = _get_payload()
    host = str(payload.get("host", "")).strip()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    legacy_compat = _as_bool(payload.get("legacy_compat"), default=True)
    port_value = payload.get("port", 22)

    if not host or not username or not password:
        raise TerminalError("Host, usuario e senha SSH sao obrigatorios.")

    try:
        port = int(port_value)
    except (TypeError, ValueError) as exc:
        raise TerminalError("A porta SSH precisa ser numerica.") from exc

    terminal_store.reap_closed()
    terminal = terminal_store.create(
        owner_id=_get_web_session_id(),
        host=host,
        port=port,
        username=username,
        password=password,
        legacy_compat=legacy_compat,
    )
    return _json_ok(
        message="Terminal SSH iniciado.",
        terminal=terminal.to_public_dict(),
    )


@bp.get("/api/terminals/<sid>/output")
def api_terminal_output(sid: str):
    _get_record()
    terminal_store.reap_closed()
    owner_id = _get_web_session_id()
    terminal = terminal_store.get(sid, owner_id=owner_id)
    cursor_raw = request.args.get("cursor", "0")
    try:
        cursor = int(cursor_raw)
    except (TypeError, ValueError) as exc:
        raise TerminalError("Cursor do terminal invalido.") from exc

    data, next_cursor, closed, returncode = terminal.read_since(cursor)
    return _json_ok(
        data=data,
        cursor=next_cursor,
        closed=closed,
        returncode=returncode,
    )


@bp.post("/api/terminals/<sid>/input")
def api_terminal_input(sid: str):
    _get_record()
    owner_id = _get_web_session_id()
    terminal = terminal_store.get(sid, owner_id=owner_id)
    payload = _get_payload()
    data = str(payload.get("data", ""))
    if not data:
        return _json_ok()
    terminal.write(data)
    return _json_ok()


@bp.post("/api/terminals/<sid>/resize")
def api_terminal_resize(sid: str):
    _get_record()
    owner_id = _get_web_session_id()
    terminal = terminal_store.get(sid, owner_id=owner_id)
    payload = _get_payload()
    try:
        cols = int(payload.get("cols", 80))
        rows = int(payload.get("rows", 24))
    except (TypeError, ValueError) as exc:
        raise TerminalError("Dimensoes do terminal invalidas.") from exc
    terminal.resize(cols=max(cols, 20), rows=max(rows, 8))
    return _json_ok()


@bp.delete("/api/terminals/<sid>")
def api_terminal_close(sid: str):
    owner_id = _get_web_session_id()
    terminal_store.remove(sid, owner_id=owner_id)
    return _json_ok(message="Terminal SSH encerrado.")


@bp.post("/api/vms/<moid>/power")
def api_vm_power(moid: str):
    payload = _get_payload()
    action = str(payload.get("action", "")).strip()
    if not action:
        raise VsphereError("Informe a acao de energia.")
    service, _ = _get_service()
    vm = service.power_virtual_machine(moid, action)
    return _json_ok(message="Acao executada com sucesso.", vm=vm)


@bp.post("/api/vms/<moid>/rename")
def api_vm_rename(moid: str):
    payload = _get_payload()
    new_name = str(payload.get("name", "")).strip()
    if not new_name:
        raise VsphereError("Informe o novo nome da VM.")
    service, _ = _get_service()
    vm = service.rename_virtual_machine(moid, new_name)
    return _json_ok(message="VM renomeada com sucesso.", vm=vm)


@bp.post("/api/vms/<moid>/hardware")
def api_vm_hardware(moid: str):
    payload = _get_payload()
    cpu_raw = payload.get("cpu")
    memory_raw = payload.get("memory_mb")

    cpu = None
    memory_mb = None
    if cpu_raw not in (None, ""):
        try:
            cpu = int(cpu_raw)
        except (TypeError, ValueError) as exc:
            raise VsphereError("CPU deve ser um numero inteiro.") from exc
    if memory_raw not in (None, ""):
        try:
            memory_mb = int(memory_raw)
        except (TypeError, ValueError) as exc:
            raise VsphereError("Memoria deve ser um numero inteiro em MB.") from exc

    if cpu is None and memory_mb is None:
        raise VsphereError("Informe CPU, memoria ou ambos.")

    service, _ = _get_service()
    vm = service.reconfigure_virtual_machine(moid, cpu_count=cpu, memory_mb=memory_mb)
    return _json_ok(message="Hardware da VM atualizado.", vm=vm)


@bp.get("/api/vms/<moid>/snapshots")
def api_vm_snapshots(moid: str):
    service, _ = _get_service()
    return _json_ok(snapshots=service.list_snapshots(moid))


@bp.post("/api/vms/<moid>/snapshots")
def api_vm_create_snapshot(moid: str):
    payload = _get_payload()
    name = str(payload.get("name", "")).strip()
    description = str(payload.get("description", "")).strip()
    include_memory = _as_bool(payload.get("include_memory"), default=False)
    quiesce = _as_bool(payload.get("quiesce"), default=False)

    if not name:
        raise VsphereError("Informe o nome do snapshot.")

    service, _ = _get_service()
    vm = service.create_snapshot(
        moid,
        name=name,
        description=description,
        include_memory=include_memory,
        quiesce=quiesce,
    )
    return _json_ok(message="Snapshot criado com sucesso.", vm=vm)


@bp.post("/api/vms/<moid>/snapshots/<snapshot_moid>/revert")
def api_vm_revert_snapshot(moid: str, snapshot_moid: str):
    service, _ = _get_service()
    vm = service.revert_snapshot(moid, snapshot_moid)
    return _json_ok(message="Snapshot revertido com sucesso.", vm=vm)


@bp.delete("/api/vms/<moid>/snapshots/<snapshot_moid>")
def api_vm_delete_snapshot(moid: str, snapshot_moid: str):
    service, _ = _get_service()
    vm = service.delete_snapshot(moid, snapshot_moid)
    return _json_ok(message="Snapshot removido com sucesso.", vm=vm)


@bp.post("/api/vms/<moid>/clone")
def api_vm_clone(moid: str):
    payload = _get_payload()
    clone_name = str(payload.get("name", "")).strip()
    if not clone_name:
        raise VsphereError("Informe o nome do clone.")

    service, _ = _get_service()
    result = service.clone_virtual_machine(
        moid,
        name=clone_name,
        folder_moid=str(payload.get("folder_moid", "")).strip() or None,
        resource_pool_moid=str(payload.get("resource_pool_moid", "")).strip() or None,
        datastore_moid=str(payload.get("datastore_moid", "")).strip() or None,
        power_on=_as_bool(payload.get("power_on"), default=False),
        as_template=_as_bool(payload.get("as_template"), default=False),
    )
    return _json_ok(message="Clone criado com sucesso.", vm=result)


@bp.get("/api/hosts")
def api_hosts():
    service, _ = _get_service()
    return _json_ok(hosts=service.list_hosts())


@bp.get("/api/hosts/<moid>")
def api_host_details(moid: str):
    service, _ = _get_service()
    return _json_ok(host=service.get_host_details(moid))


@bp.post("/api/hosts/<moid>/maintenance")
def api_host_maintenance(moid: str):
    payload = _get_payload()
    enabled = _as_bool(payload.get("enabled"), default=True)
    service, _ = _get_service()
    host = service.set_host_maintenance(moid, enabled=enabled)
    return _json_ok(message="Estado de maintenance atualizado.", host=host)


@bp.post("/api/hosts/<moid>/power")
def api_host_power(moid: str):
    payload = _get_payload()
    action = str(payload.get("action", "")).strip()
    if not action:
        raise VsphereError("Informe a acao do host.")
    service, _ = _get_service()
    host = service.power_host(moid, action)
    return _json_ok(message="Acao do host enviada.", host=host)


@bp.get("/api/docker/overview")
def api_docker_overview():
    service, _ = _get_docker_service()
    return _json_ok(overview=service.get_overview())


@bp.get("/api/docker/containers")
def api_docker_containers():
    service, _ = _get_docker_service()
    return _json_ok(containers=service.list_containers())


@bp.post("/api/docker/containers")
def api_docker_create_container():
    payload = _get_payload()
    service, _ = _get_docker_service()
    result = service.create_container(
        image=str(payload.get("image", "")).strip(),
        name=str(payload.get("name", "")).strip() or None,
        command=str(payload.get("command", "")).strip() or None,
        ports=str(payload.get("ports", "")).strip() or None,
        environment=str(payload.get("environment", "")).strip() or None,
        volumes=str(payload.get("volumes", "")).strip() or None,
        network=str(payload.get("network", "")).strip() or None,
        restart_policy=str(payload.get("restart_policy", "")).strip() or None,
        extra_args=str(payload.get("extra_args", "")).strip() or None,
        detach=_as_bool(payload.get("detach"), default=True),
    )
    return _json_ok(
        message="Container criado com sucesso.",
        command=result["command"],
        output=result["output"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        container=result["container"],
    )


@bp.get("/api/docker/containers/<path:container_id>")
def api_docker_container_details(container_id: str):
    service, _ = _get_docker_service()
    return _json_ok(container=service.get_container_details(container_id))


@bp.get("/api/docker/containers/<path:container_id>/logs")
def api_docker_container_logs(container_id: str):
    service, _ = _get_docker_service()
    tail_raw = request.args.get("tail", "200")
    try:
        tail = int(tail_raw)
    except (TypeError, ValueError) as exc:
        raise DockerError("O valor de tail precisa ser numerico.") from exc
    return _json_ok(logs=service.get_container_logs(container_id, tail=tail))


@bp.post("/api/docker/containers/<path:container_id>/action")
def api_docker_container_action(container_id: str):
    payload = _get_payload()
    action = str(payload.get("action", "")).strip()
    if not action:
        raise DockerError("Informe a acao do container.")

    service, _ = _get_docker_service()
    container = service.execute_container_action(container_id, action)
    return _json_ok(message="Acao do container executada.", container=container)


@bp.post("/api/docker/commands")
def api_docker_run_command():
    payload = _get_payload()
    command = str(payload.get("command", "")).strip()
    if not command:
        raise DockerError("Informe o comando Docker.")

    service, _ = _get_docker_service()
    result = service.run_docker_command(command)
    return _json_ok(
        message="Comando Docker executado.",
        command=result["command"],
        output=result["output"],
        stdout=result["stdout"],
        stderr=result["stderr"],
    )
