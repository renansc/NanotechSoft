#!/usr/bin/env python3
import json
import os
import sys
import time
import subprocess
import fcntl
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Arquivo local usado pelo Conky
# Pode alterar por variavel de ambiente, se precisar:
# export KANBAN_TASKS_FILE="/srv/riob/kanban-tasks.json"
DEFAULT_TASKS_FILE = (
    "/srv/conky/kanban-tasks.json"
    if Path("/srv/conky").is_dir()
    else "/srv/kanban/kanban-tasks.json"
)
TASKS_FILE = Path(os.environ.get("KANBAN_TASKS_FILE", DEFAULT_TASKS_FILE)).expanduser()
LOCK_FILE = Path(os.environ.get("KANBAN_LOCK_FILE", str(TASKS_FILE) + ".lock")).expanduser()

# Script de sincronizacao. Sera chamado automaticamente apos salvar alteracoes.
SYNC_SCRIPT = Path(os.environ.get("KANBAN_SYNC_SCRIPT", str(BASE_DIR / "kanban_sync.py"))).expanduser()

STATUSES = ("todo", "today", "waiting")
LABELS = {
    "today": "EM ATENDIMENTO",
    "todo": "ABERTO",
    "waiting": "AGUARDANDO",
}
EMPTY = {
    "today": "nenhum em atendimento",
    "todo": "nenhum chamado aberto",
    "waiting": "nenhum aguardando",
}
FIRST_CARD_OFFSET = 20
NEXT_CARD_OFFSET = 20
ITEM_SLOTS = 6
MAX_ITEMS = 6
MAX_TEXT = 30


