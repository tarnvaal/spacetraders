import argparse
import os
import sys

from dotenv import load_dotenv

from api.client import ApiClient


def derive_system_symbol(waypoint_symbol: str) -> str:
    parts = waypoint_symbol.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return waypoint_symbol


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Manually purchase a ship at a shipyard.")
    parser.add_argument(
        "-w",
        "--waypoint",
        default="X1-GZ7-H60",
        help="Waypoint symbol of the shipyard (e.g. X1-GZ7-H60)",
    )
    parser.add_argument(
        "-t",
        "--type",
        default="SHIP_MINING_DRONE",
        help="Ship type to purchase (e.g. SHIP_MINING_DRONE)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available ships at the shipyard before purchasing.",
    )
    parser.add_argument(
        "--skip-presence-check",
        action="store_true",
        help="Skip check for having a ship present at the waypoint.",
    )

    args = parser.parse_args()

    agent_token = os.getenv("AGENT_TOKEN")
    if not agent_token:
        print("Missing AGENT_TOKEN in environment.", file=sys.stderr)
        sys.exit(1)

    client = ApiClient(agent_token)

    waypoint_symbol = args.waypoint
    system_symbol = derive_system_symbol(waypoint_symbol)

    # Optionally list available ships at the shipyard
    if args.list:
        try:
            shipyard_info = client.waypoints.find_waypoint_available_ships(system_symbol, waypoint_symbol)
            # The API wrapper returns the data object; show a concise view if possible
            ship_types = []
            if isinstance(shipyard_info, dict):
                ship_types = [st.get("type") for st in shipyard_info.get("shipTypes", [])]
            print(f"Shipyard {waypoint_symbol} available types: {', '.join([t for t in ship_types if t]) or 'unknown'}")
        except Exception as exc:
            print(f"Warning: failed to list shipyard offerings: {exc}", file=sys.stderr)

    # Verify we have a ship present at this waypoint (recommended for price visibility)
    if not args.skip_presence_check:
        try:
            fleet_payload = client.fleet.get_my_ships()
            fleet_data = fleet_payload.get("data", []) if isinstance(fleet_payload, dict) else []
            at_waypoint = any(
                (ship.get("nav", {}) or {}).get("waypointSymbol") == waypoint_symbol for ship in fleet_data
            )
            if not at_waypoint:
                print(
                    "Warning: No ship detected at the target shipyard waypoint. Prices/details may be hidden.",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(f"Warning: failed to verify ship presence: {exc}", file=sys.stderr)

    # Perform purchase
    payload = {"shipType": args.type, "waypointSymbol": waypoint_symbol}
    try:
        url = f"{client.http.base_url}/my/ships"
        resp = client.http.post(url, headers=client.http.auth_headers(client.agent_key), json=payload)
        data = resp.json()

        if resp.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            code = err.get("code") if isinstance(err, dict) else resp.status_code
            message = err.get("message") if isinstance(err, dict) else str(data)
            print(f"Purchase failed ({code}): {message}", file=sys.stderr)
            sys.exit(1)

        # Best-effort extraction of key fields
        purchase_data = data.get("data", {}) if isinstance(data, dict) else {}
        ship = purchase_data.get("ship", {})
        transaction = purchase_data.get("transaction", {})
        ship_symbol = ship.get("symbol", "?")
        price = transaction.get("price")
        print("Purchase successful.")
        print(f"  Ship: {ship_symbol}")
        if price is not None:
            print(f"  Price: {price}")
        # Some responses include agent details; show credits if present
        agent = purchase_data.get("agent", {})
        credits = agent.get("credits")
        if credits is not None:
            print(f"  Remaining Credits: {credits}")
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Unexpected error during purchase: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
