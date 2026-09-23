import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from apps.chamados.conky_sync import (
    CONKY_TO_CHAMADO,
    load_task_file,
    normalize_tasks,
    save_task_file,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
KANBAN_SCRIPT = PROJECT_DIR / "apps" / "riob" / "source" / "kanban.py"


class ChamadosConkyTests(unittest.TestCase):
    def test_statuses_map_to_active_ticket_flow(self):
        self.assertEqual("ABERTO", CONKY_TO_CHAMADO["todo"])
        self.assertEqual("EM_ATENDIMENTO", CONKY_TO_CHAMADO["today"])
        self.assertEqual("AGUARDANDO", CONKY_TO_CHAMADO["waiting"])

    def test_normalization_adds_stable_keys_and_unique_ids(self):
        tasks = normalize_tasks([
            {"id": "1", "status": "todo", "text": "Primeira", "created": 10},
            {"id": "1", "status": "today", "text": "Segunda", "created": 11},
        ], now=20)

        self.assertEqual(["1", "2"], [task["id"] for task in tasks])
        self.assertTrue(all(len(task["syncKey"]) == 32 for task in tasks))
        self.assertNotEqual(tasks[0]["syncKey"], tasks[1]["syncKey"])

    def test_kanban_commands_keep_ticket_metadata_for_portal_sync(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_file = Path(temp_dir) / "kanban-tasks.json"
            env = {
                **os.environ,
                "KANBAN_TASKS_FILE": str(task_file),
                "KANBAN_SYNC_SCRIPT": str(Path(temp_dir) / "not-installed.py"),
            }
            subprocess.run(
                ["python3", str(KANBAN_SCRIPT), "add", "Validar impressora"],
                check=True,
                env=env,
            )
            tasks = load_task_file(task_file)
            self.assertEqual("todo", tasks[0]["status"])
            tasks[0].update({
                "ticketId": 42,
                "protocol": "CH-2026-000042",
                "syncedStatus": "todo",
                "syncedText": "Validar impressora",
                "ticketUpdatedAt": "2026-09-03T12:00:00",
                "syncedAt": 100,
            })
            original_key = tasks[0]["syncKey"]
            save_task_file(task_file, tasks)

            subprocess.run(
                ["python3", str(KANBAN_SCRIPT), "move", "1", "today"],
                check=True,
                env=env,
            )
            persisted = json.loads(task_file.read_text(encoding="utf-8"))[0]

            self.assertEqual("today", persisted["status"])
            self.assertEqual(42, persisted["ticketId"])
            self.assertEqual("CH-2026-000042", persisted["protocol"])
            self.assertEqual(original_key, persisted["syncKey"])
            self.assertGreater(persisted["updated"], 0)

    def test_concurrent_kanban_writes_do_not_lose_tasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_file = Path(temp_dir) / "kanban-tasks.json"
            env = {
                **os.environ,
                "KANBAN_TASKS_FILE": str(task_file),
                "KANBAN_LOCK_FILE": str(task_file) + ".lock",
                "KANBAN_SYNC_SCRIPT": str(Path(temp_dir) / "not-installed.py"),
            }

            def add_task(index):
                subprocess.run(
                    ["python3", str(KANBAN_SCRIPT), "add", "todo", f"Tarefa {index}"],
                    check=True,
                    env=env,
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(add_task, range(24)))

            persisted = json.loads(task_file.read_text(encoding="utf-8"))
            self.assertEqual(24, len(persisted))
            self.assertEqual(24, len({task["id"] for task in persisted}))
            self.assertEqual(24, len({task["text"] for task in persisted}))
            self.assertTrue(all(task["status"] == "todo" for task in persisted))


if __name__ == "__main__":
    unittest.main()
