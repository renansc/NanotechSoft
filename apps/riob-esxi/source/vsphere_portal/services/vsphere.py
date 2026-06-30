from __future__ import annotations

import http.client
import os
import ssl
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

from pyVim.connect import SmartConnect
from pyVmomi import vim, vmodl


class VsphereError(RuntimeError):
    pass


class VsphereService:
    PERF_COUNTERS = {
        "cpu_usage": ("cpu", "usage", "average"),
        "memory_usage": ("mem", "usage", "average"),
        "network_usage": ("net", "usage", "average"),
        "disk_usage": ("disk", "usage", "average"),
        "disk_read": ("disk", "read", "average"),
        "disk_write": ("disk", "write", "average"),
    }

    def __init__(self, service_instance: Any) -> None:
        self.service_instance = service_instance

    @staticmethod
    def _build_ssl_context(verify_ssl: bool) -> ssl.SSLContext:
        if verify_ssl:
            context = ssl.create_default_context()
        else:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            context.options |= ssl.OP_IGNORE_UNEXPECTED_EOF

        if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
            context.options |= ssl.OP_LEGACY_SERVER_CONNECT

        tls_version = getattr(ssl, "TLSVersion", None)
        if tls_version is not None and hasattr(context, "minimum_version"):
            try:
                context.minimum_version = tls_version.TLSv1
            except ValueError:
                pass

        try:
            context.set_ciphers(os.getenv("VSPHERE_SSL_CIPHERS", "ALL:@SECLEVEL=0"))
        except ssl.SSLError:
            pass

        return context

    @staticmethod
    def normalize_endpoint(host: str, port: Any = None) -> tuple[str, int]:
        raw_host = str(host or "").strip()
        if not raw_host:
            raise VsphereError("Host ou IP sao obrigatorios.")

        candidate = raw_host if "://" in raw_host else f"https://{raw_host}"
        try:
            parsed = urlsplit(candidate)
            normalized_host = parsed.hostname or raw_host.strip().strip("/")
            embedded_port = parsed.port
        except ValueError as exc:
            raise VsphereError("Host, URL ou porta invalidos.") from exc

        if not normalized_host:
            raise VsphereError("Host ou URL invalidos.")

        resolved_port = embedded_port if port in (None, "") else port
        if resolved_port in (None, ""):
            resolved_port = 443

        try:
            normalized_port = int(resolved_port)
        except (TypeError, ValueError) as exc:
            raise VsphereError("A porta precisa ser numerica.") from exc

        if not 1 <= normalized_port <= 65535:
            raise VsphereError("A porta precisa estar entre 1 e 65535.")

        return normalized_host, normalized_port

    @classmethod
    def connect(
        cls,
        *,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        verify_ssl: bool = False,
    ) -> tuple[Any, dict[str, str]]:
        normalized_host, normalized_port = cls.normalize_endpoint(host, port)
        if normalized_port == 22:
            raise VsphereError("A porta 22 e SSH. Para ESXi ou vCenter use HTTPS, normalmente na porta 443.")
        try:
            kwargs: dict[str, Any] = {
                "host": normalized_host,
                "user": username,
                "pwd": password,
                "port": normalized_port,
                "sslContext": cls._build_ssl_context(verify_ssl),
            }

            service_instance = SmartConnect(**kwargs)
            about = service_instance.RetrieveContent().about
            endpoint = {
                "endpoint_name": getattr(about, "fullName", normalized_host),
                "api_type": getattr(about, "apiType", "unknown"),
                "api_version": getattr(about, "apiVersion", "unknown"),
                "product_line": getattr(about, "name", "unknown"),
            }
            return service_instance, endpoint
        except ssl.SSLError as exc:
            message = str(exc)
            if "WRONG_VERSION_NUMBER" in message.upper():
                raise VsphereError(
                    "O host respondeu com um protocolo que nao parece ser HTTPS do vSphere nessa porta. "
                    "Para ESXi ou vCenter use o FQDN/IP do proprio servidor e, em geral, a porta 443."
                ) from exc
            raise VsphereError(f"Falha SSL ao conectar: {exc}") from exc
        except vmodl.MethodFault as exc:
            raise VsphereError(exc.msg or "Falha ao conectar no ambiente vSphere.") from exc
        except Exception as exc:
            raise VsphereError(f"Falha ao conectar: {exc}") from exc

    def get_inventory(self) -> dict[str, Any]:
        content = self._content()
        datacenters = self._get_view(vim.Datacenter)
        clusters = self._get_view(vim.ClusterComputeResource)
        hosts = self._get_view(vim.HostSystem)
        datastores = self._get_view(vim.Datastore)
        networks = self._get_view(vim.Network)
        resource_pools = self._get_view(vim.ResourcePool)
        folders = [folder for folder in self._get_view(vim.Folder) if self._is_vm_folder(folder)]
        virtual_machines = self._get_view(vim.VirtualMachine)

        return {
            "about": self._serialize_about(content.about),
            "summary": {
                "datacenters": len(datacenters),
                "clusters": len(clusters),
                "hosts": len(hosts),
                "datastores": len(datastores),
                "networks": len(networks),
                "resource_pools": len(resource_pools),
                "vm_folders": len(folders),
                "virtual_machines": len(virtual_machines),
            },
            "datacenters": [self._serialize_named_object(item) for item in datacenters],
            "clusters": [self._serialize_cluster(item) for item in clusters],
            "hosts": [self._serialize_host_summary(item) for item in hosts],
            "datastores": [self._serialize_datastore(item) for item in datastores],
            "networks": [self._serialize_named_object(item) for item in networks],
            "resource_pools": [self._serialize_resource_pool(item) for item in resource_pools],
            "folders": [self._serialize_folder(item) for item in folders],
        }

    def list_virtual_machines(self) -> list[dict[str, Any]]:
        vms = [self._serialize_vm_summary(vm) for vm in self._get_view(vim.VirtualMachine)]
        return sorted(vms, key=lambda item: item["name"].lower())

    def get_virtual_machine_details(self, moid: str) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        details = self._serialize_vm_summary(vm)
        details.update(
            {
                "instance_uuid": getattr(vm.config, "instanceUuid", None),
                "bios_uuid": getattr(vm.config, "uuid", None),
                "annotation": getattr(vm.config, "annotation", "") or "",
                "boot_time": self._serialize_datetime(getattr(vm.runtime, "bootTime", None)),
                "guest_hostname": getattr(vm.guest, "hostName", None),
                "guest_state": getattr(vm.guest, "guestState", None),
                "guest_disks": self._serialize_guest_disks(vm),
                "network_adapters": self._serialize_vm_network_adapters(vm),
                "cdroms": self._serialize_vm_cdroms(vm),
                "performance": self._query_latest_performance(vm),
                "snapshots": self._serialize_snapshot_tree(
                    getattr(getattr(vm, "snapshot", None), "rootSnapshotList", [])
                ),
            }
        )
        return details

    def get_virtual_machine_remote_access(
        self,
        moid: str,
        *,
        management_host: str,
        management_port: int,
        management_username: str,
    ) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        guest_full_name = getattr(getattr(vm, "config", None), "guestFullName", None) or ""
        guest_ip = getattr(getattr(vm, "guest", None), "ipAddress", None)
        guest_platform = self._guess_guest_platform(guest_full_name)
        default_guest_user = "Administrator" if guest_platform == "windows" else "root"

        return {
            "vmrc_url": self._build_vmrc_url(
                management_host=management_host,
                management_port=management_port,
                management_username=management_username,
                moid=moid,
            ),
            "management_host": management_host,
            "management_port": management_port,
            "management_username": management_username,
            "guest_ip": guest_ip,
            "guest_platform": guest_platform,
            "default_guest_user": default_guest_user,
            "ssh_available": bool(guest_ip) and guest_platform != "windows",
            "rdp_available": bool(guest_ip) and guest_platform == "windows",
            "vnc_available": False,
            "vnc_note": "VNC nao e nativo no vSphere. Exige um servidor VNC dentro do sistema operacional da VM.",
            "vmrc_note": (
                "VMRC usa o console nativo da VMware e funciona mesmo quando a rede da VM esta indisponivel. "
                "Exige o cliente VMware Remote Console instalado."
            ),
        }

    def build_rdp_file(
        self,
        moid: str,
        *,
        guest_username: str | None = None,
    ) -> tuple[str, str]:
        vm = self._find_object(vim.VirtualMachine, moid)
        guest_full_name = getattr(getattr(vm, "config", None), "guestFullName", None) or ""
        guest_ip = getattr(getattr(vm, "guest", None), "ipAddress", None)
        if not guest_ip:
            raise VsphereError("A VM nao possui IP conhecido para gerar acesso RDP.")
        if self._guess_guest_platform(guest_full_name) != "windows":
            raise VsphereError("RDP foi habilitado apenas para VMs Windows.")

        lines = [
            "screen mode id:i:2",
            "use multimon:i:0",
            "desktopwidth:i:1600",
            "desktopheight:i:900",
            "session bpp:i:32",
            f"full address:s:{guest_ip}",
            "prompt for credentials:i:1",
            "authentication level:i:2",
            "enablecredsspsupport:i:1",
            "redirectclipboard:i:1",
            "redirectprinters:i:0",
            "redirectcomports:i:0",
            "redirectsmartcards:i:1",
            "audiomode:i:0",
        ]

        if guest_username:
            lines.append(f"username:s:{guest_username}")

        filename = f"{getattr(vm, 'name', 'vm')}.rdp"
        return filename, "\r\n".join(lines) + "\r\n"

    def power_virtual_machine(self, moid: str, action: str) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        action_map = {
            "power_on": lambda: vm.PowerOnVM_Task(),
            "power_off": lambda: vm.PowerOffVM_Task(),
            "reset": lambda: vm.ResetVM_Task(),
            "suspend": lambda: vm.SuspendVM_Task(),
        }

        if action == "shutdown_guest":
            self._require_vmware_tools(vm)
            vm.ShutdownGuest()
            return self.get_virtual_machine_details(moid)
        if action == "reboot_guest":
            self._require_vmware_tools(vm)
            vm.RebootGuest()
            return self.get_virtual_machine_details(moid)
        if action not in action_map:
            raise VsphereError("Acao de energia da VM nao suportada.")

        self._wait_for_task(action_map[action](), f"Falha ao executar {action} na VM.")
        return self.get_virtual_machine_details(moid)

    def rename_virtual_machine(self, moid: str, new_name: str) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        self._wait_for_task(vm.Rename_Task(new_name), "Falha ao renomear a VM.")
        return self.get_virtual_machine_details(moid)

    def reconfigure_virtual_machine(
        self,
        moid: str,
        *,
        cpu_count: int | None = None,
        memory_mb: int | None = None,
    ) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        spec = vim.vm.ConfigSpec()
        if cpu_count is not None:
            if cpu_count < 1:
                raise VsphereError("CPU deve ser maior que zero.")
            spec.numCPUs = cpu_count
        if memory_mb is not None:
            if memory_mb < 4:
                raise VsphereError("Memoria deve ser informada em MB e ser maior que 4.")
            spec.memoryMB = memory_mb

        self._wait_for_task(vm.ReconfigVM_Task(spec=spec), "Falha ao atualizar hardware da VM.")
        return self.get_virtual_machine_details(moid)

    def list_snapshots(self, moid: str) -> list[dict[str, Any]]:
        vm = self._find_object(vim.VirtualMachine, moid)
        return self._serialize_snapshot_tree(getattr(getattr(vm, "snapshot", None), "rootSnapshotList", []))

    def create_snapshot(
        self,
        moid: str,
        *,
        name: str,
        description: str,
        include_memory: bool,
        quiesce: bool,
    ) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        self._wait_for_task(
            vm.CreateSnapshot_Task(
                name=name,
                description=description,
                memory=include_memory,
                quiesce=quiesce,
            ),
            "Falha ao criar snapshot.",
        )
        return self.get_virtual_machine_details(moid)

    def revert_snapshot(self, moid: str, snapshot_moid: str) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        snapshot = self._find_snapshot(vm, snapshot_moid)
        self._wait_for_task(snapshot.RevertToSnapshot_Task(), "Falha ao reverter snapshot.")
        return self.get_virtual_machine_details(moid)

    def delete_snapshot(self, moid: str, snapshot_moid: str) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        snapshot = self._find_snapshot(vm, snapshot_moid)
        self._wait_for_task(
            snapshot.RemoveSnapshot_Task(removeChildren=False, consolidate=True),
            "Falha ao remover snapshot.",
        )
        return self.get_virtual_machine_details(moid)

    def clone_virtual_machine(
        self,
        moid: str,
        *,
        name: str,
        folder_moid: str | None,
        resource_pool_moid: str | None,
        datastore_moid: str | None,
        power_on: bool,
        as_template: bool,
    ) -> dict[str, Any]:
        source_vm = self._find_object(vim.VirtualMachine, moid)
        destination_folder = self._resolve_clone_folder(source_vm, folder_moid)
        resource_pool = self._resolve_clone_pool(source_vm, resource_pool_moid)
        datastore = self._resolve_clone_datastore(source_vm, datastore_moid)

        relocate = vim.vm.RelocateSpec()
        if resource_pool is not None:
            relocate.pool = resource_pool
        if datastore is not None:
            relocate.datastore = datastore

        clone_spec = vim.vm.CloneSpec(
            location=relocate,
            powerOn=power_on,
            template=as_template,
        )

        cloned_vm = self._wait_for_task(
            source_vm.CloneVM_Task(folder=destination_folder, name=name, spec=clone_spec),
            "Falha ao clonar VM.",
        )
        if cloned_vm is None:
            cloned_vm = self._find_virtual_machine_by_name(name)
        return self._serialize_vm_summary(cloned_vm)

    def create_virtual_machine(
        self,
        *,
        name: str,
        guest_id: str,
        cpu_count: int,
        memory_mb: int,
        disk_gb: int,
        host_moid: str | None,
        folder_moid: str | None,
        resource_pool_moid: str | None,
        datastore_moid: str,
        network_moid: str | None,
        power_on: bool,
        iso_datastore_moid: str | None = None,
        iso_path: str | None = None,
    ) -> dict[str, Any]:
        normalized_name = str(name or "").strip()
        normalized_guest_id = str(guest_id or "").strip()
        if not normalized_name:
            raise VsphereError("Informe o nome da nova VM.")
        if not normalized_guest_id:
            raise VsphereError("Informe o guest ID da nova VM.")
        if cpu_count < 1:
            raise VsphereError("A nova VM precisa de pelo menos 1 vCPU.")
        if memory_mb < 256:
            raise VsphereError("A memoria minima recomendada e 256 MB.")
        if disk_gb < 1:
            raise VsphereError("O disco da nova VM precisa ter ao menos 1 GB.")

        host = self._resolve_create_host(host_moid)
        folder = self._resolve_create_folder(folder_moid, host)
        resource_pool = self._resolve_create_pool(resource_pool_moid, host)
        if resource_pool is None:
            raise VsphereError("Nao foi possivel determinar o resource pool da nova VM.")

        datastore = self._find_object(vim.Datastore, datastore_moid)
        vm_files = vim.vm.FileInfo(vmPathName=f"[{datastore.name}]")
        config = vim.vm.ConfigSpec(
            name=normalized_name,
            guestId=normalized_guest_id,
            numCPUs=int(cpu_count),
            memoryMB=int(memory_mb),
            files=vm_files,
        )
        if iso_path:
            config.bootOptions = vim.vm.BootOptions(
                bootOrder=[
                    vim.vm.BootOptions.BootableCdromDevice(),
                    vim.vm.BootOptions.BootableDiskDevice(),
                ]
            )

        device_changes: list[Any] = []

        scsi_controller = vim.vm.device.VirtualLsiLogicController()
        scsi_controller.key = 1000
        scsi_controller.busNumber = 0
        scsi_controller.sharedBus = vim.vm.device.VirtualSCSIController.Sharing.noSharing
        device_changes.append(
            self._build_device_change(vim.vm.device.VirtualDeviceSpec.Operation.add, scsi_controller)
        )

        disk = vim.vm.device.VirtualDisk()
        disk.key = -1
        disk.unitNumber = 0
        disk.controllerKey = scsi_controller.key
        disk.capacityInKB = int(disk_gb) * 1024 * 1024
        disk.backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
        disk.backing.diskMode = "persistent"
        disk.backing.thinProvisioned = True
        disk.backing.fileName = f"[{datastore.name}]"
        device_changes.append(
            self._build_device_change(
                vim.vm.device.VirtualDeviceSpec.Operation.add,
                disk,
                file_operation=vim.vm.device.VirtualDeviceSpec.FileOperation.create,
            )
        )

        if network_moid:
            network = self._find_network(network_moid)
            nic = self._build_virtual_nic(network)
            device_changes.append(
                self._build_device_change(vim.vm.device.VirtualDeviceSpec.Operation.add, nic)
            )

        if iso_path:
            iso_datastore = self._find_object(vim.Datastore, iso_datastore_moid or datastore_moid)
            ide_controller = vim.vm.device.VirtualIDEController()
            ide_controller.key = 200
            ide_controller.busNumber = 0
            device_changes.append(
                self._build_device_change(vim.vm.device.VirtualDeviceSpec.Operation.add, ide_controller)
            )

            cdrom = self._build_virtual_cdrom(
                controller_key=ide_controller.key,
                datastore=iso_datastore,
                iso_path=iso_path,
                connected=False,
                start_connected=True,
            )
            device_changes.append(
                self._build_device_change(vim.vm.device.VirtualDeviceSpec.Operation.add, cdrom)
            )

        config.deviceChange = device_changes
        create_kwargs = {
            "config": config,
            "pool": resource_pool,
        }
        if host is not None:
            create_kwargs["host"] = host

        created_vm = self._wait_for_task(
            folder.CreateVM_Task(**create_kwargs),
            "Falha ao criar a nova VM.",
        )
        if created_vm is None:
            created_vm = self._find_virtual_machine_by_name(normalized_name)

        if power_on:
            self._wait_for_task(created_vm.PowerOnVM_Task(), "Falha ao ligar a nova VM.")

        return self.get_virtual_machine_details(getattr(created_vm, "_moId", None))

    def list_datastore_isos(self, datastore_moid: str, *, folder_path: str | None = None) -> list[dict[str, Any]]:
        datastore = self._find_object(vim.Datastore, datastore_moid)
        browser = getattr(datastore, "browser", None)
        if browser is None:
            raise VsphereError("O datastore selecionado nao oferece browser de arquivos.")

        normalized_folder = self._normalize_datastore_subpath(folder_path or "")
        search_root = f"[{datastore.name}]"
        if normalized_folder:
            search_root = f"{search_root} {normalized_folder}"

        search_spec = vim.HostDatastoreBrowser.SearchSpec(matchPattern=["*.iso"])
        results = self._wait_for_task(
            browser.SearchDatastoreSubFolders_Task(searchPath=search_root, searchSpec=search_spec),
            "Falha ao listar ISOs do datastore.",
        ) or []

        items: list[dict[str, Any]] = []
        prefix = f"[{datastore.name}]"
        for result in results:
            folder_label = str(getattr(result, "folderPath", "") or "")
            relative_folder = folder_label[len(prefix):].strip() if folder_label.startswith(prefix) else folder_label.strip()
            relative_folder = relative_folder.rstrip("/")
            for file_info in getattr(result, "file", []) or []:
                filename = getattr(file_info, "path", None)
                if not filename:
                    continue
                relative_path = "/".join(
                    part for part in (relative_folder, filename) if part
                )
                items.append(
                    {
                        "datastore_moid": getattr(datastore, "_moId", None),
                        "datastore_name": getattr(datastore, "name", None),
                        "path": relative_path,
                        "full_path": self._build_datastore_file_name(datastore, relative_path),
                        "size_bytes": getattr(file_info, "fileSize", None),
                        "modified_at": self._serialize_datetime(getattr(file_info, "modification", None)),
                    }
                )

        return sorted(items, key=lambda item: str(item.get("path") or "").lower())

    def upload_iso_to_datastore(
        self,
        datastore_moid: str,
        *,
        file_stream: Any,
        filename: str,
        content_length: int | None,
        management_host: str,
        management_port: int,
        verify_ssl: bool,
        overwrite: bool = False,
        folder_path: str | None = None,
    ) -> dict[str, Any]:
        datastore = self._find_object(vim.Datastore, datastore_moid)
        sanitized_filename = self._sanitize_upload_filename(filename)
        if not sanitized_filename.lower().endswith(".iso"):
            raise VsphereError("Apenas arquivos .iso sao suportados neste envio.")

        relative_folder = self._normalize_datastore_subpath(folder_path or "iso")
        relative_path = "/".join(part for part in (relative_folder, sanitized_filename) if part)
        datacenter = self._find_datacenter_for_object(datastore)
        if datacenter is None:
            raise VsphereError("Nao foi possivel determinar o datacenter do datastore.")

        prepared_stream, resolved_length, cleanup_path = self._materialize_stream_if_needed(file_stream, content_length)

        request_path = (
            f"/folder/{quote(relative_path, safe='/')}?"
            f"{urlencode({'dcPath': datacenter.name, 'dsName': datastore.name})}"
        )
        cookie = getattr(getattr(self.service_instance, "_stub", None), "cookie", None)
        if not cookie:
            raise VsphereError("Nao foi possivel obter o cookie de sessao do vSphere para enviar a ISO.")

        connection = http.client.HTTPSConnection(
            host=management_host,
            port=int(management_port or 443),
            context=self._build_ssl_context(verify_ssl),
            timeout=600,
        )
        try:
            connection.putrequest("PUT", request_path)
            connection.putheader("Cookie", cookie)
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Content-Length", str(int(resolved_length)))
            connection.putheader("Overwrite", "T" if overwrite else "F")
            connection.endheaders()

            while True:
                chunk = prepared_stream.read(1024 * 1024)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                connection.send(chunk)

            response = connection.getresponse()
            response_body = response.read().decode("utf-8", errors="replace")
        finally:
            connection.close()
            try:
                prepared_stream.close()
            except Exception:
                pass
            if cleanup_path:
                try:
                    cleanup_path.unlink(missing_ok=True)
                except Exception:
                    pass

        if response.status not in {200, 201}:
            details = response_body.strip()
            if response.status == 409:
                raise VsphereError("Ja existe um arquivo com esse nome no datastore. Marque sobrescrever para substituir.")
            raise VsphereError(
                f"Falha ao enviar ISO para o datastore: HTTP {response.status} {details[:220]}".strip()
            )

        return {
            "datastore_moid": getattr(datastore, "_moId", None),
            "datastore_name": getattr(datastore, "name", None),
            "path": relative_path,
            "full_path": self._build_datastore_file_name(datastore, relative_path),
            "size_bytes": int(resolved_length),
        }

    def upload_iso_from_url(
        self,
        datastore_moid: str,
        *,
        source_url: str,
        management_host: str,
        management_port: int,
        verify_ssl: bool,
        overwrite: bool = False,
        folder_path: str | None = None,
    ) -> dict[str, Any]:
        normalized_url = str(source_url or "").strip()
        parsed = urlsplit(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise VsphereError("Informe uma URL HTTP/HTTPS valida para baixar a ISO.")

        filename = self._sanitize_upload_filename(parsed.path or "")
        if not filename.lower().endswith(".iso"):
            raise VsphereError("A URL precisa apontar para um arquivo .iso.")

        request = Request(
            normalized_url,
            headers={"User-Agent": "vsphere-flask-client/1.0"},
        )
        try:
            with urlopen(request, timeout=180) as response:
                content_length_header = response.headers.get("Content-Length")
                content_length = int(content_length_header) if content_length_header else None
                return self.upload_iso_to_datastore(
                    datastore_moid,
                    file_stream=response,
                    filename=filename,
                    content_length=content_length,
                    management_host=management_host,
                    management_port=management_port,
                    verify_ssl=verify_ssl,
                    overwrite=overwrite,
                    folder_path=folder_path,
                )
        except VsphereError:
            raise
        except Exception as exc:
            raise VsphereError(f"Falha ao baixar a ISO da URL informada: {exc}") from exc

    def mount_virtual_machine_iso(
        self,
        moid: str,
        *,
        datastore_moid: str,
        iso_path: str,
        connect_at_power_on: bool = True,
    ) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        datastore = self._find_object(vim.Datastore, datastore_moid)
        cdrom = self._find_virtual_cdrom(vm)
        ide_controller = self._find_virtual_ide_controller(vm)
        device_changes: list[Any] = []

        if cdrom is None:
            if ide_controller is None:
                ide_controller = vim.vm.device.VirtualIDEController()
                ide_controller.key = 200
                ide_controller.busNumber = 0
                device_changes.append(
                    self._build_device_change(vim.vm.device.VirtualDeviceSpec.Operation.add, ide_controller)
                )

            cdrom = self._build_virtual_cdrom(
                controller_key=ide_controller.key,
                datastore=datastore,
                iso_path=iso_path,
                connected=self._is_vm_powered_on(vm),
                start_connected=connect_at_power_on,
            )
            device_changes.append(
                self._build_device_change(vim.vm.device.VirtualDeviceSpec.Operation.add, cdrom)
            )
        else:
            connectable = getattr(cdrom, "connectable", None) or vim.vm.device.VirtualDevice.ConnectInfo()
            connectable.allowGuestControl = True
            connectable.startConnected = connect_at_power_on
            connectable.connected = self._is_vm_powered_on(vm)
            cdrom.connectable = connectable
            cdrom.backing = vim.vm.device.VirtualCdrom.IsoBackingInfo(
                fileName=self._build_datastore_file_name(datastore, iso_path),
                datastore=datastore,
            )
            device_changes.append(
                self._build_device_change(vim.vm.device.VirtualDeviceSpec.Operation.edit, cdrom)
            )

        spec = vim.vm.ConfigSpec(deviceChange=device_changes)
        self._wait_for_task(vm.ReconfigVM_Task(spec=spec), "Falha ao montar a ISO na VM.")
        return self.get_virtual_machine_details(moid)

    def eject_virtual_machine_iso(self, moid: str) -> dict[str, Any]:
        vm = self._find_object(vim.VirtualMachine, moid)
        cdrom = self._find_virtual_cdrom(vm)
        if cdrom is None:
            return self.get_virtual_machine_details(moid)

        connectable = getattr(cdrom, "connectable", None) or vim.vm.device.VirtualDevice.ConnectInfo()
        connectable.allowGuestControl = True
        connectable.startConnected = False
        connectable.connected = False
        cdrom.connectable = connectable
        cdrom.backing = vim.vm.device.VirtualCdrom.AtapiBackingInfo(
            deviceName="",
            useAutoDetect=True,
        )

        spec = vim.vm.ConfigSpec(
            deviceChange=[
                self._build_device_change(vim.vm.device.VirtualDeviceSpec.Operation.edit, cdrom)
            ]
        )
        self._wait_for_task(vm.ReconfigVM_Task(spec=spec), "Falha ao ejetar a ISO da VM.")
        return self.get_virtual_machine_details(moid)

    def list_hosts(self) -> list[dict[str, Any]]:
        hosts = [self._serialize_host_details(host) for host in self._get_view(vim.HostSystem)]
        return sorted(hosts, key=lambda item: item["name"].lower())

    def get_host_details(self, moid: str) -> dict[str, Any]:
        host = self._find_object(vim.HostSystem, moid)
        details = self._serialize_host_details(host)
        details.update(
            {
                "boot_time": self._serialize_datetime(getattr(getattr(host, "runtime", None), "bootTime", None)),
                "license": self._serialize_license_info(host),
                "network": self._serialize_host_network(host),
                "datastores": [self._serialize_datastore(item) for item in getattr(host, "datastore", []) or []],
                "virtual_machines": sorted(
                    [self._serialize_vm_host_reference(item) for item in getattr(host, "vm", []) or []],
                    key=lambda item: item["name"].lower(),
                ),
                "performance": self._query_latest_performance(host),
            }
        )
        return details

    def set_host_maintenance(self, moid: str, *, enabled: bool) -> dict[str, Any]:
        host = self._find_object(vim.HostSystem, moid)
        if enabled:
            task = host.EnterMaintenanceMode_Task(timeout=0)
            self._wait_for_task(task, "Falha ao entrar em maintenance mode.")
        else:
            task = host.ExitMaintenanceMode_Task(timeout=0)
            self._wait_for_task(task, "Falha ao sair de maintenance mode.")
        return self._serialize_host_details(host)

    def power_host(self, moid: str, action: str) -> dict[str, Any]:
        host = self._find_object(vim.HostSystem, moid)
        if action == "reboot":
            self._wait_for_task(host.RebootHost_Task(force=True), "Falha ao reiniciar host.")
        elif action == "shutdown":
            self._wait_for_task(host.ShutdownHost_Task(force=True), "Falha ao desligar host.")
        else:
            raise VsphereError("Acao de host nao suportada.")
        return self._serialize_host_details(host)

    def _content(self):
        return self.service_instance.RetrieveContent()

    def _get_view(self, managed_type):
        content = self._content()
        view = content.viewManager.CreateContainerView(content.rootFolder, [managed_type], True)
        try:
            return list(view.view)
        finally:
            view.Destroy()

    def _find_object(self, managed_type, moid: str):
        for item in self._get_view(managed_type):
            if getattr(item, "_moId", None) == moid:
                return item
        raise VsphereError(f"Objeto {moid} nao encontrado.")

    def _find_virtual_machine_by_name(self, name: str):
        matches = [vm for vm in self._get_view(vim.VirtualMachine) if vm.name == name]
        if not matches:
            raise VsphereError("Clone finalizado, mas a VM clonada nao foi localizada pelo nome.")
        matches.sort(key=lambda item: self._serialize_datetime(getattr(item.runtime, "bootTime", None)) or "")
        return matches[-1]

    def _find_snapshot(self, vm, snapshot_moid: str):
        tree = getattr(getattr(vm, "snapshot", None), "rootSnapshotList", [])
        for node in self._walk_snapshot_tree(tree):
            if getattr(node.snapshot, "_moId", None) == snapshot_moid:
                return node.snapshot
        raise VsphereError("Snapshot nao encontrado.")

    def _walk_snapshot_tree(self, nodes: Iterable[Any]):
        for node in nodes:
            yield node
            children = getattr(node, "childSnapshotList", []) or []
            yield from self._walk_snapshot_tree(children)

    def _wait_for_task(self, task, default_message: str):
        while task.info.state in (vim.TaskInfo.State.queued, vim.TaskInfo.State.running):
            time.sleep(1)

        if task.info.state == vim.TaskInfo.State.success:
            return task.info.result

        error = getattr(task.info, "error", None)
        if error is not None:
            message = getattr(error, "msg", None) or str(error)
            raise VsphereError(message)
        raise VsphereError(default_message)

    def _require_vmware_tools(self, vm) -> None:
        status = getattr(vm.guest, "toolsRunningStatus", "")
        if status != "guestToolsRunning":
            raise VsphereError("A acao guest exige VMware Tools em execucao na VM.")

    def _resolve_clone_folder(self, source_vm, folder_moid: str | None):
        if folder_moid:
            return self._find_object(vim.Folder, folder_moid)
        parent = getattr(source_vm, "parent", None)
        if isinstance(parent, vim.Folder):
            return parent
        raise VsphereError("Nao foi possivel determinar a pasta de destino do clone.")

    def _resolve_clone_pool(self, source_vm, resource_pool_moid: str | None):
        if resource_pool_moid:
            return self._find_object(vim.ResourcePool, resource_pool_moid)

        resource_pool = getattr(source_vm, "resourcePool", None)
        if resource_pool is not None:
            return resource_pool

        runtime_host = getattr(source_vm.runtime, "host", None)
        compute_resource = getattr(runtime_host, "parent", None)
        return getattr(compute_resource, "resourcePool", None)

    def _resolve_clone_datastore(self, source_vm, datastore_moid: str | None):
        if datastore_moid:
            return self._find_object(vim.Datastore, datastore_moid)
        datastores = getattr(source_vm, "datastore", None) or []
        return datastores[0] if datastores else None

    def _resolve_create_host(self, host_moid: str | None):
        if host_moid:
            return self._find_object(vim.HostSystem, host_moid)

        hosts = self._get_view(vim.HostSystem)
        if not hosts:
            raise VsphereError("Nenhum host disponivel para criar a VM.")
        hosts.sort(key=lambda item: str(getattr(item, "name", "")).lower())
        return hosts[0]

    def _resolve_create_folder(self, folder_moid: str | None, host) -> Any:
        if folder_moid:
            return self._find_object(vim.Folder, folder_moid)

        datacenter = self._find_datacenter_for_object(host)
        vm_folder = getattr(datacenter, "vmFolder", None) if datacenter is not None else None
        if vm_folder is not None:
            return vm_folder

        folders = [folder for folder in self._get_view(vim.Folder) if self._is_vm_folder(folder)]
        if not folders:
            raise VsphereError("Nao foi possivel determinar a pasta de destino da nova VM.")
        folders.sort(key=lambda item: str(getattr(item, "name", "")).lower())
        return folders[0]

    def _resolve_create_pool(self, resource_pool_moid: str | None, host) -> Any:
        if resource_pool_moid:
            return self._find_object(vim.ResourcePool, resource_pool_moid)

        compute_resource = getattr(host, "parent", None)
        pool = getattr(compute_resource, "resourcePool", None)
        if pool is not None:
            return pool

        pools = self._get_view(vim.ResourcePool)
        if not pools:
            return None
        pools.sort(key=lambda item: str(getattr(item, "name", "")).lower())
        return pools[0]

    def _find_network(self, network_moid: str):
        for managed_type in (vim.Network, vim.dvs.DistributedVirtualPortgroup):
            try:
                return self._find_object(managed_type, network_moid)
            except VsphereError:
                continue
        raise VsphereError("Rede nao encontrada para a nova VM.")

    def _find_datacenter_for_object(self, obj) -> Any | None:
        current = obj
        visited = 0
        while current is not None and visited < 20:
            if isinstance(current, vim.Datacenter):
                return current
            current = getattr(current, "parent", None)
            visited += 1
        return None

    def _build_device_change(self, operation, device, *, file_operation=None):
        change = vim.vm.device.VirtualDeviceSpec()
        change.operation = operation
        if file_operation is not None:
            change.fileOperation = file_operation
        change.device = device
        return change

    def _build_virtual_nic(self, network):
        nic = vim.vm.device.VirtualE1000e()
        nic.key = -1
        nic.addressType = "generated"
        nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
            startConnected=True,
            connected=False,
            allowGuestControl=True,
        )

        if isinstance(network, vim.dvs.DistributedVirtualPortgroup):
            port = vim.dvs.PortConnection(
                portgroupKey=getattr(network, "key", None),
                switchUuid=getattr(getattr(getattr(network, "config", None), "distributedVirtualSwitch", None), "uuid", None),
            )
            nic.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(port=port)
        else:
            nic.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
                deviceName=getattr(network, "name", None),
                network=network,
            )
        return nic

    def _build_virtual_cdrom(
        self,
        *,
        controller_key: int,
        datastore,
        iso_path: str,
        connected: bool,
        start_connected: bool,
    ):
        cdrom = vim.vm.device.VirtualCdrom()
        cdrom.key = -1
        cdrom.controllerKey = controller_key
        cdrom.unitNumber = 0
        cdrom.backing = vim.vm.device.VirtualCdrom.IsoBackingInfo(
            fileName=self._build_datastore_file_name(datastore, iso_path),
            datastore=datastore,
        )
        cdrom.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
            startConnected=start_connected,
            connected=connected,
            allowGuestControl=True,
        )
        return cdrom

    def _find_virtual_cdrom(self, vm):
        devices = getattr(getattr(getattr(vm, "config", None), "hardware", None), "device", []) or []
        for device in devices:
            if isinstance(device, vim.vm.device.VirtualCdrom):
                return device
        return None

    def _find_virtual_ide_controller(self, vm):
        devices = getattr(getattr(getattr(vm, "config", None), "hardware", None), "device", []) or []
        for device in devices:
            if isinstance(device, vim.vm.device.VirtualIDEController):
                return device
        return None

    def _is_vm_powered_on(self, vm) -> bool:
        return str(getattr(getattr(vm, "runtime", None), "powerState", "")) == "poweredOn"

    def _sanitize_upload_filename(self, filename: str) -> str:
        raw = str(filename or "").strip().replace("\\", "/")
        sanitized = raw.split("/")[-1]
        if not sanitized:
            raise VsphereError("Informe um nome de arquivo ISO valido.")
        return sanitized

    def _normalize_datastore_subpath(self, path: str | None) -> str:
        normalized = str(path or "").replace("\\", "/").strip().strip("/")
        safe_parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
        return "/".join(safe_parts)

    def _build_datastore_file_name(self, datastore, relative_path: str) -> str:
        safe_path = self._normalize_datastore_subpath(relative_path)
        if not safe_path:
            raise VsphereError("Caminho da ISO no datastore e obrigatorio.")
        return f"[{datastore.name}] {safe_path}"

    def _materialize_stream_if_needed(self, stream: Any, content_length: int | None) -> tuple[Any, int, Path | None]:
        if content_length is not None and int(content_length) > 0:
            try:
                if hasattr(stream, "seek"):
                    stream.seek(0)
            except Exception:
                pass
            return stream, int(content_length), None

        temp_file = tempfile.NamedTemporaryFile(prefix="vsphere-iso-", suffix=".bin", delete=False)
        cleanup_path = Path(temp_file.name)
        total_size = 0
        try:
            if hasattr(stream, "seek"):
                try:
                    stream.seek(0)
                except Exception:
                    pass
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                temp_file.write(chunk)
                total_size += len(chunk)
        finally:
            temp_file.close()

        if total_size <= 0:
            try:
                cleanup_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise VsphereError("Nao foi possivel determinar ou ler o conteudo da ISO enviada.")

        prepared_stream = cleanup_path.open("rb")
        return prepared_stream, total_size, cleanup_path

    def _query_latest_performance(self, entity) -> dict[str, Any]:
        content = self._content()
        perf_manager = getattr(content, "perfManager", None)
        if perf_manager is None:
            return {}

        try:
            provider = perf_manager.QueryProviderSummary(entity)
            refresh_rate = getattr(provider, "refreshRate", None) or 20
            available_metrics = perf_manager.QueryAvailablePerfMetric(entity=entity, intervalId=refresh_rate) or []
        except Exception:
            return {}

        available_instances: dict[int, str] = {}
        for metric in available_metrics:
            counter_id = getattr(metric, "counterId", None)
            if counter_id is None:
                continue
            instance = getattr(metric, "instance", "") or ""
            current = available_instances.get(counter_id)
            if current is None or (current and not instance):
                available_instances[counter_id] = instance

        counters_by_path = {
            self._perf_counter_path(counter): counter
            for counter in getattr(perf_manager, "perfCounter", []) or []
        }

        selected_metric_ids = []
        selected_counters: dict[int, tuple[str, Any]] = {}
        for label, path_parts in self.PERF_COUNTERS.items():
            counter = counters_by_path.get(".".join(path_parts))
            if counter is None:
                continue
            instance = available_instances.get(counter.key)
            if instance is None:
                continue
            selected_metric_ids.append(
                vim.PerformanceManager.MetricId(counterId=counter.key, instance=instance)
            )
            selected_counters[counter.key] = (label, counter)

        if not selected_metric_ids:
            return {}

        try:
            query = vim.PerformanceManager.QuerySpec(
                entity=entity,
                metricId=selected_metric_ids,
                intervalId=refresh_rate,
                maxSample=1,
            )
            results = perf_manager.QueryPerf(querySpec=[query]) or []
        except Exception:
            return {}

        if not results:
            return {}

        entity_metric = results[0]
        sample_info = getattr(entity_metric, "sampleInfo", []) or []
        performance: dict[str, Any] = {
            "sample_time": self._serialize_datetime(
                getattr(sample_info[-1], "timestamp", None) if sample_info else None
            ),
        }

        for series in getattr(entity_metric, "value", []) or []:
            counter_id = getattr(getattr(series, "id", None), "counterId", None)
            if counter_id not in selected_counters:
                continue
            values = getattr(series, "value", []) or []
            if not values:
                continue
            label, counter = selected_counters[counter_id]
            performance[label] = self._normalize_perf_value(counter, values[-1])

        return performance

    def _perf_counter_path(self, counter) -> str:
        group = getattr(getattr(counter, "groupInfo", None), "key", "")
        name = getattr(getattr(counter, "nameInfo", None), "key", "")
        rollup = str(getattr(counter, "rollupType", "") or "").lower()
        return f"{group}.{name}.{rollup}"

    def _normalize_perf_value(self, counter, raw_value: int | float) -> dict[str, Any]:
        unit_key = getattr(getattr(counter, "unitInfo", None), "key", None)
        label = getattr(getattr(counter, "nameInfo", None), "label", None)

        value = float(raw_value)
        display_value = value
        display_unit = unit_key

        if unit_key == "percent":
            display_value = round(value / 100, 2)
            display_unit = "%"
        elif unit_key == "kiloBytesPerSecond":
            display_value = round(value / 1024, 2)
            display_unit = "MB/s"
        elif unit_key == "megaHertz":
            display_value = round(value, 2)
            display_unit = "MHz"
        else:
            display_value = round(value, 2)

        return {
            "raw_value": raw_value,
            "value": display_value,
            "unit": display_unit,
            "counter_label": label,
            "counter_name": self._perf_counter_path(counter),
        }

    def _serialize_license_info(self, host) -> dict[str, Any]:
        manager = getattr(self._content(), "licenseManager", None)
        if manager is None:
            return {}

        assignment = None
        assignment_manager = getattr(manager, "licenseAssignmentManager", None)
        if assignment_manager is not None:
            try:
                assigned = assignment_manager.QueryAssignedLicenses(getattr(host, "_moId", None)) or []
                assignment = assigned[0] if assigned else None
            except Exception:
                assignment = None

        try:
            usage = manager.QueryUsage(host)
        except Exception:
            usage = None

        evaluation = getattr(manager, "evaluation", None)
        evaluation_properties = self._serialize_key_any_values(getattr(evaluation, "properties", []) or [])
        expires_on = self._find_license_expiration(
            usage=usage,
            assignment=assignment,
            evaluation_properties=evaluation_properties,
        )

        remaining_hours = None
        for key, value in evaluation_properties.items():
            normalized_key = str(key).lower()
            if "remaining" in normalized_key and "hour" in normalized_key:
                try:
                    remaining_hours = int(value)
                except (TypeError, ValueError):
                    remaining_hours = None
                break

        return {
            "edition": getattr(manager, "licensedEdition", None),
            "assigned_license": self._serialize_license_assignment(assignment),
            "usage": self._serialize_license_usage(usage),
            "evaluation": evaluation_properties,
            "expires_on": expires_on,
            "remaining_hours": remaining_hours,
        }

    def _find_license_expiration(self, *, usage, assignment, evaluation_properties: dict[str, Any]) -> str | None:
        candidates: list[datetime] = []

        feature_info = getattr(usage, "featureInfo", []) if usage is not None else []
        for feature in feature_info or []:
            expires_on = getattr(feature, "expiresOn", None)
            if expires_on is not None:
                candidates.append(expires_on)

        assigned_license = getattr(assignment, "assignedLicense", None)
        if assigned_license is not None:
            for prop in getattr(assigned_license, "properties", []) or []:
                key = str(getattr(prop, "key", "")).lower()
                value = getattr(prop, "value", None)
                if isinstance(value, datetime) and ("expire" in key or "eval" in key):
                    candidates.append(value)

        for key, value in evaluation_properties.items():
            normalized_key = str(key).lower()
            if isinstance(value, datetime) and ("expire" in normalized_key or "end" in normalized_key):
                candidates.append(value)

        if not candidates:
            return None
        candidates.sort()
        return self._serialize_datetime(candidates[0])

    def _serialize_license_assignment(self, assignment) -> dict[str, Any] | None:
        if assignment is None:
            return None

        assigned_license = getattr(assignment, "assignedLicense", None)
        return {
            "entity_id": getattr(assignment, "entityId", None),
            "entity_display_name": getattr(assignment, "entityDisplayName", None),
            "scope": getattr(assignment, "scope", None),
            "license": self._serialize_license_record(assigned_license),
        }

    def _serialize_license_usage(self, usage) -> dict[str, Any] | None:
        if usage is None:
            return None

        return {
            "source_available": getattr(usage, "sourceAvailable", None),
            "reservations": [
                {
                    "key": getattr(item, "key", None),
                    "state": str(getattr(item, "state", "")) if getattr(item, "state", None) is not None else None,
                    "required": getattr(item, "required", None),
                }
                for item in getattr(usage, "reservationInfo", []) or []
            ],
            "features": [
                {
                    "key": getattr(item, "key", None),
                    "name": getattr(item, "featureName", None),
                    "state": str(getattr(item, "state", "")) if getattr(item, "state", None) is not None else None,
                    "expires_on": self._serialize_datetime(getattr(item, "expiresOn", None)),
                }
                for item in getattr(usage, "featureInfo", []) or []
            ],
        }

    def _serialize_license_record(self, license_info) -> dict[str, Any] | None:
        if license_info is None:
            return None

        return {
            "name": getattr(license_info, "name", None),
            "edition_key": getattr(license_info, "editionKey", None),
            "license_key": getattr(license_info, "licenseKey", None),
            "total": getattr(license_info, "total", None),
            "used": getattr(license_info, "used", None),
            "cost_unit": getattr(license_info, "costUnit", None),
            "properties": self._serialize_key_any_values(getattr(license_info, "properties", []) or []),
            "labels": [
                {
                    "key": getattr(item, "key", None),
                    "value": getattr(item, "value", None),
                }
                for item in getattr(license_info, "labels", []) or []
            ],
        }

    def _serialize_host_network(self, host) -> dict[str, Any]:
        host_config = getattr(host, "config", None)
        network = getattr(host_config, "network", None)
        network_system = getattr(getattr(host, "configManager", None), "networkSystem", None)

        hints_by_device: dict[str, Any] = {}
        if network_system is not None:
            try:
                hints = network_system.QueryNetworkHint(None) or []
                hints_by_device = {
                    getattr(item, "device", ""): item
                    for item in hints
                    if getattr(item, "device", None)
                }
            except Exception:
                hints_by_device = {}

        return {
            "dns_servers": list(getattr(getattr(network, "dnsConfig", None), "address", []) or []),
            "host_name": getattr(getattr(network, "dnsConfig", None), "hostName", None),
            "domain_name": getattr(getattr(network, "dnsConfig", None), "domainName", None),
            "default_gateway": getattr(getattr(network, "ipRouteConfig", None), "defaultGateway", None),
            "physical_nics": [
                self._serialize_physical_nic(item, hints_by_device.get(getattr(item, "device", "")))
                for item in getattr(network, "pnic", []) or []
            ],
            "vmkernel_nics": [
                self._serialize_virtual_nic(item)
                for item in getattr(network, "vnic", []) or []
            ],
            "vswitches": [
                self._serialize_virtual_switch(item)
                for item in getattr(network, "vswitch", []) or []
            ],
            "portgroups": [
                self._serialize_portgroup(item)
                for item in getattr(network, "portgroup", []) or []
            ],
        }

    def _serialize_physical_nic(self, pnic, hint=None) -> dict[str, Any]:
        link_speed = getattr(pnic, "linkSpeed", None)
        configured_speed = getattr(getattr(pnic, "spec", None), "linkSpeed", None)
        hint_connected = getattr(getattr(hint, "connectedSwitchPort", None), "devId", None)
        hint_port = getattr(getattr(hint, "connectedSwitchPort", None), "portId", None)

        return {
            "device": getattr(pnic, "device", None),
            "mac": getattr(pnic, "mac", None),
            "driver": getattr(pnic, "driver", None),
            "pci": getattr(pnic, "pci", None),
            "link_up": link_speed is not None,
            "link_speed_mbps": getattr(link_speed, "speedMb", None),
            "duplex": self._duplex_label(getattr(link_speed, "duplex", None)),
            "configured_speed_mbps": getattr(configured_speed, "speedMb", None),
            "configured_duplex": self._duplex_label(getattr(configured_speed, "duplex", None)),
            "lldp_device": hint_connected,
            "lldp_port": hint_port,
        }

    def _serialize_virtual_nic(self, vnic) -> dict[str, Any]:
        spec = getattr(vnic, "spec", None)
        ip = getattr(spec, "ip", None)

        return {
            "device": getattr(vnic, "device", None),
            "portgroup": getattr(vnic, "portgroup", None),
            "mac": getattr(vnic, "mac", None),
            "mtu": getattr(spec, "mtu", None),
            "ip_address": getattr(ip, "ipAddress", None),
            "subnet_mask": getattr(ip, "subnetMask", None),
            "dhcp": bool(getattr(ip, "dhcp", False)),
            "ipv6_enabled": bool(getattr(spec, "ipV6Enabled", False)),
        }

    def _serialize_virtual_switch(self, vswitch) -> dict[str, Any]:
        spec = getattr(vswitch, "spec", None)
        bridge = getattr(spec, "bridge", None)
        return {
            "name": getattr(vswitch, "name", None),
            "mtu": getattr(spec, "mtu", None),
            "num_ports": getattr(vswitch, "numPorts", None),
            "num_ports_available": getattr(vswitch, "numPortsAvailable", None),
            "uplinks": list(getattr(bridge, "nicDevice", []) or []),
            "teaming": self._serialize_teaming_policy(getattr(getattr(spec, "policy", None), "nicTeaming", None)),
            "security": self._serialize_security_policy(getattr(getattr(spec, "policy", None), "security", None)),
        }

    def _serialize_portgroup(self, portgroup) -> dict[str, Any]:
        spec = getattr(portgroup, "spec", None)
        policy = getattr(spec, "policy", None)
        return {
            "name": getattr(spec, "name", None),
            "vswitch_name": getattr(spec, "vswitchName", None),
            "vlan_id": getattr(spec, "vlanId", None),
            "teaming": self._serialize_teaming_policy(getattr(policy, "nicTeaming", None)),
            "security": self._serialize_security_policy(getattr(policy, "security", None)),
        }

    def _serialize_teaming_policy(self, policy) -> dict[str, Any] | None:
        if policy is None:
            return None

        nic_order = getattr(policy, "nicOrder", None)
        return {
            "policy": getattr(policy, "policy", None),
            "reverse_policy": getattr(policy, "reversePolicy", None),
            "notify_switches": getattr(policy, "notifySwitches", None),
            "rolling_order": getattr(policy, "rollingOrder", None),
            "failure_detection": getattr(getattr(policy, "failureCriteria", None), "checkSpeed", None),
            "active_nics": list(getattr(nic_order, "activeNic", []) or []),
            "standby_nics": list(getattr(nic_order, "standbyNic", []) or []),
        }

    def _serialize_security_policy(self, policy) -> dict[str, Any] | None:
        if policy is None:
            return None

        return {
            "allow_promiscuous": getattr(policy, "allowPromiscuous", None),
            "mac_changes": getattr(policy, "macChanges", None),
            "forged_transmits": getattr(policy, "forgedTransmits", None),
        }

    def _serialize_key_any_values(self, items: Iterable[Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in items or []:
            key = getattr(item, "key", None)
            if key is None:
                continue
            value = getattr(item, "value", None)
            if isinstance(value, datetime):
                result[str(key)] = self._serialize_datetime(value)
            else:
                result[str(key)] = value
        return result

    def _serialize_guest_disks(self, vm) -> list[dict[str, Any]]:
        result = []
        for disk in getattr(getattr(vm, "guest", None), "disk", []) or []:
            capacity = getattr(disk, "capacity", 0) or 0
            free_space = getattr(disk, "freeSpace", 0) or 0
            result.append(
                {
                    "path": getattr(disk, "diskPath", None),
                    "capacity_gb": round(capacity / (1024 ** 3), 2),
                    "free_space_gb": round(free_space / (1024 ** 3), 2),
                    "used_space_gb": round(max(capacity - free_space, 0) / (1024 ** 3), 2),
                }
            )
        return result

    def _serialize_vm_network_adapters(self, vm) -> list[dict[str, Any]]:
        guest_networks = {
            str(getattr(item, "macAddress", "")).lower(): item
            for item in getattr(getattr(vm, "guest", None), "net", []) or []
            if getattr(item, "macAddress", None)
        }

        devices = getattr(getattr(getattr(vm, "config", None), "hardware", None), "device", []) or []
        adapters = []
        for device in devices:
            if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                continue

            mac_address = getattr(device, "macAddress", None)
            guest_network = guest_networks.get(str(mac_address or "").lower())
            adapters.append(
                {
                    "label": getattr(getattr(device, "deviceInfo", None), "label", None),
                    "mac": mac_address,
                    "network_name": getattr(getattr(device, "backing", None), "deviceName", None)
                    or getattr(getattr(device, "deviceInfo", None), "summary", None),
                    "connected": bool(getattr(getattr(device, "connectable", None), "connected", False)),
                    "start_connected": bool(getattr(getattr(device, "connectable", None), "startConnected", False)),
                    "guest_network": getattr(guest_network, "network", None),
                    "ip_addresses": list(getattr(guest_network, "ipAddress", []) or []),
                }
            )
        return adapters

    def _serialize_vm_cdroms(self, vm) -> list[dict[str, Any]]:
        devices = getattr(getattr(getattr(vm, "config", None), "hardware", None), "device", []) or []
        result: list[dict[str, Any]] = []
        for device in devices:
            if not isinstance(device, vim.vm.device.VirtualCdrom):
                continue

            backing = getattr(device, "backing", None)
            backing_type = None
            iso_path = None
            summary = getattr(getattr(device, "deviceInfo", None), "summary", None)
            if isinstance(backing, vim.vm.device.VirtualCdrom.IsoBackingInfo):
                backing_type = "iso"
                iso_path = getattr(backing, "fileName", None)
            elif isinstance(backing, vim.vm.device.VirtualCdrom.AtapiBackingInfo):
                backing_type = "atapi"
            elif isinstance(backing, vim.vm.device.VirtualCdrom.RemotePassthroughBackingInfo):
                backing_type = "passthrough"
            elif backing is not None:
                backing_type = backing.__class__.__name__

            connectable = getattr(device, "connectable", None)
            result.append(
                {
                    "label": getattr(getattr(device, "deviceInfo", None), "label", None),
                    "summary": summary,
                    "backing_type": backing_type,
                    "iso_path": iso_path,
                    "connected": bool(getattr(connectable, "connected", False)),
                    "start_connected": bool(getattr(connectable, "startConnected", False)),
                }
            )
        return result

    def _serialize_vm_host_reference(self, vm) -> dict[str, Any]:
        return {
            "moid": getattr(vm, "_moId", None),
            "name": getattr(vm, "name", None),
            "power_state": str(getattr(getattr(vm, "runtime", None), "powerState", "unknown")),
        }

    def _build_vmrc_url(
        self,
        *,
        management_host: str,
        management_port: int,
        management_username: str,
        moid: str,
    ) -> str:
        encoded_user = quote(str(management_username or "").strip(), safe="")
        host = str(management_host or "").strip()
        port = int(management_port or 443)
        authority = f"{encoded_user}@{host}:{port}" if encoded_user else f"{host}:{port}"
        return f"vmrc://{authority}/?moid={quote(moid, safe='')}"

    def _guess_guest_platform(self, guest_full_name: str | None) -> str:
        normalized = str(guest_full_name or "").lower()
        if "windows" in normalized:
            return "windows"
        if any(token in normalized for token in ("linux", "ubuntu", "debian", "centos", "red hat", "suse", "oracle")):
            return "linux"
        return "unknown"

    def _aggregate_datastores(self, datastores: Iterable[Any]) -> dict[str, float | None]:
        total_capacity = 0
        total_free = 0
        has_data = False

        for datastore in datastores or []:
            summary = getattr(datastore, "summary", None)
            capacity = getattr(summary, "capacity", None)
            free_space = getattr(summary, "freeSpace", None)
            if capacity is None or free_space is None:
                continue
            has_data = True
            total_capacity += capacity
            total_free += free_space

        if not has_data:
            return {
                "storage_capacity_gb": None,
                "storage_free_gb": None,
                "storage_used_gb": None,
                "storage_usage_percent": None,
            }

        used = max(total_capacity - total_free, 0)
        return {
            "storage_capacity_gb": round(total_capacity / (1024 ** 3), 2),
            "storage_free_gb": round(total_free / (1024 ** 3), 2),
            "storage_used_gb": round(used / (1024 ** 3), 2),
            "storage_usage_percent": self._compute_percent(used, total_capacity),
        }

    def _compute_percent(self, numerator: int | float | None, denominator: int | float | None) -> float | None:
        if numerator in (None, "") or denominator in (None, "", 0):
            return None
        return round((float(numerator) / float(denominator)) * 100, 2)

    def _duplex_label(self, duplex: bool | None) -> str | None:
        if duplex is None:
            return None
        return "full" if duplex else "half"

    def _serialize_about(self, about) -> dict[str, Any]:
        return {
            "name": getattr(about, "name", None),
            "full_name": getattr(about, "fullName", None),
            "vendor": getattr(about, "vendor", None),
            "api_type": getattr(about, "apiType", None),
            "api_version": getattr(about, "apiVersion", None),
            "build": getattr(about, "build", None),
            "instance_uuid": getattr(about, "instanceUuid", None),
            "os_type": getattr(about, "osType", None),
        }

    def _serialize_named_object(self, item) -> dict[str, Any]:
        return {
            "moid": getattr(item, "_moId", None),
            "name": getattr(item, "name", None),
        }

    def _serialize_cluster(self, cluster) -> dict[str, Any]:
        hosts = getattr(cluster, "host", []) or []
        return {
            "moid": getattr(cluster, "_moId", None),
            "name": getattr(cluster, "name", None),
            "host_count": len(hosts),
            "overall_status": str(getattr(cluster, "overallStatus", "unknown")),
        }

    def _serialize_resource_pool(self, pool) -> dict[str, Any]:
        parent = getattr(pool, "parent", None)
        return {
            "moid": getattr(pool, "_moId", None),
            "name": getattr(pool, "name", None),
            "parent_name": getattr(parent, "name", None),
        }

    def _serialize_folder(self, folder) -> dict[str, Any]:
        parent = getattr(folder, "parent", None)
        return {
            "moid": getattr(folder, "_moId", None),
            "name": getattr(folder, "name", None),
            "parent_name": getattr(parent, "name", None),
        }

    def _serialize_datastore(self, datastore) -> dict[str, Any]:
        summary = getattr(datastore, "summary", None)
        capacity = getattr(summary, "capacity", 0) or 0
        free_space = getattr(summary, "freeSpace", 0) or 0
        return {
            "moid": getattr(datastore, "_moId", None),
            "name": getattr(datastore, "name", None),
            "type": getattr(summary, "type", None),
            "capacity_gb": round(capacity / (1024 ** 3), 2),
            "free_space_gb": round(free_space / (1024 ** 3), 2),
        }

    def _serialize_vm_summary(self, vm) -> dict[str, Any]:
        summary = getattr(vm, "summary", None)
        storage = getattr(summary, "storage", None)
        runtime = getattr(summary, "runtime", None)
        quick_stats = getattr(summary, "quickStats", None)
        guest = getattr(vm, "guest", None)
        committed = getattr(storage, "committed", 0) or 0
        uncommitted = getattr(storage, "uncommitted", 0) or 0
        provisioned = committed + uncommitted
        cpu_usage_mhz = getattr(quick_stats, "overallCpuUsage", None)
        cpu_capacity_mhz = getattr(runtime, "maxCpuUsage", None)
        host_memory_usage_mb = getattr(quick_stats, "hostMemoryUsage", None)
        guest_memory_usage_mb = getattr(quick_stats, "guestMemoryUsage", None)
        memory_capacity_mb = getattr(getattr(vm.config, "hardware", None), "memoryMB", None)
        guest_disks = getattr(guest, "disk", []) or []
        guest_disk_capacity = sum((getattr(item, "capacity", 0) or 0) for item in guest_disks)
        guest_disk_free = sum((getattr(item, "freeSpace", 0) or 0) for item in guest_disks)

        return {
            "moid": getattr(vm, "_moId", None),
            "name": getattr(vm, "name", None),
            "power_state": str(getattr(vm.runtime, "powerState", "unknown")),
            "guest_state": getattr(vm.guest, "guestState", None),
            "guest_full_name": getattr(vm.config, "guestFullName", None),
            "tools_status": getattr(vm.guest, "toolsRunningStatus", None),
            "cpu_count": getattr(getattr(vm.config, "hardware", None), "numCPU", None),
            "memory_mb": getattr(getattr(vm.config, "hardware", None), "memoryMB", None),
            "cpu_usage_mhz": cpu_usage_mhz,
            "cpu_usage_percent": self._compute_percent(cpu_usage_mhz, cpu_capacity_mhz),
            "host_memory_usage_mb": host_memory_usage_mb,
            "guest_memory_usage_mb": guest_memory_usage_mb,
            "memory_usage_percent": self._compute_percent(host_memory_usage_mb, memory_capacity_mb),
            "ip_address": getattr(vm.guest, "ipAddress", None),
            "host_name": getattr(getattr(vm.runtime, "host", None), "name", None),
            "resource_pool_name": getattr(getattr(vm, "resourcePool", None), "name", None),
            "folder_name": getattr(getattr(vm, "parent", None), "name", None),
            "datastores": [item.name for item in getattr(vm, "datastore", []) or []],
            "has_snapshots": bool(getattr(getattr(vm, "snapshot", None), "rootSnapshotList", [])),
            "storage_gb": round(provisioned / (1024 ** 3), 2),
            "storage_used_gb": round(committed / (1024 ** 3), 2),
            "guest_disk_capacity_gb": round(guest_disk_capacity / (1024 ** 3), 2) if guest_disk_capacity else None,
            "guest_disk_free_gb": round(guest_disk_free / (1024 ** 3), 2) if guest_disk_capacity else None,
            "uptime_seconds": getattr(quick_stats, "uptimeSeconds", None),
            "overall_status": str(getattr(vm, "overallStatus", "unknown")),
        }

    def _serialize_snapshot_tree(self, nodes: Iterable[Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def walk(items: Iterable[Any], path: list[str]):
            for node in items:
                current_path = [*path, node.name]
                result.append(
                    {
                        "moid": getattr(node.snapshot, "_moId", None),
                        "name": node.name,
                        "description": getattr(node, "description", "") or "",
                        "created_at": self._serialize_datetime(getattr(node, "createTime", None)),
                        "state": str(getattr(node, "state", "unknown")),
                        "path": " / ".join(current_path),
                    }
                )
                children = getattr(node, "childSnapshotList", []) or []
                walk(children, current_path)

        walk(nodes, [])
        return result

    def _serialize_host_summary(self, host) -> dict[str, Any]:
        runtime = getattr(host, "runtime", None)
        summary_runtime = getattr(getattr(host, "summary", None), "runtime", None)
        return {
            "moid": getattr(host, "_moId", None),
            "name": getattr(host, "name", None),
            "connection_state": str(getattr(runtime, "connectionState", "unknown")),
            "power_state": str(getattr(summary_runtime, "powerState", "unknown")) if summary_runtime else None,
            "in_maintenance_mode": bool(getattr(runtime, "inMaintenanceMode", False)),
            "overall_status": str(getattr(host, "overallStatus", "unknown")),
        }

    def _serialize_host_details(self, host) -> dict[str, Any]:
        summary = getattr(host, "summary", None)
        hardware = getattr(summary, "hardware", None)
        config = getattr(summary, "config", None)
        runtime = getattr(summary, "runtime", None)
        quick_stats = getattr(summary, "quickStats", None)
        parent = getattr(host, "parent", None)
        product = getattr(config, "product", None)
        cpu_mhz = getattr(hardware, "cpuMhz", 0) or 0
        cpu_cores = getattr(hardware, "numCpuCores", 0) or 0
        cpu_capacity_mhz = cpu_mhz * cpu_cores if cpu_mhz and cpu_cores else None
        cpu_usage_mhz = getattr(quick_stats, "overallCpuUsage", None)
        memory_size = getattr(hardware, "memorySize", 0) or 0
        memory_total_mb = round(memory_size / (1024 ** 2), 2) if memory_size else None
        memory_usage_mb = getattr(quick_stats, "overallMemoryUsage", None)
        datastore_totals = self._aggregate_datastores(getattr(host, "datastore", []) or [])

        return {
            "moid": getattr(host, "_moId", None),
            "name": getattr(host, "name", None),
            "connection_state": str(getattr(runtime, "connectionState", "unknown")),
            "power_state": str(getattr(runtime, "powerState", "unknown")),
            "in_maintenance_mode": bool(getattr(host.runtime, "inMaintenanceMode", False)),
            "overall_status": str(getattr(host, "overallStatus", "unknown")),
            "vendor": getattr(hardware, "vendor", None),
            "model": getattr(hardware, "model", None),
            "cpu_model": getattr(hardware, "cpuModel", None),
            "cpu_cores": getattr(hardware, "numCpuCores", None),
            "cpu_packages": getattr(hardware, "numCpuPkgs", None),
            "cpu_mhz": cpu_mhz or None,
            "cpu_capacity_mhz": cpu_capacity_mhz,
            "cpu_usage_mhz": cpu_usage_mhz,
            "cpu_usage_percent": self._compute_percent(cpu_usage_mhz, cpu_capacity_mhz),
            "memory_gb": round((getattr(hardware, "memorySize", 0) or 0) / (1024 ** 3), 2),
            "memory_total_mb": memory_total_mb,
            "memory_usage_mb": memory_usage_mb,
            "memory_usage_percent": self._compute_percent(memory_usage_mb, memory_total_mb),
            "product_name": getattr(product, "fullName", None),
            "cluster_name": getattr(parent, "name", None),
            "uptime_seconds": getattr(quick_stats, "uptime", None),
            "vm_count": len(getattr(host, "vm", []) or []),
            "datastore_count": len(getattr(host, "datastore", []) or []),
            **datastore_totals,
        }

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()

    def _is_vm_folder(self, folder) -> bool:
        child_types = getattr(folder, "childType", None)
        if not child_types:
            return True
        return any("VirtualMachine" in str(item) for item in child_types)
