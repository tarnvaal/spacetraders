"""
Warehouse module for caching and managing game state including systems, waypoints, ships, and market data.
Serves as the central data store for all discovered game entities.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from data.models.runtime import ShipRuntime
from data.models.ship import Ship
from data.models.system import System, SystemWaypointRef
from data.models.waypoints import Waypoints
from data.storage import get_storage


@dataclass
class Warehouse:
    accountId: str = ""
    symbol: str = ""
    headquarters: str = ""
    credits: int = 0
    startingFaction: str = ""
    shipCount: int = 0
    sectorsKnown: dict[str, Any] | None = None
    systems_by_symbol: dict[str, System] = field(default_factory=dict)
    waypoints_by_symbol: dict[str, SystemWaypointRef] = field(default_factory=dict)
    full_waypoints_by_symbol: dict[str, Waypoints] = field(default_factory=dict)
    ships_by_symbol: dict[str, Ship] = field(default_factory=dict)
    # Market knowledge base
    market_prices_by_waypoint: dict[str, dict[str, Any]] = field(default_factory=dict)
    goods_observations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Per-ship runtime state (FSM)
    runtime: dict[str, ShipRuntime] = field(default_factory=dict)

    def __post_init__(self):
        if self.sectorsKnown is None:
            self.sectorsKnown = {
                "sectorSymbol": "",
                "type": "",
                "x": 0,
                "y": 0,
                "waypoints": 0,
                "factions": [],
                "constellation": "",
                "name": "",
            }

    def load_agent_data(self, data: dict[str, Any]) -> None:
        known_keys = {"accountId", "symbol", "headquarters", "credits", "startingFaction", "shipCount"}
        for key in known_keys:
            if key in data:
                setattr(self, key, data[key])

    def upsert_system(self, payload: dict[str, Any]) -> System:
        sys = System.from_dict(payload)
        self.systems_by_symbol[sys.symbol] = sys
        for wp in sys.waypoints:
            self.waypoints_by_symbol[wp.symbol] = wp
        return sys

    def upsert_systems(self, payloads: list[dict[str, Any]]) -> list[System]:
        return [self.upsert_system(p) for p in payloads]

    def get_system(self, symbol: str) -> System | None:
        return self.systems_by_symbol.get(symbol)

    def get_systems_in_sector(self, sector_symbol: str) -> list[System]:
        return [s for s in self.systems_by_symbol.values() if s.sectorSymbol == sector_symbol]

    def systems_count(self) -> int:
        return len(self.systems_by_symbol)

    def upsert_waypoint_detail(self, payload: dict[str, Any]) -> Waypoints:
        w = Waypoints.from_detail_dict(payload)
        self.full_waypoints_by_symbol[w.symbol] = w
        ref = self.waypoints_by_symbol.get(w.symbol)
        if ref is None:
            ref = SystemWaypointRef(
                symbol=w.symbol,
                type=w.type,
                x=w.x,
                y=w.y,
                orbitals=list(w.orbitals),
                orbits=w.orbits,
            )
            self.waypoints_by_symbol[w.symbol] = ref
        else:
            ref.type = w.type
            ref.x = w.x
            ref.y = w.y
            ref.orbitals = list(w.orbitals)
            ref.orbits = w.orbits
        return w

    def upsert_waypoints_detail(self, payloads: list[dict[str, Any]]) -> list[Waypoints]:
        return [self.upsert_waypoint_detail(p) for p in payloads]

    def upsert_ship(self, payload: dict[str, Any]) -> Ship:
        ship = Ship.from_dict(payload)
        self.ships_by_symbol[ship.symbol] = ship
        return ship

    def upsert_fleet(self, payload: dict[str, Any]) -> list[Ship]:
        ships_payload = payload.get("data", []) if isinstance(payload, dict) else []
        return [self.upsert_ship(p) for p in ships_payload]

    def get_waypoint_ref(self, symbol: str) -> SystemWaypointRef | None:
        return self.waypoints_by_symbol.get(symbol)

    def get_waypoint(self, symbol: str) -> Waypoints | None:
        return self.full_waypoints_by_symbol.get(symbol)

    def get_waypoints_in_system(self, system_symbol: str) -> list[SystemWaypointRef]:
        sys = self.systems_by_symbol.get(system_symbol)
        return list(sys.waypoints) if sys else []

    def get_children(self, symbol: str) -> list[SystemWaypointRef]:
        wp = self.waypoints_by_symbol.get(symbol)
        if not wp:
            return []
        return [self.waypoints_by_symbol[s] for s in wp.orbitals if s in self.waypoints_by_symbol]

    def get_parent(self, symbol: str) -> SystemWaypointRef | None:
        wp = self.waypoints_by_symbol.get(symbol)
        if not wp or not wp.orbits:
            return None
        return self.waypoints_by_symbol.get(wp.orbits)

    def __str__(self):
        output = ""
        output += f"Account ID: {self.accountId}\n"
        output += f"Symbol: {self.symbol}\n"
        output += f"Headquarters: {self.headquarters}\n"
        output += f"Credits: {self.credits}\n"
        output += f"Starting Faction: {self.startingFaction}\n"
        output += f"Ship Count: {self.shipCount}\n"
        return output

    def print_warehouse_size(self):
        print(
            "Warehouse size: "
            f"{self.systems_count()} systems, "
            f"{len(self.waypoints_by_symbol)} waypoints, "
            f"{len(self.full_waypoints_by_symbol)} full waypoints, "
            f"{len(self.ships_by_symbol)} ships"
        )

    # Market data helpers
    def upsert_market_snapshot(self, system_symbol: str, market_data: dict[str, Any]) -> None:
        if not isinstance(market_data, dict):
            return
        waypoint_symbol = market_data.get("symbol") or market_data.get("waypointSymbol")
        if not waypoint_symbol:
            return
        # Determine if prices changed compared to previous snapshot
        previous_snapshot = self.market_prices_by_waypoint.get(waypoint_symbol)

        def _extract_price_map(market_like: dict[str, Any] | None) -> dict[str, tuple[Any, Any]]:
            if not isinstance(market_like, dict):
                return {}
            goods_list = market_like.get("tradeGoods", [])
            result: dict[str, tuple[Any, Any]] = {}
            if isinstance(goods_list, list):
                for g in goods_list:
                    if not isinstance(g, dict):
                        continue
                    sym = g.get("symbol")
                    if not sym:
                        continue
                    result[str(sym)] = (g.get("purchasePrice"), g.get("sellPrice"))
            return result

        previous_prices = _extract_price_map(previous_snapshot)
        incoming_prices = _extract_price_map(market_data)
        prices_unchanged = bool(previous_prices) and previous_prices == incoming_prices
        snapshot = {
            "systemSymbol": system_symbol,
            "waypointSymbol": waypoint_symbol,
            "seenAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "tradeGoods": market_data.get("tradeGoods", []),
        }
        self.market_prices_by_waypoint[waypoint_symbol] = snapshot
        # Log prices only when changed; otherwise emit a single-line update
        goods = snapshot.get("tradeGoods", [])
        if prices_unchanged:
            try:
                logging.info(f"Updated market waypoint: {waypoint_symbol}")
            except Exception:
                pass
        else:
            if isinstance(goods, list) and goods:
                for g in goods:
                    if not isinstance(g, dict):
                        continue
                    sym = g.get("symbol")
                    if not sym:
                        continue
                    buy = g.get("purchasePrice")
                    sell = g.get("sellPrice")
                    try:
                        logging.info(f"Probe prices @ {waypoint_symbol} -> {sym}: buy={buy} sell={sell}")
                    except Exception:
                        # Never let logging failures impact game flow
                        pass

    def record_good_observation(self, system_symbol: str, waypoint_symbol: str, good: dict[str, Any]) -> None:
        if not isinstance(good, dict):
            return
        symbol = good.get("symbol")
        if not symbol:
            return
        obs = {
            "systemSymbol": system_symbol,
            "waypointSymbol": waypoint_symbol,
            "purchasePrice": good.get("purchasePrice"),
            "sellPrice": good.get("sellPrice"),
            "tradeVolume": good.get("tradeVolume"),
            "supply": good.get("supply"),
            "activity": good.get("activity"),
            "seenAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        self.goods_observations.setdefault(symbol, []).append(obs)
        # Persist to SQLite for long-running historical analytics
        try:
            storage = get_storage()
            storage.insert_market_observation(
                ts=obs["seenAt"],
                system=system_symbol,
                waypoint=waypoint_symbol,
                good=symbol,
                buy_price=obs["purchasePrice"],
                sell_price=obs["sellPrice"],
                trade_volume=obs["tradeVolume"],
                supply=obs["supply"],
                activity=obs["activity"],
            )
        except Exception:
            pass

    def load_market_data_from_storage(self) -> None:
        """
        Hydrate in-memory market snapshots from SQLite (latest per good per waypoint).
        Ships remain live-only; this only restores market_prices_by_waypoint and seeds goods_observations with the latest entries.
        """
        try:
            storage = get_storage()
            latest = storage.fetch_latest_prices_by_waypoint()
        except Exception:
            return
        for waypoint_symbol, payload in latest.items():
            system_symbol = payload.get("system") or ""
            goods_list = payload.get("goods") or []
            # Build tradeGoods array
            trade_goods: list[dict[str, Any]] = []
            latest_ts = None
            for g in goods_list:
                symbol = g.get("good")
                if not symbol:
                    continue
                purchase = g.get("buy_price")
                sell = g.get("sell_price")
                ts = g.get("ts")
                if isinstance(ts, str):
                    if latest_ts is None or ts > latest_ts:
                        latest_ts = ts
                trade_goods.append(
                    {
                        "symbol": symbol,
                        "purchasePrice": purchase,
                        "sellPrice": sell,
                    }
                )
                # Seed the latest observation for quick best-price queries
                try:
                    self.goods_observations.setdefault(symbol, []).append(
                        {
                            "systemSymbol": system_symbol,
                            "waypointSymbol": waypoint_symbol,
                            "purchasePrice": purchase,
                            "sellPrice": sell,
                            "tradeVolume": None,
                            "supply": None,
                            "activity": None,
                            "seenAt": ts or "",
                        }
                    )
                except Exception:
                    pass
            # Store snapshot
            self.market_prices_by_waypoint[waypoint_symbol] = {
                "systemSymbol": system_symbol,
                "waypointSymbol": waypoint_symbol,
                "seenAt": (latest_ts or datetime.utcnow().isoformat(timespec="seconds") + "Z"),
                "tradeGoods": trade_goods,
            }

    def get_best_sell_observation(self, good_symbol: str) -> dict[str, Any] | None:
        obs_list = self.goods_observations.get(good_symbol, [])
        if not obs_list:
            return None
        return max(
            (o for o in obs_list if isinstance(o.get("sellPrice"), int | float)),
            key=lambda o: o["sellPrice"],
            default=None,
        )

    def get_best_purchase_observation(self, good_symbol: str) -> dict[str, Any] | None:
        obs_list = self.goods_observations.get(good_symbol, [])
        if not obs_list:
            return None
        return min(
            (o for o in obs_list if isinstance(o.get("purchasePrice"), int | float)),
            key=lambda o: o["purchasePrice"],
            default=None,
        )
