"""HTTP for the model services, with the standard library only.

* Redirects are errors: urllib would otherwise replay ``x-api-key`` / ``Authorization`` to the new address.
* Addresses on this computer (localhost, 127.0.0.1, ::1) bypass any proxy; everything else honours the proxy
  settings (``HTTPS_PROXY``), whichever provider it is.
* TLS verification is never disabled.
* Connecting is limited to :data:`CONNECT_TIMEOUT`; after that ``timeout`` is an *idle* limit (each read).
* Cancelling (Stop) shuts the request's socket as soon as it is connected, so a thread waiting for the answer's
  headers or for the next line of a stream wakes up at once; streams also check the event between lines.
"""

from __future__ import annotations

import http.client as _httpc
import json
import random
import socket
import ssl
import threading
import urllib.error
import urllib.request
from typing import Any, Callable, Iterator, TypeVar
from urllib.parse import urlparse

from .. import __version__

USER_AGENT = f"EDGE/{__version__} (experiment assistant)"
MAX_BODY = 30 * 1024 * 1024
RETRY_STATUS = {408, 429, 500, 502, 503, 504, 529}
RETRY_BASE = 2.0            # seconds; tests make it small
MAX_RETRY_AFTER = 60.0
CONNECT_TIMEOUT = 20.0      # seconds to open the connection (an unreachable address must not hold a job for minutes)
NO_RETRY_TYPES = ("insufficient_quota", "billing_error")     # 429/402 that waiting won't fix
T = TypeVar("T")


class Cancelled(Exception):
    """The person pressed Stop."""


