from dataclasses import dataclass, field
from typing import Any

from data.enums import ShipNavFlightMode, ShipNavStatus, ShipRole


@dataclass
class ShipRegistration:
    name: str | None
    factionSymbol: str | None
    role: ShipRole | None


@dataclass
class ShipNavRouteWaypoint:
    symbol: str | None
    type: str | None
    systemSymbol: str | None
    x: int | None
    y: int | None


@dataclass
class ShipNavRoute:
    departure: ShipNavRouteWaypoint | None
    destination: ShipNavRouteWaypoint | None
    departureTime: str | None
    arrival: str | None
    distance: int | None


@dataclass
class ShipNav:
    systemSymbol: str | None
    waypointSymbol: str | None
    route: ShipNavRoute | None
    status: ShipNavStatus | None
    flightMode: ShipNavFlightMode = ShipNavFlightMode.CRUISE


@dataclass
class ShipEngine:
    symbol: str | None
    name: str | None
    description: str | None
    speed: int | None


@dataclass
class ShipFuel:
    current: int = 0
    capacity: int = 0


@dataclass
class ShipCooldown:
    totalSeconds: int = 0
    remainingSeconds: int = 0


@dataclass
class ShipCargo:
    capacity: int = 0
    units: int = 0


@dataclass
class Ship:
    symbol: str
    registration: ShipRegistration
    nav: ShipNav
    engine: ShipEngine | None = None
    fuel: ShipFuel = field(default_factory=ShipFuel)
    cargo: ShipCargo = field(default_factory=ShipCargo)
    cooldown: ShipCooldown = field(default_factory=ShipCooldown)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Ship":
        registration_dict = d.get("registration", {}) or {}
        role_value = registration_dict.get("role")
        role = ShipRole(role_value) if isinstance(role_value, str) and role_value in ShipRole.__members__ else None

        registration = ShipRegistration(
            name=registration_dict.get("name"),
            factionSymbol=registration_dict.get("factionSymbol"),
            role=role,
        )

        nav_dict = d.get("nav", {}) or {}
        route_dict = nav_dict.get("route", {}) or {}

        def wp_from(dct: dict[str, Any]) -> ShipNavRouteWaypoint:
            if not isinstance(dct, dict):
                return ShipNavRouteWaypoint(symbol=None, type=None, systemSymbol=None, x=None, y=None)
            return ShipNavRouteWaypoint(
                symbol=dct.get("symbol"),
                type=dct.get("type"),
                systemSymbol=dct.get("systemSymbol"),
                x=dct.get("x"),
                y=dct.get("y"),
            )

        route = (
            ShipNavRoute(
                departure=wp_from(route_dict.get("origin", {})),
                destination=wp_from(route_dict.get("destination", {})),
                departureTime=route_dict.get("departureTime"),
                arrival=route_dict.get("arrival"),
                distance=route_dict.get("distance"),
            )
            if route_dict
            else None
        )

        status_value = nav_dict.get("status")
        status = None
        if isinstance(status_value, str):
            try:
                status = ShipNavStatus(status_value)
            except ValueError:
                status = None

        flight_mode_value = nav_dict.get("flightMode", ShipNavFlightMode.CRUISE.value)
        try:
            flight_mode = ShipNavFlightMode(flight_mode_value)
        except ValueError:
            flight_mode = ShipNavFlightMode.CRUISE

        nav = ShipNav(
            systemSymbol=nav_dict.get("systemSymbol"),
            waypointSymbol=nav_dict.get("waypointSymbol"),
            route=route,
            status=status,
            flightMode=flight_mode,
        )

        engine_dict = d.get("engine", {}) or {}
        engine = None
        if engine_dict:
            engine = ShipEngine(
                symbol=engine_dict.get("symbol"),
                name=engine_dict.get("name"),
                description=engine_dict.get("description"),
                speed=engine_dict.get("speed"),
            )

        fuel_dict = d.get("fuel", {}) or {}
        fuel = ShipFuel(
            current=fuel_dict.get("current", 0),
            capacity=fuel_dict.get("capacity", 0),
        )

        cargo_dict = d.get("cargo", {}) or {}
        cargo = ShipCargo(
            capacity=cargo_dict.get("capacity", 0),
            units=cargo_dict.get("units", 0),
        )

        cooldown_dict = d.get("cooldown", {}) or {}
        cooldown = ShipCooldown(
            totalSeconds=cooldown_dict.get("totalSeconds", 0),
            remainingSeconds=cooldown_dict.get("remainingSeconds", 0),
        )

        return Ship(
            symbol=d.get("symbol"),
            registration=registration,
            nav=nav,
            engine=engine,
            fuel=fuel,
            cargo=cargo,
            cooldown=cooldown,
        )
