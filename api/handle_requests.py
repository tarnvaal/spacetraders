import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from requests_ratelimiter import LimiterSession, LimiterAdapter
from pyrate_limiter import Limiter, RequestRate, Duration, MemoryListBucket


limiter = Limiter(
    RequestRate(2, Duration.SECOND),
    RequestRate(30, Duration.MINUTE),
    bucket_class=MemoryListBucket,
)

session = LimiterSession(limiter=limiter, per_host=False)

retry = Retry(
    total=6,                        
    connect=3, read=3, status=6,    
    backoff_factor=1.2,            
    status_forcelist=[429, 500, 502, 503, 504],
    respect_retry_after_header=True,
    raise_on_status=False,
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)
session.mount("http://", adapter)

def _sleep_with_jitter(seconds: float):
    time.sleep(seconds * (0.9 + 0.2 * (time.time() % 1)))

def _handle_spacetraders_429(resp):
    """
    If SpaceTraders returns its own 429 (with x-ratelimit-*), wait until reset.
    Otherwise, fall back to generic Retry behavior already configured.
    """
    if resp is None or resp.status_code != 429:
        return False

    h = resp.headers
    if "x-ratelimit-limit" not in h:
        return False

    reset_raw = h.get("x-ratelimit-reset")
    if reset_raw:
        try:
            reset_val = float(reset_raw)
            now = time.time()
            wait_s = reset_val - now if reset_val > 1e10 else reset_val
            wait_s = max(0.0, min(wait_s, 60.0)) 
            if wait_s > 0:
                _sleep_with_jitter(wait_s)
                return True
        except Exception:
            pass
    _sleep_with_jitter(2.0)
    return True


def spacetraders_get(url: str, **kwargs) -> requests.Response:
    """
    GET wrapper:
      - obeys local rate limit
      - retries 429/5xx
      - if a SpaceTraders 429 occurs, sleeps until reset using response headers
    """
    resp = session.get(url, **kwargs)
    if resp.status_code == 429 and _handle_spacetraders_429(resp):
        resp = session.get(url, **kwargs)
    elif resp.status_code == 502:
        _sleep_with_jitter(3.0)
    return resp
