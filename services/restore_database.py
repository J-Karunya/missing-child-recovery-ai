"""Safe SQLite restore utility. Default is dry-run and never replaces silently."""
from __future__ import annotations
import argparse, shutil, sqlite3
from pathlib import Path
try:
    from .backup_database import backup_database
except ImportError:
    from backup_database import backup_database

REQUIRED_TABLES = {"users", "cases", "potential_matches", "audit_logs"}

def validate_database(path: Path) -> bool:
    try:
        with sqlite3.connect(path) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return REQUIRED_TABLES.issubset(tables)
    except sqlite3.Error:
        return False

def restore_database(source: Path, destination: Path, confirm_replace: bool = False, dry_run: bool = True) -> Path:
    source, destination = Path(source), Path(destination)
    if not source.is_file() or not validate_database(source):
        raise ValueError("Source backup is not a valid project SQLite database.")
    if destination.exists() and not confirm_replace:
        raise PermissionError("Destination exists; explicit replacement confirmation is required.")
    if dry_run:
        return destination
    if destination.exists():
        backup_database(destination, destination.parent / "pre_restore_backups")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if not validate_database(destination):
        raise OSError("Restored database validation failed.")
    return destination

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Safely restore a verified project SQLite backup.")
    parser.add_argument("source"); parser.add_argument("destination")
    parser.add_argument("--confirm-replace", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Perform restore; default is dry-run.")
    args = parser.parse_args()
    result = restore_database(Path(args.source), Path(args.destination), args.confirm_replace, not args.apply)
    print("RESTORE " + ("APPLIED" if args.apply else "DRY-RUN") + f": {result.name}")
