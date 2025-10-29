"""
HTTP request handler with rate limiting, retry logic, and SpaceTraders-specific error handling.
Implements intelligent backoff for 429 (rate limit) and 5xx (server) errors.
"""
import time
import sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests_ratelimiter import LimiterSession, LimiterAdapter
from pyrate_limiter import Limiter, RequestRate, Duration, MemoryListBucket

class RequestHandler:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.limiter = Limiter(
            RequestRate(2, Duration.SECOND),
            RequestRate(30, Duration.MINUTE),
            bucket_class=MemoryListBucket,
        )
        self.session = LimiterSession(limiter=self.limiter, per_host=False)
        self.retry = Retry(
            total=6,                        
            connect=3, read=3, status=6,    
            backoff_factor=1.2,            
            status_forcelist=[429, 500, 502, 503, 504],
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.adapter = HTTPAdapter(max_retries=self.retry)
        self.session.mount("https://", self.adapter)
        self.session.mount("http://", self.adapter)

    def get(self, url: str, **kwargs):
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.session.post(url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.session.put(url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.session.delete(url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self.session.patch(url, **kwargs)

    def head(self, url: str, **kwargs):
        return self.session.head(url, **kwargs)

    def options(self, url: str, **kwargs):
        return self.session.options(url, **kwargs)

    def _sleep_with_jitter(self, seconds: float):
        time.sleep(seconds * (0.9 + 0.2 * (time.time() % 1)))

    def _abort_on_token_reset_mismatch(self, resp):
        """
        Detect SpaceTraders error code 4113 (token reset_date mismatch) and exit.
        """
        try:
            payload = resp.json()
        except Exception:
            return
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict) and err.get("code") == 4113:
            code = err.get("code")
            message = err.get("message")
            print(f"{code}: {message}", file=sys.stderr, flush=True)
            raise SystemExit(1)

    def _handle_spacetraders_429(self, resp):
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
                    self._sleep_with_jitter(wait_s)
                    return True
            except Exception:
                pass
        self._sleep_with_jitter(2.0)
        return True

    def spacetraders_get(self, url: str, **kwargs) -> requests.Response:
        """
        GET wrapper:
          - obeys local rate limit
          - retries 429/5xx
          - if a SpaceTraders 429 occurs, sleeps until reset using response headers
        """
        resp = self.session.get(url, **kwargs)
        self._abort_on_token_reset_mismatch(resp)
        if resp.status_code == 429 and self._handle_spacetraders_429(resp):
            resp = self.session.get(url, **kwargs)
            self._abort_on_token_reset_mismatch(resp)
        elif resp.status_code == 502:
            self._sleep_with_jitter(3.0)
        return resp

    def auth_headers(self, agent_key: str) -> dict:
        return {"Authorization": f"Bearer {agent_key}"}

    def get_json(self, path: str, agent_key: str, params: dict | None = None):
        """
        JSON GET helper using rate-limited session + retries.
        path: path relative to BASE_URL (no leading slash)
        returns parsed JSON payload (dict or list typically)
        """
        url = f"{self.base_url}/{path}"
        resp = self.spacetraders_get(url, headers=self.auth_headers(agent_key), params=params)
        return resp.json()

    def post_json(self, path: str, agent_key: str, json: dict | None = None):
        """
        JSON POST helper with SpaceTraders-aware retry/backoff behavior.
        """
        url = f"{self.base_url}/{path}"
        resp = self.session.post(url, headers=self.auth_headers(agent_key), json=json)
        self._abort_on_token_reset_mismatch(resp)
        if resp.status_code == 429 and self._handle_spacetraders_429(resp):
            resp = self.session.post(url, headers=self.auth_headers(agent_key), json=json)
            self._abort_on_token_reset_mismatch(resp)
        elif resp.status_code == 502:
            self._sleep_with_jitter(3.0)
        return resp.json()

    def patch_json(self, path: str, agent_key: str, json: dict | None = None):
        """
        JSON PATCH helper with SpaceTraders-aware retry/backoff behavior.
        """
        url = f"{self.base_url}/{path}"
        resp = self.session.patch(url, headers=self.auth_headers(agent_key), json=json)
        self._abort_on_token_reset_mismatch(resp)
        if resp.status_code == 429 and self._handle_spacetraders_429(resp):
            resp = self.session.patch(url, headers=self.auth_headers(agent_key), json=json)
            self._abort_on_token_reset_mismatch(resp)
        elif resp.status_code == 502:
            self._sleep_with_jitter(3.0)
        return resp.json()