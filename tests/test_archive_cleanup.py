from contextlib import closing
import gzip
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.cleanup_signal_archive import cleanup


class ArchiveCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "app.db"
        self.csv = self.root / "signal_evaluation.csv"
        self.csv.write_text("symbol,date\nAAA,2026-10-01\n", encoding="utf-8")
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript("""
                CREATE TABLE generic_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, table_name TEXT, source TEXT, payload_json TEXT
                );
                CREATE TABLE accounts (id INTEGER PRIMARY KEY, balance REAL);
                INSERT INTO accounts VALUES (1, 10000);
                INSERT INTO generic_frames (table_name, source, payload_json) VALUES
                    ('signal_evaluation', 'signal_evaluation.csv', 'old snapshot'),
                    ('signal_evaluation', 'signal_evaluation.csv', 'new snapshot'),
                    ('signal_evaluation_summary', 'signal_evaluation_summary.csv', 'keep summary'),
                    ('signal_evaluation', 'different.csv', 'keep different source'),
                    (NULL, 'signal_evaluation.csv', 'keep null name'),
                    ('signal_evaluation', NULL, 'keep null source');
            """)

    def test_cleanup_preserves_other_records_and_has_restorable_backup(self):
        result = cleanup(self.db, self.csv, self.root / "backups")
        self.assertEqual(result["deleted_rows"], 2)
        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(self.csv.read_text(encoding="utf-8"), "symbol,date\nAAA,2026-10-01\n")
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM generic_frames").fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT balance FROM accounts").fetchone()[0], 10000)
        restored = self.root / "restored.db"
        with gzip.open(result["backup"], "rb") as source:
            restored.write_bytes(source.read())
        with closing(sqlite3.connect(restored)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM generic_frames").fetchone()[0], 6)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(cleanup(self.db, self.csv, self.root / "backups")["deleted_rows"], 0)

    def test_backup_failure_leaves_database_untouched(self):
        with patch("scripts.cleanup_signal_archive.checked_backup", side_effect=OSError("backup failed")):
            with self.assertRaisesRegex(OSError, "backup failed"):
                cleanup(self.db, self.csv, self.root / "backups")
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM generic_frames").fetchone()[0], 6)

    def test_missing_current_detail_prevents_cleanup(self):
        with self.assertRaises(FileNotFoundError):
            cleanup(self.db, self.root / "missing.csv", self.root / "backups")


if __name__ == "__main__":
    unittest.main()
