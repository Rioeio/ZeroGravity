from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class DeduplicationRegistry:
    """SQLite-backed registry for tracking deduplicated packages."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            self.db_path = Path.home() / ".zerogravity" / "registry.db"
        else:
            self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS packages (
                    hash TEXT PRIMARY KEY,
                    store_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    file_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash TEXT NOT NULL REFERENCES packages(hash),
                    link_path TEXT NOT NULL UNIQUE,
                    project_path TEXT,
                    original_path TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
            conn.commit()

    def __enter__(self) -> DeduplicationRegistry:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self.conn = conn
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.conn:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
            self.conn.close()
            self.conn = None

    def _get_connection(self) -> sqlite3.Connection:
        if self.conn:
            return self.conn
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def register_package(self, hash: str, store_path: str, size_bytes: int, file_count: int) -> None:
        """Register a new package in the store."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    '''INSERT OR IGNORE INTO packages
                       (hash, store_path, size_bytes, file_count, created_at)
                       VALUES (?, ?, ?, ?, ?)''',
                    (hash, store_path, size_bytes, file_count, datetime.utcnow().isoformat())
                )
        finally:
            if not self.conn:
                conn.close()

    def register_link(self, hash: str, link_path: str, project_path: str, original_path: str) -> None:
        """Register a new link to a package."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    '''INSERT INTO links
                       (hash, link_path, project_path, original_path, created_at)
                       VALUES (?, ?, ?, ?, ?)''',
                    (hash, link_path, project_path, original_path, datetime.utcnow().isoformat())
                )
        finally:
            if not self.conn:
                conn.close()

    def get_package(self, hash: str) -> Optional[Dict[str, Any]]:
        """Retrieve package information by hash."""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute('SELECT * FROM packages WHERE hash = ?', (hash,))
                row = cursor.fetchone()
                return dict(row) if row else None
        finally:
            if not self.conn:
                conn.close()

    def get_links_for_package(self, hash: str) -> List[Dict[str, Any]]:
        """Retrieve all links associated with a package hash."""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute('SELECT * FROM links WHERE hash = ?', (hash,))
                return [dict(row) for row in cursor.fetchall()]
        finally:
            if not self.conn:
                conn.close()

    def get_all_links(self) -> List[Dict[str, Any]]:
        """Retrieve all active links."""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute('SELECT * FROM links')
                return [dict(row) for row in cursor.fetchall()]
        finally:
            if not self.conn:
                conn.close()

    def remove_link(self, link_path: str) -> None:
        """Remove a link from the registry."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute('DELETE FROM links WHERE link_path = ?', (link_path,))
        finally:
            if not self.conn:
                conn.close()

    def remove_package(self, hash: str) -> None:
        """Remove a package and all its associated links from the registry."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute('DELETE FROM links WHERE hash = ?', (hash,))
                conn.execute('DELETE FROM packages WHERE hash = ?', (hash,))
        finally:
            if not self.conn:
                conn.close()

    def package_exists(self, hash: str) -> bool:
        """Check if a package exists in the registry."""
        return self.get_package(hash) is not None

    def get_savings_report(self) -> Dict[str, Any]:
        """Generate a report on deduplication savings."""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute('''
                    SELECT
                        COUNT(*) as total_packages,
                        SUM(size_bytes) as total_bytes_stored,
                        MAX(size_bytes) as largest_package_bytes
                    FROM packages
                ''')
                pkg_stats = dict(cursor.fetchone() or {})

                cursor = conn.execute('SELECT COUNT(*) as total_links FROM links')
                link_stats = dict(cursor.fetchone() or {})

                total_packages = pkg_stats.get('total_packages') or 0
                total_links = link_stats.get('total_links') or 0
                total_bytes_stored = pkg_stats.get('total_bytes_stored') or 0
                largest_package_bytes = pkg_stats.get('largest_package_bytes') or 0

                avg_size = (total_bytes_stored / total_packages) if total_packages > 0 else 0
                estimated_bytes_saved = int((total_links - total_packages) * avg_size) if total_links > total_packages else 0

                return {
                    "total_packages": total_packages,
                    "total_links": total_links,
                    "total_bytes_stored": total_bytes_stored,
                    "estimated_bytes_saved": estimated_bytes_saved,
                    "largest_package_bytes": largest_package_bytes
                }
        finally:
            if not self.conn:
                conn.close()
