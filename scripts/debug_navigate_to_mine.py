import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

from api.client import ApiClient
from data.enums import ShipNavFlightMode, WaypointTraitType
from data.warehouse import Warehouse
from logic.navigation import Navigation
from logic.navigation_algorithms import NavigationAlgorithms


def _as_json(obj) -> str:
    try:
        return json.dumps(obj, indent=2, sort_keys=True)
    except Exception:
        return str(obj)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Debug navigate-to-mine for a single ship")
    p.add_argument("--ship", required=True, help="Ship symbol, e.g. RAMZA4-4")
    p.add_argument("--target", help="Waypoint symbol to navigate to; if omitted, choose closest mineable")
    p.add_argument(
        "--flight-mode",
        choices=[m.name for m in ShipNavFlightMode],
        default=ShipNavFlightMode.BURN.name,
        help="Flight mode to use while navigating",
    )
    p.add_argument("--no-wait", action="store_true", help="Do not wait for arrival; exit after navigate")
    p.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    return p


def main() -> int:
    load_dotenv()
    args = build_arg_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    token = os.getenv("AGENT_TOKEN")
    if not token:
        logging.error("AGENT_TOKEN not set; export it or add to .env")
        return 1

    client = ApiClient(token)
    warehouse = Warehouse()
    navigator = Navigation(client, warehouse)
    nav_algos = NavigationAlgorithms(client, warehouse)

    ship_symbol = args.ship
    logging.info(f"Debugging navigate-to-mine for ship {ship_symbol}")

    # Fetch ship and upsert
    ship_payload = client.fleet.get_ship(ship_symbol)
    ship = warehouse.upsert_ship(ship_payload.get("data") if isinstance(ship_payload, dict) else {})
    logging.info(
        f"Initial ship: wp={ship.nav.waypointSymbol} status={ship.nav.status} fuel={ship.fuel.current}/{ship.fuel.capacity}"
    )

    # Choose target
    target: str | None = args.target
    if not target:
        try:
            target = nav_algos.find_closest_mineable_waypoint(ship_symbol)
        except Exception as e:
            logging.error(f"Failed to find mineable waypoint: {e}")
            return 2
    logging.info(f"Target mineable waypoint: {target}")

    # Verify mineable traits on target
    mineable_traits = [
        WaypointTraitType.MINERAL_DEPOSITS,
        WaypointTraitType.COMMON_METAL_DEPOSITS,
        WaypointTraitType.PRECIOUS_METAL_DEPOSITS,
        WaypointTraitType.RARE_METAL_DEPOSITS,
        WaypointTraitType.METHANE_POOLS,
        WaypointTraitType.ICE_CRYSTALS,
        WaypointTraitType.EXPLOSIVE_GASES,
    ]
    try:
        has_mine = any(navigator._waypoint_has_trait(target, t) for t in mineable_traits)
        logging.info(f"Target trait check: mineable={has_mine}")
    except Exception as e:
        logging.warning(f"Trait verification skipped due to error: {e}")

    # Ensure orbit and set flight mode
    try:
        navigator._ensure_orbit(ship_symbol)
    except Exception as e:
        logging.warning(f"ensure_orbit failed (continuing): {e}")
    try:
        fm = ShipNavFlightMode[args.flight_mode]
        navigator._maybe_set_flight_mode(ship_symbol, fm)
    except Exception as e:
        logging.warning(f"set flight mode failed (continuing): {e}")

    # Perform raw navigate call to capture error payloads verbatim
    logging.info(f"Calling navigate_ship to {target} in {args.flight_mode} mode")
    try:
        raw_resp = client.fleet.navigate_ship(ship_symbol, target)
        logging.info(f"navigate_ship response:\n{_as_json(raw_resp)}")
    except Exception as e:
        logging.error(f"navigate_ship raised exception: {e}")
        return 3

    # Apply minimal response to cached ship (mirror Navigation.navigate_in_system behavior)
    try:
        data_obj = raw_resp.get("data") if isinstance(raw_resp, dict) else None
        if isinstance(data_obj, dict):
            nav_obj = data_obj.get("nav") if isinstance(data_obj, dict) else None
            fuel_obj = data_obj.get("fuel") if isinstance(data_obj, dict) else None
            ship = warehouse.ships_by_symbol.get(ship_symbol) or navigator._refresh_ship(ship_symbol)
            if isinstance(nav_obj, dict) and ship and ship.nav:
                status_val = nav_obj.get("status")
                if isinstance(status_val, str):
                    from data.enums import ShipNavStatus as _NavStatus

                    try:
                        ship.nav.status = _NavStatus(status_val)
                    except Exception:
                        pass
                ship.nav.systemSymbol = nav_obj.get("systemSymbol", ship.nav.systemSymbol)
                ship.nav.waypointSymbol = nav_obj.get("waypointSymbol", ship.nav.waypointSymbol)
                route_dict = nav_obj.get("route") or {}
                if isinstance(route_dict, dict) and ship.nav.route:
                    dest = route_dict.get("destination") or {}
                    if isinstance(dest, dict) and ship.nav.route.destination:
                        ship.nav.route.destination.symbol = dest.get("symbol")
                        ship.nav.route.destination.systemSymbol = dest.get("systemSymbol")
                        ship.nav.route.destination.x = dest.get("x")
                        ship.nav.route.destination.y = dest.get("y")
                    origin = route_dict.get("origin") or {}
                    if isinstance(origin, dict) and ship.nav.route.departure:
                        ship.nav.route.departure.symbol = origin.get("symbol")
                        ship.nav.route.departure.systemSymbol = origin.get("systemSymbol")
                        ship.nav.route.departure.x = origin.get("x")
                        ship.nav.route.departure.y = origin.get("y")
                    ship.nav.route.departureTime = route_dict.get("departureTime", ship.nav.route.departureTime)
                    ship.nav.route.arrival = route_dict.get("arrival", ship.nav.route.arrival)
                    ship.nav.route.distance = route_dict.get("distance", ship.nav.route.distance)
            if isinstance(fuel_obj, dict) and ship and ship.fuel:
                ship.fuel.current = fuel_obj.get("current", ship.fuel.current)
                ship.fuel.capacity = fuel_obj.get("capacity", ship.fuel.capacity)
    except Exception as e:
        logging.warning(f"Failed to apply nav response to cached ship: {e}")

    # Print post-state
    ship = warehouse.ships_by_symbol.get(ship_symbol) or ship
    try:
        dest = (
            ship.nav.route.destination.symbol
            if ship and ship.nav and ship.nav.route and ship.nav.route.destination
            else None
        )
        arrival = ship.nav.route.arrival if ship and ship.nav and ship.nav.route else None
        logging.info(
            f"Post-navigate: status={ship.nav.status} now_at={ship.nav.waypointSymbol} dest={dest} arrival={arrival}"
        )
    except Exception:
        pass

    # Optionally wait
    if not args.no_wait:
        try:
            logging.info("Waiting for arrival (polling)...")
            ship = navigator.wait_until_arrival(ship_symbol, poll_interval_s=5, timeout_s=600)
            logging.info(f"Arrived at {ship.nav.waypointSymbol}; status={ship.nav.status}")
        except TimeoutError:
            logging.error("Timed out waiting for arrival")
            return 4
        except Exception as e:
            logging.error(f"Error while waiting for arrival: {e}")
            return 5

    return 0


if __name__ == "__main__":
    sys.exit(main())
