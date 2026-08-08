"""Outbound HTTP with a scheme/host allowlist and a size cap.

Deferred at M01 close and closed here (security review MEDIUM-3/MEDIUM-4).

Ingestion's fetch targets are not constants. Both APIs answer with the *next*
URL to fetch — `next_page_url` in the FR document list, `full_text_xml_url`
in a document's JSON — and the previous code passed those straight into
`urllib.request.urlopen`. So the set of hosts this Lambda talks to was
decided by the response body, not by us. Combined with urllib following
redirects by default, that is a server-side request forgery primitive:

  - `http://169.254.169.254/latest/meta-data/iam/security-credentials/`
    reaches the instance metadata endpoint from inside the execution role.
  - `file:///proc/self/environ` — urllib handles `file:` — reads the
    environment, which holds the table and bucket names.
  - any internal address reachable from the Lambda's network position.

Nothing in M01 required a compromised federalregister.gov for this to matter:
an on-path attacker or a DNS answer is enough, and the redirect path means an
allowlisted first hop can still land anywhere.

Two properties are enforced here, and both have to hold on *every* hop:
  1. scheme in ALLOWED_FETCH_SCHEMES and host in ALLOWED_FETCH_HOSTS
  2. the body stops at MAX_FETCH_BYTES

Redirects are checked rather than disabled, because the FR API does legitimately
redirect between its own hosts. `_AllowlistRedirectHandler` re-validates the
target of each hop, so a 302 off the allowlist raises instead of following.
"""
import json
import urllib.parse
import urllib.request

from shared import config


class FetchNotAllowedError(ValueError):
    """A URL failed the allowlist, on the initial request or on a redirect."""


class ResponseTooLargeError(ValueError):
    """The response body exceeded MAX_FETCH_BYTES."""


def check_url(url: str) -> str:
    """Raise unless `url` is https and on the host allowlist.

    Compares the parsed hostname, never a substring: `startswith` on the URL
    would accept `https://www.ecfr.gov.attacker.example/`, and a naive `in`
    check would accept `https://attacker.example/?x=www.ecfr.gov`. Userinfo is
    the same trap — `https://www.ecfr.gov@attacker.example/` has hostname
    `attacker.example`, which is exactly what `.hostname` returns.
    """
    if not isinstance(url, str) or not url:
        raise FetchNotAllowedError(f"not a URL: {url!r}")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in config.ALLOWED_FETCH_SCHEMES:
        raise FetchNotAllowedError(
            f"scheme {parts.scheme!r} not allowed (need "
            f"{sorted(config.ALLOWED_FETCH_SCHEMES)}): {url!r}")
    host = (parts.hostname or "").lower()
    if host not in config.ALLOWED_FETCH_HOSTS:
        raise FetchNotAllowedError(
            f"host {host!r} not on the fetch allowlist "
            f"{sorted(config.ALLOWED_FETCH_HOSTS)}: {url!r}")
    return url


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-check the allowlist on every redirect hop.

    Returning None from the parent would silently stop following and hand back
    the 3xx body; raising is what makes an off-allowlist redirect a failed
    message instead of a document parsed from a redirect page.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> urllib.request.OpenerDirector:
    """An opener carrying ONLY https, so no other scheme has a handler at all.

    `build_opener()` was wrong here and the test caught it: it *adds* to the
    default handler set rather than replacing it, so FileHandler, FTPHandler
    and plain HTTPHandler all remained installed. The scheme check in
    `check_url` still blocked them, so nothing was exploitable — but the
    defence-in-depth layer this was supposed to provide did not exist, and the
    comment claimed it did.

    Constructing the director explicitly is what actually removes them.
    ProxyHandler is also left out on purpose: it would let `https_proxy` in the
    environment redirect every fetch to a host the allowlist never sees.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.HTTPSHandler(),
        _AllowlistRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.HTTPDefaultErrorHandler(),
        # Required, or an unhandled scheme makes `open()` return None rather
        # than raise — which surfaces three lines later as an AttributeError on
        # a None context manager. UnknownHandler turns it into URLError, so a
        # scheme that somehow reaches here fails legibly.
        urllib.request.UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


_opener = _build_opener()


def get_bytes(url: str, *, timeout: int = 60,
              max_bytes: int | None = None) -> bytes:
    """Fetch `url` after allowlist checks, reading at most max_bytes.

    Reads one byte past the cap and raises if it arrives, so an oversized body
    is refused rather than silently truncated into a half-parsed document. A
    Content-Length header is not trusted for this — it is attacker-supplied
    and may understate the stream.
    """
    check_url(url)
    limit = config.MAX_FETCH_BYTES if max_bytes is None else max_bytes
    req = urllib.request.Request(
        url, headers={"User-Agent": "regdelta-ingest/0.1"})
    with _opener.open(req, timeout=timeout) as r:
        body = r.read(limit + 1)
    if len(body) > limit:
        raise ResponseTooLargeError(
            f"response exceeded {limit} bytes: {url!r}")
    return body


def get_json(url: str, *, timeout: int = 60,
             max_bytes: int | None = None) -> dict:
    return json.loads(get_bytes(url, timeout=timeout, max_bytes=max_bytes))
