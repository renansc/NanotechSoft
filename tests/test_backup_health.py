"""Current backup health must not inherit an old successful execution."""
import datetime as dt
import unittest

import app as portal


class BackupHealthTests(unittest.TestCase):
    def row(self, **changes):
        return dict(id=1, ativo=1, horarios='["08:00", "16:00"]', ultimo_contato_em=dt.datetime.now(dt.UTC).replace(tzinfo=None),
                    ultima_status="SUCCESS", ultima_execucao_id="previous", **changes)

    def test_old_success_does_not_hide_missing_agent(self):
        row = self.row()
        row["ultimo_contato_em"] -= dt.timedelta(days=6)
        result = portal.technology_public_backup(row)
        self.assertEqual("OFFLINE", result["health"])
        self.assertIn("Erro", result["healthMessage"])
        self.assertEqual("SUCCESS", result["lastRun"]["status"])

    def test_contact_timeout_uses_utc_instead_of_server_local_time(self):
        row = self.row()
        row["ultimo_contato_em"] -= dt.timedelta(minutes=11)
        for timestamp in (row["ultimo_contato_em"], row["ultimo_contato_em"].replace(tzinfo=dt.UTC)):
            row["ultimo_contato_em"] = timestamp
            self.assertEqual("OFFLINE", portal.technology_public_backup(row)["health"])

    def test_connected_failed_waiting_and_disabled_are_distinct(self):
        row = self.row()
        self.assertEqual("ONLINE", portal.technology_public_backup(row)["health"])
        row["ultima_status"] = "FAILED"
        self.assertEqual("WARNING", portal.technology_public_backup(row)["health"])
        row["ultimo_contato_em"] = None
        self.assertEqual("WAITING", portal.technology_public_backup(row)["health"])
        row["ativo"] = 0
        self.assertEqual("DISABLED", portal.technology_public_backup(row)["health"])
