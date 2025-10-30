"""
SQLite-backed persistence for market observations and transactions.
Single-file DB with WAL; 2-day retention enforced periodically.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time

_storage_singleton = None
_singleton_lock = threading.Lock()


class SQLiteStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._create_schema()
        self._lock = threading.Lock()
        self._last_cleanup_time = 0.0

    def _create_schema(self) -> None:
        cur = self._conn.cursor()
        # Observations
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS market_observations (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                system TEXT NOT NULL,
                waypoint TEXT NOT NULL,
                good TEXT NOT NULL,
                buy_price REAL,
                sell_price REAL,
                trade_volume INTEGER,
                supply TEXT,
                activity TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_obs_good_ts ON market_observations(good, ts DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_obs_wp_ts ON market_observations(waypoint, ts DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_obs_ts ON market_observations(ts)")

        # Transactions
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                ship TEXT,
                waypoint TEXT,
                action TEXT NOT NULL, -- BUY or SELL
                symbol TEXT,
                units INTEGER,
                unit_price REAL,
                total_price REAL,
                credits_after INTEGER
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_ts ON transactions(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_ship_ts ON transactions(ship, ts DESC)")
        self._conn.commit()

    def _maybe_cleanup(self, days: int = 2) -> None:
        now = time.time()
        # Cleanup at most once per hour
        if now - self._last_cleanup_time < 3600:
            return
        self._last_cleanup_time = now
        # Threshold ISO string (SQLite stores as text; compare lexicographically if ISO-8601)
        cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - days * 86400))
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM market_observations WHERE ts < ?", (cutoff_iso,))
            cur.execute("DELETE FROM transactions WHERE ts < ?", (cutoff_iso,))
            self._conn.commit()

    def insert_market_observation(
        self,
        *,
        ts: str,
        system: str,
        waypoint: str,
        good: str,
        buy_price: float | None,
        sell_price: float | None,
        trade_volume: int | None,
        supply: str | None,
        activity: str | None,
    ) -> None:
        self._maybe_cleanup(days=2)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO market_observations
                (ts, system, waypoint, good, buy_price, sell_price, trade_volume, supply, activity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, system, waypoint, good, buy_price, sell_price, trade_volume, supply, activity),
            )
            self._conn.commit()

    def insert_transaction(
        self,
        *,
        ts: str,
        ship: str | None,
        waypoint: str | None,
        action: str,
        symbol: str | None,
        units: int | None,
        unit_price: float | None,
        total_price: float | None,
        credits_after: int | None,
    ) -> None:
        self._maybe_cleanup(days=2)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO transactions
                (ts, ship, waypoint, action, symbol, units, unit_price, total_price, credits_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, ship, waypoint, action, symbol, units, unit_price, total_price, credits_after),
            )
            self._conn.commit()

    def fetch_latest_prices_by_waypoint(self) -> dict:
        """
        Return a mapping of waypoint -> {
            "system": str,
            "goods": list[{
                "good": str,
                "buy_price": float | None,
                "sell_price": float | None,
                "ts": str,
            }]
        }
        using the most recent observation per (waypoint, good).
        """
        result: dict[str, dict] = {}
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT mo1.system, mo1.waypoint, mo1.good, mo1.buy_price, mo1.sell_price, mo1.ts
                FROM market_observations mo1
                JOIN (
                    SELECT waypoint, good, MAX(ts) AS ts
                    FROM market_observations
                    GROUP BY waypoint, good
                ) latest
                ON mo1.waypoint = latest.waypoint AND mo1.good = latest.good AND mo1.ts = latest.ts
                ORDER BY mo1.waypoint, mo1.good
                """
            )
            rows = cur.fetchall()
        for system, waypoint, good, buy_price, sell_price, ts in rows:
            entry = result.setdefault(waypoint, {"system": system, "goods": []})
            entry["goods"].append(
                {
                    "good": good,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "ts": ts,
                }
            )
        return result


def get_storage(db_path: str | None = None) -> SQLiteStorage:
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton
    with _singleton_lock:
        if _storage_singleton is None:
            if not db_path:
                # Default under data/ directory
                base_dir = os.path.dirname(__file__)
                db_path = os.path.join(base_dir, "markets.db")
            _storage_singleton = SQLiteStorage(db_path)
        return _storage_singleton
