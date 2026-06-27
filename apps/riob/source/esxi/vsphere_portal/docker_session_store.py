from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any


@dataclass
class DockerConnectionRecord:
    sid: str
    host: str
    port: int
    username: str
    password: str
    legacy_compat: bool
    engine_name: str | None
    server_version: str | None
    operating_system: str | None
    connected_at: datetime

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "legacy_compat": self.legacy_compat,
            "engine_name": self.engine_name,
            "server_version": self.server_version,
            "operating_system": self.operating_system,
            "connected_at": self.connected_at.astimezone(timezone.utc).isoformat(),
        }


class DockerConnectionStore:
    def __init__(self) -> None:
        self._items: dict[str, DockerConnectionRecord] = {}
        self._lock = RLock()

    def create(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        legacy_compat: bool,
        engine_name: str | None,
        server_version: str | None,
        operating_system: str | None,
    ) -> DockerConnectionRecord:
        record = DockerConnectionRecord(
            sid=uuid.uuid4().hex,
            host=host,
            port=port,
            username=username,
            password=password,
            legacy_compat=legacy_compat,
            engine_name=engine_name,
            server_version=server_version,
            operating_system=operating_system,
            connected_at=datetime.now(tz=timezone.utc),
        )
        with self._lock:
            self._items[record.sid] = record
        return record

    def get(self, sid: str | None) -> DockerConnectionRecord | None:
        if not sid:
            return None
        with self._lock:
            return self._items.get(sid)

    def remove(self, sid: str | None) -> DockerConnectionRecord | None:
        if not sid:
            return None
        with self._lock:
            return self._items.pop(sid, None)


docker_connection_store = DockerConnectionStore()