class CancelEvent(threading.Event):
    """A threading.Event that also runs callbacks when set (used to wake a blocked network read)."""

    def __init__(self) -> None:
        super().__init__()
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def on_cancel(self, fn: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            self._callbacks.append(fn)
        if self.is_set():
            _safe(fn)

        def remove() -> None:
            with self._lock:
                if fn in self._callbacks:
                    self._callbacks.remove(fn)
        return remove

    def set(self) -> None:
        super().set()
        with self._lock:
            cbs = list(self._callbacks)
        for fn in cbs:
            _safe(fn)


def _safe(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception:
        pass


class HttpFailure(Exception):
    """A non-2xx answer or a transport failure, with what's needed to explain it."""

    def __init__(self, status: int | None = None, headers: dict[str, str] | None = None, body_text: str = "",
                 reason: str | None = None, url: str = "", timeout: float | None = None):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.body_text = body_text or ""
        try:
            self.body_json: Any = json.loads(self.body_text) if self.body_text.strip()[:1] in ("{", "[") else None
        except ValueError:
            self.body_json = None
        self.reason = reason
        self.url = url
        self.timeout = timeout
        super().__init__(f"HTTP {status}" if status else (reason or "network error"))

    def retry_after(self) -> float | None:
        v = self.headers.get("retry-after")
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None

    def message(self) -> str:
        j = self.body_json
        if isinstance(j, dict):
            e = j.get("error")
            if isinstance(e, dict):
                return str(e.get("message") or "")
            if isinstance(e, str):
                return e
        return self.body_text[:500]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, N802
        raise HttpFailure(code, dict(headers or {}), "", reason="redirect", url=newurl)


def _shutdown(sock: Any) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _hook_connection(conn: Any, cancel: threading.Event | None) -> Any:
    """Bound the connect time, then register the connected socket with the cancel event (Stop wakes a thread
    that is still waiting for the answer's headers, e.g. while a local model loads)."""
    orig = conn.connect
    read_timeout = conn.timeout

    def connect() -> None:
        if cancel is not None and cancel.is_set():
            raise OSError("cancelled")
        limit = CONNECT_TIMEOUT if not isinstance(read_timeout, (int, float)) else min(read_timeout, CONNECT_TIMEOUT)
        conn.timeout = limit
        try:
            orig()
        finally:
            conn.timeout = read_timeout
        sock = conn.sock
        if sock is not None:
            try:
                sock.settimeout(read_timeout if isinstance(read_timeout, (int, float)) else None)
            except OSError:
                pass
            if isinstance(cancel, CancelEvent):
                cancel.on_cancel(lambda: _shutdown(sock))
    conn.connect = connect
    return conn


class _HTTP(urllib.request.HTTPHandler):
    def __init__(self, cancel: threading.Event | None) -> None:
        super().__init__()
        self._cancel = cancel

    def do_open(self, http_class, req, **kw):  # noqa: ANN001, D102
        return super().do_open(lambda host, **a: _hook_connection(http_class(host, **a), self._cancel), req, **kw)


class _HTTPS(urllib.request.HTTPSHandler):
    def __init__(self, cancel: threading.Event | None) -> None:
        super().__init__(context=ssl.create_default_context())
        self._cancel = cancel

    def do_open(self, http_class, req, **kw):  # noqa: ANN001, D102
        return super().do_open(lambda host, **a: _hook_connection(http_class(host, **a), self._cancel), req, **kw)


def _local_address(url: str) -> bool:
    from .config import is_local_host
    try:
        return is_local_host(urlparse(url).hostname)
    except ValueError:
        return False


def _opener(bypass_proxy: bool, cancel: threading.Event | None = None) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [_NoRedirect(),
                           urllib.request.ProxyHandler({}) if bypass_proxy else urllib.request.ProxyHandler(),
                           _HTTP(cancel), _HTTPS(cancel)]
    return urllib.request.build_opener(*handlers)


def _reason(e: BaseException) -> str:
    text = f"{type(e).__name__} {e}".lower()
    inner = getattr(e, "reason", None)
    if isinstance(inner, BaseException):
        text += f" {type(inner).__name__} {inner}".lower()
        e = inner
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in text:
        return "timeout"
    if isinstance(e, ssl.SSLError) or "ssl" in text or "certificate" in text:
        return "tls"
    if isinstance(e, ConnectionRefusedError) or "refused" in text:
        return "connection_refused"
    if isinstance(e, socket.gaierror) or "name or service" in text or "nodename" in text or "getaddrinfo" in text:
        return "dns"
    if isinstance(e, ConnectionResetError) or "reset" in text or "broken pipe" in text or "remote end closed" in text:
        return "reset"
    if "unreachable" in text:
        return "unreachable"
    return "reset"


def _encode(body: Any) -> bytes | None:
    if body is None:
        return None
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_BODY:
        from .errors import AssistantError
        raise AssistantError("request_too_large")
    return data


def _open(method: str, url: str, headers: dict[str, str], body: Any, timeout: float, local: bool,
          cancel: threading.Event | None = None):
    data = _encode(body)
    h = {"User-Agent": USER_AGENT, "Accept": "application/json, text/event-stream, application/x-ndjson"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        return _opener(_local_address(url), cancel).open(req, timeout=timeout)
    except HttpFailure:
        raise
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        raise HttpFailure(e.code, dict(e.headers or {}), text, url=url) from None
    except (urllib.error.URLError, OSError, ValueError, _httpc.HTTPException) as e:
        if cancel is not None and cancel.is_set():
            raise Cancelled() from None
        if isinstance(e, ValueError) and not isinstance(e, ssl.SSLError):
            raise HttpFailure(None, {}, str(e), reason="bad_url", url=url) from None
        raise HttpFailure(None, {}, str(e), reason=_reason(e), url=url, timeout=timeout) from None


def request_json(method: str, url: str, *, headers: dict[str, str] | None = None, body: Any = None,
                 timeout: float = 30.0, local: bool = False,
                 cancel: threading.Event | None = None) -> tuple[int, dict[str, str], Any]:
    """One request with a JSON answer. Raises HttpFailure for non-2xx answers and network failures, Cancelled
    when ``cancel`` is set while it waits."""
    resp = _open(method, url, headers or {}, body, timeout, local, cancel)
    try:
        raw = resp.read()
    except (OSError, socket.timeout, _httpc.HTTPException) as e:
        if cancel is not None and cancel.is_set():
            raise Cancelled() from None
        raise HttpFailure(None, {}, str(e), reason=_reason(e), url=url, timeout=timeout) from None
    finally:
        resp.close()
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text) if text.strip() else None
    except ValueError:
        raise HttpFailure(resp.status, dict(resp.headers or {}), text, reason="bad_json", url=url) from None
    return resp.status, {k.lower(): v for k, v in (resp.headers or {}).items()}, data


def open_stream(url: str, *, headers: dict[str, str] | None = None, body: Any = None, timeout: float = 120.0,
                local: bool = False, first_byte_timeout: float | None = None,
                cancel: threading.Event | None = None) -> "Stream":
    resp = _open("POST", url, headers or {}, body, first_byte_timeout or timeout, local, cancel)
    return Stream(resp, url, timeout, first_byte_timeout)


class Stream:
    """A streaming answer: Server-Sent Events (Anthropic, OpenAI) or one JSON object per line (Ollama)."""

    def __init__(self, resp: Any, url: str, idle: float, first_byte: float | None):
        self.resp = resp
        self.url = url
        self.idle = idle
        self.first_byte = first_byte
        self.status = getattr(resp, "status", 200)
        self.headers = {k.lower(): v for k, v in (getattr(resp, "headers", None) or {}).items()}
        self._closed = False
        self._got_first = False
        self.saw_done = False           # an SSE "data: [DONE]" arrived (OpenAI-compatible streams end with it)

    def _sock(self) -> Any:
        fp = getattr(self.resp, "fp", None)
        raw = getattr(fp, "raw", None)
        return getattr(raw, "_sock", None)

    def abort(self) -> None:
        """Wake a read blocked in another thread (Stop): shut the socket, leave the closing to the reader."""
        sock = self._sock()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.abort()
        try:
            self.resp.close()
        except Exception:
            pass

    def _lines(self, cancel: threading.Event) -> Iterator[str]:
        remove = cancel.on_cancel(self.abort) if isinstance(cancel, CancelEvent) else (lambda: None)
        try:
            while True:
                if cancel.is_set():
                    raise Cancelled()
                try:
                    line = self.resp.readline()
                except (OSError, socket.timeout, ValueError, AttributeError) as e:
                    if cancel.is_set():
                        raise Cancelled() from None
                    reason = _reason(e) if not isinstance(e, ValueError) else "reset"
                    raise HttpFailure(None, {}, str(e), reason=reason, url=self.url,
                                      timeout=self.idle if self._got_first else (self.first_byte or self.idle)) from None
                if cancel.is_set():
                    raise Cancelled()
                if not self._got_first:
                    self._got_first = True
                    if self.first_byte and self.first_byte != self.idle:
                        sock = self._sock()
                        if sock is not None:
                            try:
                                sock.settimeout(self.idle)
                            except OSError:
                                pass
                if not line:
                    return
                yield line.decode("utf-8", errors="replace").rstrip("\r\n")
        finally:
            remove()
            self.close()

    def iter_sse(self, cancel: threading.Event) -> Iterator[tuple[str, str]]:
        """(event, data) per Server-Sent Event; ``data: [DONE]`` ends the stream."""
        event, data = "", []
        for line in self._lines(cancel):
            if line == "":
                if data or event:
                    payload = "\n".join(data)
                    if payload.strip() == "[DONE]":
                        self.saw_done = True
                        return
                    yield event or "message", payload
                event, data = "", []
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
        if data:
            payload = "\n".join(data)
            if payload.strip() != "[DONE]":
                yield event or "message", payload
            else:
                self.saw_done = True

    def iter_ndjson(self, cancel: threading.Event) -> Iterator[dict]:
        for line in self._lines(cancel):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                raise HttpFailure(self.status, {}, line[:500], reason="bad_json", url=self.url) from None
            if isinstance(obj, dict):
                yield obj

    def read_json(self, cancel: threading.Event) -> Any:
        text = "\n".join(self._lines(cancel))
        try:
            return json.loads(text)
        except ValueError:
            raise HttpFailure(self.status, {}, text[:500], reason="bad_json", url=self.url) from None


def with_retries(fn: Callable[[], T], *, on_wait: Callable[[str, float], None], cancel: threading.Event,
                 attempts: int = 3, local: bool = False, label: str = "The service") -> T:
    """Call ``fn``; on a retryable failure (before any answer arrived) wait and try again."""
    n = 0
    while True:
        try:
            return fn()
        except HttpFailure as f:
            n += 1
            retryable = (f.status in RETRY_STATUS) or (not local and f.reason in ("reset", "connection_refused"))
            if not retryable or n >= attempts or f.reason == "redirect" or _no_credit(f):
                raise
            ra = f.retry_after()
            if ra is not None and ra > MAX_RETRY_AFTER:
                raise
            delay = ra if ra is not None else RETRY_BASE * (2 ** (n - 1)) * random.uniform(0.8, 1.2)
            what = "busy" if f.status in (529, 503, 500, 502, 504) else (
                "limiting requests" if f.status == 429 else "not answering")
            who = label[:1].upper() + label[1:]
            on_wait(f"{who} is {what} — trying again in {max(1, round(delay))} s", delay)
            if cancel.wait(max(0.0, delay)):
                raise Cancelled() from None


def _no_credit(f: HttpFailure) -> bool:
    """An empty account (OpenAI answers 429 insufficient_quota): retrying only delays the real message."""
    j = f.body_json
    e = j.get("error") if isinstance(j, dict) else None
    if isinstance(e, dict) and (str(e.get("type") or "") in NO_RETRY_TYPES or str(e.get("code") or "") in NO_RETRY_TYPES):
        return True
    low = f.body_text.lower()
    return "insufficient_quota" in low or "credit balance" in low


def sleep_or_cancel(seconds: float, cancel: threading.Event) -> None:
    if cancel.wait(seconds):
        raise Cancelled()


__all__ = ["Cancelled", "CancelEvent", "HttpFailure", "Stream", "request_json", "open_stream", "with_retries",
           "USER_AGENT"]