class FileLock:
    def __enter__(self):
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.handle = LOCK_FILE.open("w", encoding="utf-8")
        os.chmod(LOCK_FILE, 0o666)
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def run_sync_background():
    """Executa sync em segundo plano sem travar o Conky."""
    if not SYNC_SCRIPT.exists():
        return

    try:
        subprocess.Popen(
            ["python3", str(SYNC_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def load_tasks_unlocked():
    if not TASKS_FILE.exists():
        return []

    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    tasks = []
    changed = False
    ids = set()

    for item in data:
        if not isinstance(item, dict):
            changed = True
            continue

        original_status = str(item.get("status", "")).strip()
        status = normalize_status(original_status)
        text = str(item.get("text", "")).strip()
        task_id = str(item.get("id", "")).strip()

        if not status or not text:
            changed = True
            continue

        if (
            not task_id.isdigit()
            or int(task_id) <= 0
            or task_id in ids
        ):
            changed = True
            task_id = ""

        if original_status != status:
            changed = True

        if task_id:
            ids.add(task_id)
        now = int(time.time())
        task = dict(item)
        task.update({
            "id": task_id,
            "status": status,
            "text": text,
            "created": int(item.get("created", 0) or now),
            "updated": int(item.get("updated", 0) or item.get("created", 0) or now),
            "syncKey": str(item.get("syncKey") or uuid.uuid4().hex),
        })
        if task != item:
            changed = True
        tasks.append(task)

    if changed:
        for index, task in enumerate(sorted(tasks, key=lambda task: task["created"]), 1):
            task["id"] = str(index)
        save_tasks_unlocked(tasks)

    return tasks


def load_tasks():
    with FileLock():
        return load_tasks_unlocked()


def save_tasks_unlocked(tasks):
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TASKS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o666)
    os.replace(tmp, TASKS_FILE)


def save_tasks(tasks, sync=True):
    with FileLock():
        save_tasks_unlocked(tasks)

    if sync:
        run_sync_background()


def next_task_id(tasks):
    ids = [int(task["id"]) for task in tasks if str(task["id"]).isdigit()]
    return str(max(ids, default=0) + 1)


def normalize_status(value):
    aliases = {
        "0": "delete",
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
        "done": "waiting",
        "feito": "waiting",
        "concluido": "waiting",
    }
    key = "".join(str(value).lower().split())
    return aliases.get(key)


def add_task(args):
    if not args:
        die("uso: kanban.py add [aberto|em_atendimento|aguardando] texto")

    status = normalize_status(args[0]) if args else None
    if status == "delete":
        die("status 0 e usado apenas para remover tarefas")

    if status:
        text = " ".join(args[1:]).strip()
    else:
        status = "todo"
        text = " ".join(args).strip()

    if not text:
        die("informe o texto da tarefa")

    with FileLock():
        tasks = load_tasks_unlocked()
        tasks.append(
            {
                "id": next_task_id(tasks),
                "status": status,
                "text": text,
                "created": int(time.time()),
                "updated": int(time.time()),
                "syncKey": uuid.uuid4().hex,
            }
        )
        save_tasks_unlocked(tasks)
    run_sync_background()


def move_task(args):
    if len(args) < 2:
        die("uso: kanban.py move id 0|aberto|em_atendimento|aguardando")

    wanted_id = args[0]
    status = normalize_status(args[1])
    if not status:
        die("status invalido: use 0, 1, 2 ou 3")

    if status == "delete":
        delete_task([wanted_id])
        return

    with FileLock():
        tasks = load_tasks_unlocked()
        for task in tasks:
            if task["id"] == wanted_id:
                task["status"] = status
                task["updated"] = int(time.time())
                save_tasks_unlocked(tasks)
                break
        else:
            die(f"tarefa nao encontrada: {wanted_id}")

    run_sync_background()


def edit_task(args):
    if len(args) < 2:
        die("uso: kanban.py edit id texto")

    wanted_id = args[0]
    text = " ".join(args[1:]).strip()
    if not text:
        die("informe o novo texto da tarefa")

    with FileLock():
        tasks = load_tasks_unlocked()
        for task in tasks:
            if task["id"] == wanted_id:
                task["text"] = text
                task["updated"] = int(time.time())
                save_tasks_unlocked(tasks)
                break
        else:
            die(f"tarefa nao encontrada: {wanted_id}")

    run_sync_background()


def get_task(args):
    if not args:
        die("uso: kanban.py get id")

    wanted_id = args[0]
    for task in load_tasks():
        if task["id"] == wanted_id:
            print(task["text"])
            return

    die(f"tarefa nao encontrada: {wanted_id}")


def delete_task(args):
    if not args:
        die("uso: kanban.py delete id")

    wanted_id = args[0]
    with FileLock():
        tasks = load_tasks_unlocked()
        kept = [task for task in tasks if task["id"] != wanted_id]
        if len(kept) == len(tasks):
            die(f"tarefa nao encontrada: {wanted_id}")
        save_tasks_unlocked(kept)
    run_sync_background()


def list_tasks():
    for task in load_tasks():
        print(f'{task["id"]:>3}  {task["status"]:<7}  {task["text"]}')


def conky_escape(text):
    clean = " ".join(text.split())
    clean = clean.replace("$", "S")
    clean = clean.replace("{", "(").replace("}", ")")
    clean = clean.replace("\\", "/")
    return clean


def truncate(text, width):
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "."


def section_lines(tasks, status, first=False):
    items = [task for task in tasks if task["status"] == status]
    voffset = FIRST_CARD_OFFSET if first else NEXT_CARD_OFFSET

    print(
        f"${{voffset {voffset}}}${{goto 24}}${{color3}}"
        f"${{font JetBrains Mono:bold:size=10}}{LABELS[status]}${{font JetBrains Mono:size=8}}"
        f"${{goto 268}}${{color1}}{len(items)}${{color2}}"
    )

    rows = []
    if not items:
        rows.append(("empty", EMPTY[status], ""))
    else:
        visible = items[:MAX_ITEMS]
        if len(items) > MAX_ITEMS:
            visible = items[: MAX_ITEMS - 1]

        for task in visible:
            text = truncate(conky_escape(task["text"]), MAX_TEXT)
            rows.append(("task", f'{task["id"]} - {text}', ""))

        hidden = len(items) - len(visible)
        if hidden > 0:
            rows.append(("empty", f"+{hidden} tarefa(s)", ""))

    while len(rows) < ITEM_SLOTS:
        rows.append(("blank", "", ""))

    for kind, text, task_ref in rows[:ITEM_SLOTS]:
        color = "color1" if kind in ("empty", "blank") else "color2"
        print(
            f"${{voffset 8}}${{goto 24}}${{{color}}}{text}"
            f"${{goto 268}}${{color1}}{task_ref}${{color2}}"
        )


def render():
    tasks = load_tasks()
    for index, status in enumerate(STATUSES):
        section_lines(tasks, status, first=index == 0)
    print("${font}")


def sync_now():
    if not SYNC_SCRIPT.exists():
        die(f"script de sync nao encontrado: {SYNC_SCRIPT}")
    result = subprocess.run(["python3", str(SYNC_SCRIPT)], text=True)
    raise SystemExit(result.returncode)


def die(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    args = sys.argv[2:]

    if command == "render":
        render()
    elif command == "add":
        add_task(args)
    elif command == "move":
        move_task(args)
    elif command == "edit":
        edit_task(args)
    elif command == "get":
        get_task(args)
    elif command == "done":
        move_task([args[0], "3"] if args else [])
    elif command in ("delete", "del", "rm"):
        delete_task(args)
    elif command == "list":
        list_tasks()
    elif command == "sync":
        sync_now()
    else:
        print("uso:")
        print("  kanban.py render")
        print("  kanban.py add [aberto|em_atendimento|aguardando] texto")
        print("  kanban.py move id 0|aberto|em_atendimento|aguardando")
        print("  kanban.py edit id texto")
        print("  kanban.py get id")
        print("  kanban.py done id")
        print("  kanban.py delete id")
        print("  kanban.py list")
        print("  kanban.py sync")


if __name__ == "__main__":
    main()
