"""
Scanner module for discovering and mapping systems, waypoints, ships, and markets.
Handles initial fleet and system reconnaissance operations.
"""
from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType, ShipRole, CommonTradeGood

class Scanner():
    def __init__(self, client: ApiClient, warehouse: Warehouse):
        self.client = client
        self.warehouse = warehouse
        self.hq_system = ""
        agent_data = self.client.agent.get()['data']
        for key, value in agent_data.items():
            setattr(self.warehouse, key, value)
        self.hq_system = "-".join((agent_data['headquarters'].split("-")[:2]))
        
    def print_hq_system(self):
        print(f"HQ system: {self.hq_system}")
        print(F"Credits: {self.warehouse.credits}")
        
    def scan_systems(self):
        systems_api = self.client.systems
        systems_payload = systems_api.get()['data']
        loaded_systems = self.warehouse.upsert_systems(systems_payload)
        print(f"Populated {len(loaded_systems)} systems")
        
    def scan_waypoints_by_type(self, waypoint_type: WaypointTraitType):
        waypoints_api = self.client.waypoints
        waypoints_payload = waypoints_api.find_waypoints_by_trait(self.hq_system, waypoint_type)
        loaded_waypoints = self.warehouse.upsert_waypoints_detail(waypoints_payload)
        print(f"Populated {len(loaded_waypoints)} waypoints of type {waypoint_type.value}")
        
    def print_waypoints_by_type(self, waypoint_type: WaypointTraitType):
        print(f"Printing {waypoint_type.value} waypoints...")
        for waypoint in self.warehouse.full_waypoints_by_symbol.values():
            matched_trait = next((t for t in waypoint.traits if t.symbol == waypoint_type.value), None)
            if matched_trait:
                print(f"    Waypoint: {waypoint.symbol} ({waypoint.type}) ({waypoint.x}, {waypoint.y})")
                print(f"        Trait: {matched_trait.symbol}" + (f" - {matched_trait.name}" if matched_trait.name else ""))
                if waypoint_type == WaypointTraitType.SHIPYARD:
                    available_ships = self.client.waypoints.find_waypoint_available_ships(self.hq_system, waypoint.symbol)
                    for shipType in available_ships.get('shipTypes', []):
                        print(f"            {shipType['type']}")
                        
    def scan_fleet(self):
        fleet_payload = self.client.fleet.get_my_ships()
        loaded_fleet = self.warehouse.upsert_fleet(fleet_payload)
        print(f"Populated {len(loaded_fleet)} fleet")

    def print_fleet(self):
        fleet = self.client.fleet.get_my_ships()

        for ship in fleet.get('data', []):
            print(f"Ship: {ship['symbol']}")
            print(f"    Type: {ship['registration']['role']}")
            if ship.get('fuel', {}).get('capacity', 0) > 0:
                print(f"    Fuel: {ship['fuel'].get('current', 0)} / {ship['fuel'].get('capacity', 0)}")
            print(f"    Location: {ship.get('nav', {}).get('waypointSymbol')}")
            nav = ship.get('nav', {})
            route = nav.get('route', {})
            origin = route.get('origin', {})
            destination = route.get('destination', {})
            print(f"    Nav: {nav.get('status')} @ {nav.get('systemSymbol')}/{nav.get('waypointSymbol')} [{nav.get('flightMode', 'CRUISE')}]")
            if route:
                print(f"        Route: {origin.get('symbol', '?')} -> {destination.get('symbol', '?')}")
                if 'departureTime' in route and 'arrival' in route:
                    print(f"        Times: depart {route['departureTime']} arrive {route['arrival']}")
            engine = ship.get('engine', {})
            if engine:
                speed = engine.get('speed', '?')
                print(f"    Engine: {engine.get('symbol', '?')} (speed {speed})")
            cargo = ship.get('cargo', {})
            if cargo.get('capacity', 0) > 0:
                print(f"    Cargo: {cargo.get('units', 0)} / {cargo.get('capacity', 0)}")
            cooldown = ship.get('cooldown', {})
            if cooldown.get('totalSeconds', 0) > 0:
                print(f"    Cooldown: {cooldown.get('remainingSeconds', 0)} / {cooldown.get('totalSeconds', 0)}")

    # Probe market scanning
    def _get_probe_symbol(self) -> str | None:
        for ship in self.warehouse.ships_by_symbol.values():
            if ship.registration and ship.registration.role == ShipRole.SATELLITE:
                return ship.symbol
        return None

    def scan_marketplaces_with_probe(self, probe_symbol: str | None = None):
        """
        Navigate a probe between marketplaces in the HQ system, docking to fetch market data and
        upserting observations into the warehouse.
        """
        symbol = probe_symbol or self._get_probe_symbol()
        if not symbol:
            print("[Probe] No probe (SATELLITE) ship found; skipping market scan")
            return
        # Enumerate marketplaces in HQ system
        waypoints_payload = self.client.waypoints.find_waypoints_by_trait(self.hq_system, WaypointTraitType.MARKETPLACE)
        if not waypoints_payload:
            print("[Probe] No marketplaces found in HQ system; skipping")
            return
        self.warehouse.upsert_waypoints_detail(waypoints_payload)

        # For a simple pass: iterate in listed order
        for wp in waypoints_payload:
            wp_symbol = wp.get('symbol')
            if not wp_symbol:
                continue
            try:
                print(f"[Probe] Navigating {symbol} to {wp_symbol} for market scan...")
                # Ensure orbit, navigate, wait, dock, fetch market
                from logic.navigation import Navigation
                nav = Navigation(self.client, self.warehouse)
                nav.navigate_in_system(symbol, wp_symbol)
                nav.wait_until_arrival(symbol, poll_interval_s=3, timeout_s=120)
                nav._ensure_docked(symbol)
                market = self.client.waypoints.get_market(self.hq_system, wp_symbol)
                if market:
                    self.warehouse.upsert_market_snapshot(self.hq_system, market)
                    for good in market.get('tradeGoods', []) or []:
                        self.warehouse.record_good_observation(self.hq_system, wp_symbol, good)
                    print(f"[Probe] Recorded market at {wp_symbol} with {len(market.get('tradeGoods', []) or [])} goods")
                else:
                    print(f"[Probe] No market data at {wp_symbol}")
                nav._ensure_orbit(symbol)
            except Exception as e:
                print(f"[Probe] Error scanning {wp_symbol}: {e}")

    def print_known_market_observations(self, good_symbol: str | None = None):
        def _print_one(symbol: str):
            obs = self.warehouse.goods_observations.get(symbol, [])
            print(f"Known observations for {symbol} ({len(obs)}):")
            for o in obs:
                print(f"  {o.get('waypointSymbol')} sell {o.get('sellPrice')} buy {o.get('purchasePrice')} vol {o.get('tradeVolume')} seen {o.get('seenAt')}")

        if good_symbol:
            # Support enums and plain strings
            try:
                if good_symbol.upper() == "COMMON":
                    for cg in CommonTradeGood:
                        _print_one(cg.value)
                    return
                # If matches a CommonTradeGood, map to value
                if good_symbol in CommonTradeGood.__members__:
                    symbol = CommonTradeGood[good_symbol].value
                    _print_one(symbol)
                    return
            except Exception:
                pass
            _print_one(good_symbol)
            return

        print("Known market snapshots by waypoint:")
        for wp, snap in self.warehouse.market_prices_by_waypoint.items():
            goods = snap.get('tradeGoods', []) or []
            print(f"  {wp} ({len(goods)} goods) seen {snap.get('seenAt')}")