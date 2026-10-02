"""Back up and remove obsolete full signal snapshots from the local database."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


ARCHIVE = ("signal_evaluation", "signal_evaluation.csv")


def retained_fingerprints(connection: sqlite3.Connection) -> dict:
    result = {}
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    for (name,) in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        query = f"SELECT * FROM {quoted}"
        parameters = ()
        if name == "generic_frames":
            query += " WHERE table_name IS NOT ? OR source IS NOT ?"
            parameters = ARCHIVE
        query += " ORDER BY rowid"
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(query, parameters):
            digest.update(repr(row).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        result[name] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def checked_backup(db_path: Path, archive_dir: Path) -> tuple[Path, str]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    raw = archive_dir / f"app_before_signal_cleanup_{stamp}.db"
    compressed = raw.with_suffix(".db.gz")
    print("[BACKUP] Creating consistent SQLite backup", flush=True)
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(raw)) as target:
            source.backup(target)
            integrity = target.execute("PRAGMA quick_check").fetchall()
            if integrity != [("ok",)]:
                raise RuntimeError(f"Backup integrity check failed: {integrity}")
    print("[BACKUP] Compressing verified database", flush=True)
    original_digest = hashlib.sha256()
    with raw.open("rb") as source, gzip.open(compressed, "wb", compresslevel=1) as target:
        while chunk := source.read(8 * 1024 * 1024):
            original_digest.update(chunk)
            target.write(chunk)
    print("[BACKUP] Verifying compressed backup", flush=True)
    with gzip.open(compressed, "rb") as source:
        restored_digest = hashlib.file_digest(source, "sha256").hexdigest()
    if restored_digest != original_digest.hexdigest():
        raise RuntimeError("Compressed backup checksum mismatch; original database unchanged")
    raw.unlink()
    return compressed, restored_digest


def cleanup(db_path: Path, detail_path: Path, archive_dir: Path) -> dict:
    db_path = db_path.resolve(strict=True)
    detail_path = detail_path.resolve(strict=True)
    if detail_path.stat().st_size == 0:
        raise RuntimeError("Latest signal detail CSV is empty; cleanup refused")
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = archive_dir.resolve()
    before_bytes = db_path.stat().st_size
    if shutil.disk_usage(archive_dir).free < before_bytes * 3:
        raise RuntimeError("Insufficient workspace for verified backup and SQLite maintenance")
    with detail_path.open("rb") as source:
        detail_digest = hashlib.file_digest(source, "sha256").hexdigest()

    with closing(sqlite3.connect(db_path, timeout=10)) as connection:
        # Block other writers throughout backup and deletion; readers can keep working.
        connection.execute("BEGIN IMMEDIATE")
        try:
            exists = connection.execute(
                "SELECT 1 FROM generic_frames WHERE table_name=? AND source=? LIMIT 1", ARCHIVE
            ).fetchone()
            if not exists:
                connection.rollback()
                return {"deleted_rows": 0, "message": "No obsolete signal snapshots found"}
            print("[CHECK] Fingerprinting all retained database records", flush=True)
            retained = retained_fingerprints(connection)
            backup, backup_digest = checked_backup(db_path, archive_dir)
            print("[CLEANUP] Removing only obsolete signal-detail snapshots", flush=True)
            deleted = connection.execute(
                "DELETE FROM generic_frames WHERE table_name=? AND source=?", ARCHIVE
            ).rowcount
            if retained_fingerprints(connection) != retained:
                raise RuntimeError("Retained records changed; rolling back cleanup")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

        print("[COMPACT] Reclaiming unused database pages", flush=True)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError(f"Post-cleanup integrity check failed; backup: {backup}")
        if retained_fingerprints(connection) != retained:
            raise RuntimeError(f"Post-cleanup record mismatch; backup: {backup}")

    with detail_path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != detail_digest:
            raise RuntimeError("Signal detail CSV changed during cleanup")
    report = {
        "completed_at": datetime.now().astimezone().isoformat(),
        "database": str(db_path), "deleted_rows": deleted,
        "before_bytes": before_bytes, "after_bytes": db_path.stat().st_size,
        "backup": str(backup), "backup_bytes": backup.stat().st_size,
        "backup_uncompressed_sha256": backup_digest,
        "detail_csv": str(detail_path), "detail_csv_sha256": detail_digest,
        "retained_tables": retained, "integrity_check": "ok",
    }
    report_path = backup.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] Cleanup report: {report_path}", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/app.db"))
    parser.add_argument("--detail", type=Path, default=Path("outputs/signal_evaluation.csv"))
    parser.add_argument("--backup-dir", type=Path, default=Path("data/backups"))
    parser.add_argument("--apply", action="store_true", help="back up, clean, and compact the database")
    args = parser.parse_args()
    if not args.apply:
        parser.error("Use --apply after stopping other program runs; this removes archived detail snapshots")
    print(json.dumps(cleanup(args.db, args.detail, args.backup_dir), indent=2), flush=True)


if __name__ == "__main__":
    main()
