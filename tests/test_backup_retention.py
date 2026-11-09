from datetime import date
import sqlite3
from app.database.backup import backup_database, clean_reports


def test_database_backup_and_retention(tmp_path):
    database = tmp_path / "stock_agent.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE facts(value TEXT)")
        connection.execute("INSERT INTO facts VALUES('preserved')")
    backup = tmp_path / "backup"
    old = backup / "stock_agent_20250101.db"
    backup.mkdir()
    old.write_bytes(b"old")
    target = backup_database(database, backup, date(2026, 9, 8), 30)
    assert target.exists() and not old.exists()
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM facts").fetchone()[0] == "preserved"


def test_report_archive(tmp_path):
    folder = tmp_path / "reports/603283"
    folder.mkdir(parents=True)
    (folder / "2025-01-01.html").write_text("report")
    assert clean_reports(tmp_path / "reports", 365, True, date(2026, 9, 8)) == 1
    assert not (folder / "2025-01-01.html").exists()
    assert list((tmp_path / "reports").glob("*.zip"))
