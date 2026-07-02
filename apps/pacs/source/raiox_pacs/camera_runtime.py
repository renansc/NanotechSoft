from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings
from .utils import slugify


class CameraRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stream_root = settings.runtime_root / "cameras"
        self.stream_root.mkdir(parents=True, exist_ok=True)
        self._processes: dict[int, subprocess.Popen[bytes]] = {}
        self._errors: dict[int, str] = {}

    def _camera_folder(self, camera_id: int, name: str) -> Path:
        folder = self.stream_root / f"{camera_id}-{slugify(name, 'camera')}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def stop(self, camera_id: int) -> None:
        process = self._processes.pop(camera_id, None)
        if process and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass

    def _rtsp_stream_url(self, camera_id: int, name: str) -> str:
        folder = self._camera_folder(camera_id, name)
        return f"/camera-streams/{folder.name}/live.m3u8"

    def ensure_camera(self, camera: dict[str, Any]) -> None:
        camera_id = int(camera["id"])
        if not camera.get("enabled"):
            self.stop(camera_id)
            self._errors.pop(camera_id, None)
            return

        mode = str(camera.get("mode") or "rtsp").strip().lower()
        if mode != "rtsp":
            self.stop(camera_id)
            self._errors.pop(camera_id, None)
            return

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.stop(camera_id)
            self._errors[camera_id] = "ffmpeg nao encontrado no ambiente."
            return

        current = self._processes.get(camera_id)
        if current and current.poll() is None:
            return

        folder = self._camera_folder(camera_id, str(camera.get("name") or f"camera-{camera_id}"))
        playlist = folder / "live.m3u8"
        segment_pattern = folder / "seg_%03d.ts"
        transport = str(camera.get("transport") or "tcp").strip().lower()
        if transport not in {"tcp", "udp"}:
            transport = "tcp"

        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            transport,
            "-i",
            str(camera.get("source_url") or ""),
            "-c:v",
            "copy",
            "-an",
            "-f",
            "hls",
            "-hls_time",
            "2",
            "-hls_list_size",
            "6",
            "-hls_flags",
            "delete_segments+append_list",
            "-hls_segment_filename",
            str(segment_pattern),
            str(playlist),
        ]
        try:
            self._processes[camera_id] = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._errors.pop(camera_id, None)
        except Exception as exc:
            self._errors[camera_id] = str(exc)

    def sync(self, cameras: list[dict[str, Any]]) -> None:
        active_ids = {int(camera["id"]) for camera in cameras}
        for camera_id in list(self._processes):
            if camera_id not in active_ids:
                self.stop(camera_id)
                self._errors.pop(camera_id, None)
        for camera in cameras:
            self.ensure_camera(camera)

    def remove_camera(self, camera_id: int) -> None:
        self.stop(camera_id)
        self._errors.pop(camera_id, None)

    def status_map(self, cameras: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        self.sync(cameras)
        payload: dict[int, dict[str, Any]] = {}
        for camera in cameras:
            camera_id = int(camera["id"])
            mode = str(camera.get("mode") or "rtsp").strip().lower()
            enabled = bool(camera.get("enabled"))
            process = self._processes.get(camera_id)
            running = bool(process and process.poll() is None)
            error = self._errors.get(camera_id)
            if not enabled:
                status = "disabled"
            elif error:
                status = "error"
            elif mode == "rtsp":
                status = "streaming" if running else "starting"
            else:
                status = "ready"
            stream_url = self._rtsp_stream_url(camera_id, str(camera.get("name") or f"camera-{camera_id}"))
            if mode == "hls":
                stream_url = str(camera.get("source_url") or "")
            payload[camera_id] = {
                "status": status,
                "stream_url": stream_url,
                "error": error,
            }
        return payload
