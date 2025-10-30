"""
Market CLI: query best buy/sell prices from the SQLite store.

Usage examples:
  python -m scripts.market_cli best-sell --good FUEL --hours 6
  python -m scripts.market_cli best-buy --good IRON_ORE --hours 24 --limit 3
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from collections.abc import Iterable


def _db_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base_dir, "data", "markets.db")


def _connect(db_path: str) -> sqlite3.Connection:
    if not os.path.isfile(db_path):
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(2)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _cutoff_iso(hours: int) -> str:
    seconds = max(0, int(hours)) * 3600
    ts = time.gmtime(time.time() - seconds)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", ts)


def best_sell(conn: sqlite3.Connection, good: str, hours: int, limit: int) -> Iterable[sqlite3.Row]:
    cutoff = _cutoff_iso(hours)
    cur = conn.execute(
        """
        SELECT ts, system, waypoint, good, sell_price AS price
        FROM market_observations
        WHERE good = ? AND ts >= ? AND sell_price IS NOT NULL
        ORDER BY price DESC, ts DESC
        LIMIT ?
        """,
        (good, cutoff, limit),
    )
    return cur.fetchall()


def best_buy(conn: sqlite3.Connection, good: str, hours: int, limit: int) -> Iterable[sqlite3.Row]:
    cutoff = _cutoff_iso(hours)
    cur = conn.execute(
        """
        SELECT ts, system, waypoint, good, buy_price AS price
        FROM market_observations
        WHERE good = ? AND ts >= ? AND buy_price IS NOT NULL
        ORDER BY price ASC, ts DESC
        LIMIT ?
        """,
        (good, cutoff, limit),
    )
    return cur.fetchall()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query market prices from SQLite store")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sell = sub.add_parser("best-sell", help="Show highest sell price in a time window")
    p_sell.add_argument("--good", required=True, help="Trade good symbol, e.g. FUEL")
    p_sell.add_argument("--hours", type=int, default=6, help="Lookback window in hours (default: 6)")
    p_sell.add_argument("--limit", type=int, default=1, help="Max rows to return (default: 1)")

    p_buy = sub.add_parser("best-buy", help="Show lowest buy price in a time window")
    p_buy.add_argument("--good", required=True, help="Trade good symbol, e.g. IRON_ORE")
    p_buy.add_argument("--hours", type=int, default=6, help="Lookback window in hours (default: 6)")
    p_buy.add_argument("--limit", type=int, default=1, help="Max rows to return (default: 1)")

    args = parser.parse_args(argv)

    dbp = _db_path()
    conn = _connect(dbp)
    good = args.good.upper()

    if args.cmd == "best-sell":
        rows = best_sell(conn, good, args.hours, args.limit)
        for r in rows:
            print(f"{r['ts']} {r['system']} {r['waypoint']} {r['good']} SELL {r['price']}")
        return 0
    if args.cmd == "best-buy":
        rows = best_buy(conn, good, args.hours, args.limit)
        for r in rows:
            print(f"{r['ts']} {r['system']} {r['waypoint']} {r['good']} BUY {r['price']}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
