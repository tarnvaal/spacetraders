import logging
from dataclasses import dataclass

from api.client import ApiClient
from data.warehouse import Warehouse
from flow.queue import MinHeap
from logic.markets import Markets
from logic.navigation import Navigation
from logic.navigation_algorithms import NavigationAlgorithms
from logic.scanner import Scanner
from policy.dispatcher import Dispatcher
from policy.executor import ActionExecutor


@dataclass
class AppContext:
    client: ApiClient
    dataWarehouse: Warehouse
    scanner: Scanner
    navigator: Navigation
    navigatorAlgorithms: NavigationAlgorithms
    markets: Markets
    event_queue: MinHeap
    dispatcher: Dispatcher
    executor: ActionExecutor


def build_app(agent_token: str) -> AppContext:
    logging.info("Systems initializing")

    client = ApiClient(agent_token)
    dataWarehouse = Warehouse()
    scanner = Scanner(client, dataWarehouse)
    navigator = Navigation(client, dataWarehouse)
    navigatorAlgorithms = NavigationAlgorithms(client, dataWarehouse)
    markets = Markets(client, dataWarehouse)

    # Hydrate market data from storage
    try:
        dataWarehouse.load_market_data_from_storage()
        logging.info(f"Loaded {len(dataWarehouse.market_prices_by_waypoint)} market waypoints from storage")
    except Exception:
        pass

    credits = scanner.get_credits()
    logging.info(f"Credits: {credits}")

    event_queue = MinHeap()
    dispatcher = Dispatcher(dataWarehouse, scanner, event_queue)
    dispatcher.update_fleet()

    # Initialize queue with ships
    for ship in dataWarehouse.ships_by_symbol.values():
        event_queue.push(ship.symbol, dispatcher.shipReadiness(ship.symbol))
        logging.info(
            f"Ship added to event queue:\n"
            f"- Ship: {ship.symbol} - {ship.registration.role}\n"
            f"- Readiness: {dispatcher.shipReadiness(ship.symbol)}\n"
            f"- Cargo: {ship.cargo.units}/{ship.cargo.capacity}\n"
            f"- Fuel: {ship.fuel.current}/{ship.fuel.capacity}"
        )
    logging.info(f"Initial size of event queue: {event_queue.size()}")

    executor = ActionExecutor(
        client=client,
        data_warehouse=dataWarehouse,
        navigator=navigator,
        navigator_algorithms=navigatorAlgorithms,
        markets=markets,
    )

    logging.info("All systems operational.")
    return AppContext(
        client=client,
        dataWarehouse=dataWarehouse,
        scanner=scanner,
        navigator=navigator,
        navigatorAlgorithms=navigatorAlgorithms,
        markets=markets,
        event_queue=event_queue,
        dispatcher=dispatcher,
        executor=executor,
    )
