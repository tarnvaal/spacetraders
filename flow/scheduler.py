import logging
import time
from datetime import datetime, timezone

from data.enums import ShipAction
from utils.time import parse_iso_utc


def run_scheduler(ctx) -> None:
    """Run the ship event loop using dispatcher decisions and executor actions."""
    while True:
        next_priority = ctx.event_queue.peek_next_priority()
        logging.debug(f"Next event queue priority (ISO): {next_priority}")
        if next_priority is None:
            logging.info("No ships in event queue")
            break
        now_dt = datetime.now(timezone.utc)
        try:
            target_dt = parse_iso_utc(next_priority)
            wait_s = max(0.0, (target_dt - now_dt).total_seconds())
            logging.debug(
                f"Scheduler timing: now={now_dt.isoformat()}, target={target_dt.isoformat()}, wait_s={wait_s:.3f}"
            )
        except Exception:
            logging.debug(f"Failed to parse next_priority {next_priority!r}; proceeding without wait.")
            wait_s = 0.0
        if wait_s > 0:
            sleep_s = max(0.05, min(wait_s, 0.5))
            logging.debug(f"Sleeping for {sleep_s:.3f}s (remaining {wait_s:.3f}s)")
            time.sleep(sleep_s)
            continue
        event = ctx.event_queue.extract_min()
        logging.debug(f"Dequeued event: {event} (previous target {next_priority})")
        if event is None:
            logging.info("No ships in event queue")
            break
        ship = ctx.dataWarehouse.ships_by_symbol.get(event)
        if ship is None:
            logging.error(f"Ship no longer exists: {event}")
            continue
        action = ctx.dispatcher.decide_next_action(ship.symbol)
        if action != ShipAction.NOOP:
            logging.info(
                f"Ship: {ship.symbol} - Fuel: {ship.fuel.current}/{ship.fuel.capacity} - Cargo: {ship.cargo.units}/{ship.cargo.capacity} - Action: {action}"
            )
        else:
            logging.debug(
                f"Ship: {ship.symbol} - Fuel: {ship.fuel.current}/{ship.fuel.capacity} - Cargo: {ship.cargo.units}/{ship.cargo.capacity} - Action: NOOP"
            )
        if action != ShipAction.NOOP:
            ctx.executor.execute(ship.symbol, action)
            # Refresh local ship entry minimally if action changed it
            ship = ctx.dataWarehouse.ships_by_symbol.get(ship.symbol) or ship
        readiness = ctx.dispatcher.shipReadiness(ship.symbol)
        logging.debug(f"Re-queueing {ship.symbol} with readiness={readiness}")
        ctx.event_queue.push(ship.symbol, readiness)
        if action != ShipAction.NOOP:
            logging.info(
                f"Ship added back to event queue: {ship.symbol} - {ship.registration.role} - Readiness: {readiness}"
            )
