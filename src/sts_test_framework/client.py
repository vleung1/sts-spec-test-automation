"""
Minimal HTTP GET client for STS (stdlib ``urllib``): timing, JSON parse, SSL toggle.

``APIResponse`` wraps status, raw body, parsed JSON, and request duration for reporting.
"""
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class APIResponse:
    """Single request outcome: HTTP status, body text, optional parsed JSON, elapsed seconds."""

    def __init__(self, status_code: int, body: str, json_data: dict | list | None, duration: float):
        """Store response fields; ``json_data`` may be None if body is empty or non-JSON."""
        self.status_code = status_code
        self.body = body
        self._json = json_data
        self.duration = duration

    def json(self) -> dict | list | None:
        """Parsed JSON (dict/list) or None."""
        return self._json

    def is_success(self) -> bool:
        """True for 2xx status codes."""
        return 200 <= self.status_code < 300

    def is_not_found(self) -> bool:
        """True when status is 404."""
        return self.status_code == 404

    def is_no_content(self) -> bool:
        """True when status is 204."""
        return self.status_code == 204


class APIClient:
    """Stateful GET client: ``base_url`` + optional SSL verification and timeout."""

    def __init__(self, base_url: str, timeout: int = 60, ssl_verify: bool | None = None):
        """
        Args:
            base_url: e.g. ``https://sts.cancer.gov/v2`` (no trailing slash stored).
            timeout: Socket timeout per request.
            ssl_verify: If None, read ``STS_SSL_VERIFY=false`` to disable cert check.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if ssl_verify is None:
            ssl_verify = os.getenv("STS_SSL_VERIFY", "true").lower() != "false"
        self._ssl_verify = ssl_verify

    def _make_request(self, method: str, path: str, params: dict | None = None) -> APIResponse:
        """Build URL, perform request, return ``APIResponse`` (handles HTTP errors as responses)."""
        url = self.base_url + path + _build_query_string(params)

        request = Request(url)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "STS-Test-Framework-Agent/1.0")

        start = time.perf_counter()
        try:
            import ssl
            if self._ssl_verify:
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8", "replace")
                    status_code = response.getcode()
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urlopen(request, timeout=self.timeout, context=ctx) as response:
                    body = response.read().decode("utf-8", "replace")
                    status_code = response.getcode()

            try:
                json_data = json.loads(body) if body else None
            except json.JSONDecodeError:
                json_data = None
            return APIResponse(status_code, body, json_data, time.perf_counter() - start)

        except HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                body = str(e)
            try:
                json_data = json.loads(body) if body else None
            except json.JSONDecodeError:
                json_data = None
            return APIResponse(e.code, body, json_data, time.perf_counter() - start)
        except (URLError, Exception) as e:
            return APIResponse(0, str(e), None, time.perf_counter() - start)

    def get(self, path: str, params: dict | None = None) -> APIResponse:
        """Make GET request. Path should be relative to base_url (e.g. /models/)."""
        return self._make_request("GET", path, params)


def _build_query_string(params: dict | None) -> str:
    """URL-encode ``params`` into a ``?key=val&...`` suffix (empty string if no params)."""
    if not params:
        return ""
    query_parts = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, list):
            for item in v:
                query_parts.append(f"{k}={quote(str(item), safe='')}")
        else:
            query_parts.append(f"{k}={quote(str(v), safe='')}")
    if not query_parts:
        return ""
    return "?" + "&".join(query_parts)


def full_url(client: APIClient, path: str, params: dict | None = None) -> str:
    """Concatenate ``client.base_url`` + path + query string (for display/debug only)."""
    return client.base_url + path + _build_query_string(params)
