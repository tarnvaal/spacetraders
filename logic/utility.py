# Utility module for various helper functions.

from datetime import datetime, timezone


# ISO 8601 UTC timestamps with millisecond precision and a trailing Z.
def get_utc_timestamp() -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return timestamp
