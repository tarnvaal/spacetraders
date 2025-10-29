### Flow Examples

This document illustrates example sequences using the low-level helpers in `logic/navigation.py` together with `logic/markets.py` and `logic/navigation_algorithms.py`. No flows are implemented in code; these are reference patterns you can script in `main.py` or elsewhere.

### Mine until full, then sell cargo

Steps:
- Get closest mineable waypoint with `NavigationAlgorithms.find_closest_mineable_waypoint`.
- Call `Navigation.navigate_in_system` to the target.
- Use `Navigation.wait_until_arrival` to block until arrival.
- Optionally try `Markets.refuel_if_available` (if docked and available).
- Loop: `Navigation.extract_at_current_waypoint` and sleep for cooldown until cargo full.
- Choose market with `Markets.find_best_marketplace_for_cargo`.
- Navigate to market and `Navigation.wait_until_arrival`.
- Dock and sell using `Markets.dock_and_sell_all_cargo`.

### Move to nearest marketplace

Steps:
- Determine destination with `Markets.find_nearest_marketplace`.
- `Navigation.navigate_in_system` to waypoint.
- `Navigation.wait_until_arrival`.

### Explore an unvisited marketplace

Steps:
- Pick with `Markets.find_nearest_unvisited_marketplace`.
- `Navigation.navigate_in_system` and `Navigation.wait_until_arrival`.

### Notes

- Keep any policy/looping logic outside of `logic/*` to avoid embedding flows in the core helpers.
- If you need additional algorithms (distance heuristics, selection logic), put them in `logic/navigation_algorithms.py` and keep them pure (no control flow orchestration).
