from datetime import datetime, timezone


def parse_iso_utc(ts: str) -> datetime:
    """Parse ISO-8601 UTC timestamp (with trailing 'Z') to an aware datetime.

    Falls back to current UTC time if the input is falsy.
    """
    if not ts:
        return datetime.now(timezone.utc)
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)
