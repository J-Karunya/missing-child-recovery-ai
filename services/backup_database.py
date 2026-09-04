"""Create verified timestamped SQLite backups without touching the source database."""
from __future__ import annotations
import shutil
from datetime import datetime, timezone
from pathlib import Path
try:
    from .config import DATABASE_PATH, DATA_DIR
except ImportError:
    from config import DATABASE_PATH, DATA_DIR

def backup_database(database_path: Path = DATABASE_PATH, destination_dir: Path | None = None) -> Path:
    source = Path(database_path)
    if not source.is_file():
        raise FileNotFoundError("Database is unavailable for backup.")
    destination_dir = destination_dir or DATA_DIR / "backups"
    destination_dir.mkdir(parents=True, exist_ok=True)
    name = f"missing_child_ai_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
    target = destination_dir / name
    if target.exists():
        raise FileExistsError("Backup destination already exists.")
    shutil.copy2(source, target)
    if not target.is_file() or target.stat().st_size <= 0:
        raise OSError("Backup verification failed.")
    return target

if __name__ == "__main__":
    print(f"BACKUP OK: {backup_database().name}")
