#!/usr/bin/env python3
import json
import os
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOCAL = Path(os.environ.get("KANBAN_LOCAL", str(BASE_DIR / "kanban-tasks.json"))).expanduser()
REMOTE = Path(os.environ.get("KANBAN_REMOTE", str(BASE_DIR / "kanban-tasks.remote.json"))).expanduser()

def valid_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(data, list)
    except Exception:
        return False

def copy_atomic(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)

def main():
    if not LOCAL.exists() and not REMOTE.exists():
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        LOCAL.write_text("[]\n", encoding="utf-8")
        print("criado json local vazio")
        return

    if LOCAL.exists() and not valid_json(LOCAL):
        print(f"ERRO: JSON local inválido: {LOCAL}", file=sys.stderr)
        sys.exit(1)

    if REMOTE.exists() and not valid_json(REMOTE):
        print(f"ERRO: JSON remoto inválido: {REMOTE}", file=sys.stderr)
        sys.exit(1)

    if LOCAL.exists() and not REMOTE.exists():
        copy_atomic(LOCAL, REMOTE)
        print("enviado local -> remoto")
        return

    if REMOTE.exists() and not LOCAL.exists():
        copy_atomic(REMOTE, LOCAL)
        print("baixado remoto -> local")
        return

    local_mtime = LOCAL.stat().st_mtime
    remote_mtime = REMOTE.stat().st_mtime

    # margem para evitar troca por diferença mínima de relógio
    if local_mtime > remote_mtime + 2:
        copy_atomic(LOCAL, REMOTE)
        print("sincronizado local -> remoto")
    elif remote_mtime > local_mtime + 2:
        copy_atomic(REMOTE, LOCAL)
        print("sincronizado remoto -> local")
    else:
        print("sem alterações")

if __name__ == "__main__":
    main()
