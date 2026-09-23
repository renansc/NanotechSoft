import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import time
import uuid


CONKY_STATUSES = ("today", "todo", "waiting")
CONKY_TO_CHAMADO = {
    "today": "EM_ATENDIMENTO",
    "todo": "ABERTO",
    "waiting": "AGUARDANDO",
}
CHAMADO_TO_CONKY = {
    "ABERTO": "todo",
    "TRIAGEM": "todo",
    "EM_ATENDIMENTO": "today",
    "AGUARDANDO": "waiting",
}


def normalize_conky_status(value):
    aliases = {
        "2": "today",
        "hoje": "today",
        "today": "today",
        "para-hoje": "today",
        "parahoje": "today",
        "para_hoje": "today",
        "doing": "today",
        "fazendo": "today",
        "andamento": "today",
        "ematendimento": "today",
        "em_atendimento": "today",
        "1": "todo",
        "afazer": "todo",
        "todo": "todo",
        "to-do": "todo",
        "fazer": "todo",
        "aberto": "todo",
        "3": "waiting",
        "aguardando": "waiting",
        "waiting": "waiting",
        "wait": "waiting",
        "espera": "waiting",
        "pendente": "waiting",
    }
    key = "".join(str(value or "").lower().split())
    return aliases.get(key)


def new_sync_key():
    return uuid.uuid4().hex


def normalize_task(item, used_ids=None, now=None):
    if not isinstance(item, dict):
        return None
    status = normalize_conky_status(item.get("status"))
    text = str(item.get("text") or "").strip()
    if not status or not text:
        return None

    used_ids = used_ids if used_ids is not None else set()
    task_id = str(item.get("id") or "").strip()
    if not task_id.isdigit() or int(task_id) <= 0 or task_id in used_ids:
        task_id = ""
    if task_id:
        used_ids.add(task_id)

    current_time = int(now if now is not None else time.time())
    task = {
        "id": task_id,
        "status": status,
        "text": text,
        "created": positive_int(item.get("created"), current_time),
        "updated": positive_int(item.get("updated"), positive_int(item.get("created"), current_time)),
        "syncKey": str(item.get("syncKey") or "").strip()[:64] or new_sync_key(),
    }
    ticket_id = positive_int(item.get("ticketId"), 0)
    if ticket_id:
        task["ticketId"] = ticket_id
    for key in ("protocol", "syncedStatus", "syncedText", "ticketUpdatedAt"):
        value = str(item.get(key) or "").strip()
        if value:
            task[key] = value
    synced_at = positive_int(item.get("syncedAt"), 0)
    if synced_at:
        task["syncedAt"] = synced_at
    return task


def normalize_tasks(data, now=None):
    if not isinstance(data, list):
        return []
    tasks = []
    used_ids = set()
    used_keys = set()
    for item in data:
        task = normalize_task(item, used_ids=used_ids, now=now)
        if not task:
            continue
        if task["syncKey"] in used_keys:
            task["syncKey"] = new_sync_key()
        used_keys.add(task["syncKey"])
        tasks.append(task)
    next_id = max((int(value) for value in used_ids), default=0) + 1
    for task in tasks:
        if task["id"]:
            continue
        while str(next_id) in used_ids:
            next_id += 1
        task["id"] = str(next_id)
        used_ids.add(task["id"])
        next_id += 1
    return tasks


def positive_int(value, default=0):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def next_task_id(tasks):
    ids = [int(task["id"]) for task in tasks if str(task.get("id") or "").isdigit()]
    return str(max(ids, default=0) + 1)


@contextlib.contextmanager
def task_file_lock(path):
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        os.chmod(lock_path, 0o666)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_task_file(path):
    path = Path(path)
    if not path.exists():
        return []
    with task_file_lock(path):
        return load_task_file_unlocked(path)


def load_task_file_unlocked(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return normalize_tasks(data)


def save_task_file(path, tasks):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with task_file_lock(path):
        save_task_file_unlocked(path, tasks)


def save_task_file_unlocked(path, tasks):
    path = Path(path)
    normalized = normalize_tasks(tasks)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o666)
    os.replace(temporary, path)


def timestamp_text(value):
    if not value:
        return ""
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def timestamp_epoch(value, default=None):
    if not value:
        return int(default if default is not None else time.time())
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return int(value.timestamp())
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp())
    except (TypeError, ValueError):
        return int(default if default is not None else time.time())
