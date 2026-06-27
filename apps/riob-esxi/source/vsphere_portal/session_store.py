from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from pyVim.connect import Disconnect


@dataclass
class ConnectionRecord:
    sid: str
    service_instance: Any
    host: str
    port: int
    username: str
    verify_ssl: bool
    endpoint_name: str
    api_type: str
    api_version: str
    product_line: str
    connected_at: datetime

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "verify_ssl": self.verify_ssl,
            "endpoint_name": self.endpoint_name,
            "api_type": self.api_type,
            "api_version": self.api_version,
            "product_line": self.product_line,
            "connected_at": self.connected_at.astimezone(timezone.utc).isoformat(),
        }


class ConnectionStore:
    def __init__(self) -> None:
        self._items: dict[str, ConnectionRecord] = {}
        self._lock = RLock()

    def create(
        self,
        service_instance: Any,
        *,
        host: str,
        port: int,
        username: str,
        verify_ssl: bool,
        endpoint_name: str,
        api_type: str,
        api_version: str,
        product_line: str,
    ) -> ConnectionRecord:
        record = ConnectionRecord(
            sid=uuid.uuid4().hex,
            service_instance=service_instance,
            host=host,
            port=port,
            username=username,
            verify_ssl=verify_ssl,
            endpoint_name=endpoint_name,
            api_type=api_type,
            api_version=api_version,
            product_line=product_line,
            connected_at=datetime.now(tz=timezone.utc),
        )
        with self._lock:
            self._items[record.sid] = record
        return record

    def get(self, sid: str | None) -> ConnectionRecord | None:
        if not sid:
            return None
        with self._lock:
            return self._items.get(sid)

    def remove(self, sid: str | None) -> ConnectionRecord | None:
        if not sid:
            return None
        with self._lock:
            record = self._items.pop(sid, None)
        if record is not None:
            try:
                Disconnect(record.service_instance)
            except Exception:
                pass
        return record


connection_store = ConnectionStore()
