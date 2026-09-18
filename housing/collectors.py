"""Small, conservative collectors for public property-manager listing pages.

The adapters deliberately parse only listing-card fields that share one card's
grain.  Network collection is a separate, bounded operation: robots.txt plus
at most one configured listings page, with no pagination, detail-page crawl,
authentication, or block evasion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
import re
from typing import Callable, Iterable, Mapping
from urllib import error, request, robotparser
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit


USER_AGENT = "housing-decision-lab/0.1 (local personal-use collector)"
MAX_PAGE_BYTES = 5 * 1024 * 1024
SUPPORTED_ADAPTERS = ("appfolio", "managebuilding", "json")
PARSER_VERSIONS = {
    "appfolio": "appfolio-html-v1",
    "managebuilding": "managebuilding-html-v1",
    "json": "json-feed-v1",
}


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_Node | str"] = field(default_factory=list)
    parent: "_Node | None" = None


class _TreeParser(HTMLParser):
    """A minimal HTML tree sufficient for the two server-rendered card shapes."""

    _VOID = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        node = _Node(
            tag,
            {name.lower(): value or "" for name, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)
        if tag not in self._VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def _clean(value: str) -> str:
    return " ".join(value.split())


def _text(node: _Node | None) -> str:
    if node is None:
        return ""
    chunks: list[str] = []

    def visit(item: _Node | str) -> None:
        if isinstance(item, str):
            chunks.append(item)
        else:
            for child in item.children:
                visit(child)

    visit(node)
    return _clean(" ".join(chunks))


def _nodes(root: _Node, predicate: Callable[[_Node], bool]) -> Iterable[_Node]:
    for child in root.children:
        if not isinstance(child, _Node):
            continue
        if predicate(child):
            yield child
        yield from _nodes(child, predicate)


def _classes(node: _Node) -> set[str]:
    return set(node.attrs.get("class", "").split())


def _has_class(name: str) -> Callable[[_Node], bool]:
    return lambda node: name in _classes(node)


def _first(root: _Node, predicate: Callable[[_Node], bool]) -> _Node | None:
    return next(iter(_nodes(root, predicate)), None)


def _document(html: str | bytes) -> _Node:
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    parser = _TreeParser()
    parser.feed(html)
    parser.close()
    return parser.root


def _canonical_url(base_url: str, href: str) -> str:
    parts = urlsplit(urljoin(base_url, href))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def _number(value: str | None) -> int | float | None:
    if value is None:
        return None
    value = value.strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _money(value: str) -> int | float | None:
    # A range, deposit, or other multi-number string is not a single monthly rent.
    amounts = re.findall(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)", value)
    if len(amounts) != 1:
        return None
    parsed = float(amounts[0].replace(",", ""))
    if parsed <= 0:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _bed_bath(value: str) -> tuple[int | float | None, int | float | None]:
    studio = bool(re.search(r"\bstudio\b", value, re.I))
    bed_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:bd|bed(?:room)?s?)\b", value, re.I)
    bath_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ba|bath(?:room)?s?)\b", value, re.I)
    beds = 0 if studio else _number(bed_match.group(1) if bed_match else None)
    baths = _number(bath_match.group(1) if bath_match else None)
    return beds, baths


def _listing(
    *,
    source: str,
    provider_id: str,
    url: str | None,
    title: str | None,
    address: str | None,
    unit: str | None,
    grain: str,
    rent: int | float | None,
    bedrooms: int | float | None,
    bathrooms: int | float | None,
    observed_at: str,
    notes: str | None = None,
    total_monthly_cost: int | float | None = None,
) -> dict:
    row = {
        "id": f"{source}:{provider_id}",
        "source": source,
        "source_id": provider_id,
        "url": url,
        "title": title or None,
        "address": address or None,
        "unit": unit,
        "grain": grain,
        "rent": rent,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "lat": None,
        "lon": None,
        "observed_at": observed_at,
        "historical": False,
    }
    if notes:
        row["notes"] = notes
    if total_monthly_cost is not None:
        row["total_monthly_cost"] = total_monthly_cost
    return row


def _parse_appfolio(root: _Node, base_url: str, source: str, observed_at: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for card in _nodes(root, _has_class("listing-item")):
        detail = _first(
            card,
            lambda node: node.tag == "a"
            and re.search(r"/listings/detail/[^/?#]+", node.attrs.get("href", ""), re.I) is not None,
        )
        if detail is None:
            continue
        match = re.search(r"/listings/detail/([^/?#]+)", detail.attrs["href"], re.I)
        if not match:
            continue
        provider_id = unquote(match.group(1))
        if provider_id in seen:
            continue
        seen.add(provider_id)

        facts: dict[str, str] = {}
        for term in _nodes(card, lambda node: node.tag == "dt"):
            if term.parent is None:
                continue
            siblings = term.parent.children
            try:
                term_index = siblings.index(term)
            except ValueError:
                continue
            value_node = next(
                (item for item in siblings[term_index + 1 :] if isinstance(item, _Node) and item.tag == "dd"),
                None,
            )
            if value_node is not None:
                facts[_text(term).upper()] = _text(value_node)

        title_node = _first(card, _has_class("listing-item__title"))
        title_link = _first(title_node, lambda node: node.tag == "a") if title_node else None
        title = _text(title_link or title_node)
        address = _text(_first(card, _has_class("js-listing-address")))
        if not address:
            image = _first(card, lambda node: node.tag == "img" and bool(node.attrs.get("alt")))
            address = _clean(image.attrs.get("alt", "")) if image else ""

        bed_text = facts.get("BED / BATH", "")
        bedrooms, bathrooms = _bed_bath(bed_text)
        # ``rent`` is base monthly rent. Mandatory fees may be included in the
        # provider's separate total, so the two values must never be substituted.
        rent = _money(facts.get("RENT", ""))
        total_monthly_cost = _money(facts.get("TOTAL MONTHLY PRICE", ""))
        available = facts.get("AVAILABLE", "")
        notes = f"Availability reported by source: {available}" if available else None
        if total_monthly_cost is not None and rent is None:
            notes = ((notes + "; ") if notes else "") + "Base rent not reported; total monthly cost retained separately"

        rows.append(
            _listing(
                source=source,
                provider_id=provider_id,
                url=_canonical_url(base_url, detail.attrs["href"]),
                title=title,
                address=address,
                unit=None,
                grain="unit",
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                observed_at=observed_at,
                notes=notes,
                total_monthly_cost=total_monthly_cost,
            )
        )
    return rows


def _json_scalar(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"JSON listing {field_name} must be a string or null")
    return value.strip() or None


def _json_number(value: object, field_name: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"JSON listing {field_name} must be a number or null")
    parsed = float(value)
    if not (-float("inf") < parsed < float("inf")):
        raise ValueError(f"JSON listing {field_name} must be finite")
    if field_name not in ("lat", "lon") and parsed < 0:
        raise ValueError(f"JSON listing {field_name} cannot be negative")
    return int(parsed) if parsed.is_integer() else parsed


def _parse_json(payload: str | bytes, base_url: str, source: str, observed_at: str) -> list[dict]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="strict")
    document = json.loads(payload)
    records = document.get("listings") if isinstance(document, dict) else document
    if not isinstance(records, list):
        raise ValueError('JSON feed must be an array or an object with a "listings" array')

    rows: list[dict] = []
    seen: set[str] = set()
    valid_grains = {"unit", "floorplan", "property", "unknown"}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"JSON listing at index {index} must be an object")
        raw_provider_id = record.get("source_id") or record.get("id")
        provider_id = str(raw_provider_id).strip() if raw_provider_id is not None else ""
        if not provider_id:
            raise ValueError(f"JSON listing at index {index} needs source_id or id")
        if provider_id in seen:
            raise ValueError(f"duplicate JSON source_id: {provider_id}")
        seen.add(provider_id)

        grain = record.get("grain") or "unknown"
        if grain not in valid_grains:
            raise ValueError(f"invalid JSON listing grain: {grain!r}")
        raw_url = _json_scalar(record.get("url"), "url")
        exact_url = _canonical_url(base_url, raw_url) if raw_url else None
        if exact_url and urlsplit(exact_url).scheme not in ("http", "https"):
            raise ValueError("JSON listing URL must use HTTP(S)")
        lat = _json_number(record.get("lat"), "lat")
        lon = _json_number(record.get("lon"), "lon")
        if (lat is None) != (lon is None):
            raise ValueError("JSON listing must provide both lat and lon or neither")
        if lat is not None and not -90 <= lat <= 90:
            raise ValueError("JSON listing latitude is out of range")
        if lon is not None and not -180 <= lon <= 180:
            raise ValueError("JSON listing longitude is out of range")
        historical = record.get("historical", False)
        if not isinstance(historical, bool):
            raise ValueError("JSON listing historical must be boolean")

        row = _listing(
            source=source,
            provider_id=provider_id,
            url=exact_url,
            title=_json_scalar(record.get("title"), "title"),
            address=_json_scalar(record.get("address"), "address"),
            unit=_json_scalar(record.get("unit"), "unit"),
            grain=grain,
            rent=_json_number(record.get("rent"), "rent"),
            bedrooms=_json_number(record.get("bedrooms"), "bedrooms"),
            bathrooms=_json_number(record.get("bathrooms"), "bathrooms"),
            observed_at=observed_at,
            notes=_json_scalar(record.get("notes"), "notes"),
            total_monthly_cost=_json_number(record.get("total_monthly_cost"), "total_monthly_cost"),
        )
        row["lat"] = lat
        row["lon"] = lon
        row["historical"] = historical
        rows.append(row)
    return rows


def _split_managebuilding_title(title: str, locality: str) -> tuple[str, str | None]:
    if " - " in title:
        street, unit = title.rsplit(" - ", 1)
        if street.strip() and unit.strip():
            return _clean(", ".join(part for part in (street, locality) if part)), _clean(unit)
    return _clean(", ".join(part for part in (title, locality) if part)), None


def _parse_managebuilding(root: _Node, base_url: str, source: str, observed_at: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for card in _nodes(
        root,
        lambda node: node.tag == "a"
        and "featured-listing" in _classes(node)
        and re.search(r"/resident/public/rentals/[^/?#]+", node.attrs.get("href", ""), re.I) is not None,
    ):
        match = re.search(r"/resident/public/rentals/([^/?#]+)", card.attrs["href"], re.I)
        if not match:
            continue
        provider_id = unquote(match.group(1))
        if provider_id in seen:
            continue
        seen.add(provider_id)

        title = _text(_first(card, _has_class("featured-listing__title")))
        locality = _text(_first(card, _has_class("featured-listing__address")))
        address, unit = _split_managebuilding_title(title, locality)
        feature_text = _text(_first(card, _has_class("featured-listing__features")))
        text_beds, text_baths = _bed_bath(feature_text)
        bedrooms = _number(card.attrs.get("data-bedrooms"))
        bathrooms = _number(card.attrs.get("data-bathrooms"))
        if bedrooms is None:
            bedrooms = text_beds
        if bathrooms is None:
            bathrooms = text_baths
        rent = _number(card.attrs.get("data-rent"))
        if rent is None or rent <= 0:
            rent = _money(_text(_first(card, _has_class("featured-listing__price"))))
        property_type = card.attrs.get("data-type", "")
        grain = "unit" if unit else ("property" if property_type.lower() == "singlefamily" else "unknown")
        available = _text(_first(card, _has_class("featured-listing__availability")))
        notes = f"Availability reported by source: {available}" if available else None

        rows.append(
            _listing(
                source=source,
                provider_id=provider_id,
                url=_canonical_url(base_url, card.attrs["href"]),
                title=title,
                address=address,
                unit=unit,
                grain=grain,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                observed_at=observed_at,
                notes=notes,
            )
        )
    return rows


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse(
    adapter: str,
    html: str | bytes,
    base_url: str,
    source_id: str,
    observed_at: str | None = None,
) -> list[dict]:
    """Parse one AppFolio, ManageBuilding, or authorized JSON feed without I/O.

    Unknown values remain ``None``.  An empty list alone does not mean the
    source is empty; ``collect_source`` separately requires an explicit empty
    message from a recognized source page.
    """

    adapter = adapter.strip().lower()
    if adapter not in SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported collector adapter: {adapter!r}")
    if not source_id or not source_id.strip():
        raise ValueError("source_id is required")
    captured_at = observed_at or _utc_now()
    source_bytes = html if isinstance(html, bytes) else html.encode("utf-8")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if adapter == "json":
        rows = _parse_json(html, base_url, source_id.strip(), captured_at)
    else:
        root = _document(html)
        if adapter == "appfolio":
            rows = _parse_appfolio(root, base_url, source_id.strip(), captured_at)
        else:
            rows = _parse_managebuilding(root, base_url, source_id.strip(), captured_at)
    for row in rows:
        row["parser_version"] = PARSER_VERSIONS[adapter]
        row["source_content_sha256"] = source_hash
    return rows


@dataclass(frozen=True)
class _Fetch:
    status: int
    url: str
    body: bytes
    content_type: str
    error: str | None = None


class _NoRedirect(request.HTTPRedirectHandler):
    """Keep redirects from silently spending requests outside the hard bound."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _fetch_url(url: str, timeout: int, *, accept: str) -> _Fetch:
    req = request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with request.build_opener(_NoRedirect()).open(req, timeout=timeout) as response:
            body = response.read(MAX_PAGE_BYTES + 1)
            if len(body) > MAX_PAGE_BYTES:
                return _Fetch(response.status, response.geturl(), b"", "", "response exceeded 5 MiB limit")
            return _Fetch(
                response.status,
                response.geturl(),
                body,
                response.headers.get_content_type(),
            )
    except error.HTTPError as exc:
        body = exc.read(MAX_PAGE_BYTES + 1)
        content_type = exc.headers.get_content_type() if exc.headers else ""
        detail = f"HTTP {exc.code}"
        if 300 <= exc.code < 400:
            detail += "; redirect not followed"
        return _Fetch(exc.code, exc.geturl(), body[:MAX_PAGE_BYTES], content_type, detail)
    except (error.URLError, TimeoutError, OSError) as exc:
        return _Fetch(0, url, b"", "", f"{type(exc).__name__}: {exc}")


def _robots_url(page_url: str) -> str:
    parts = urlsplit(page_url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


def _robots_permission(page_url: str, timeout: int) -> tuple[bool, str, int]:
    robots_url = _robots_url(page_url)
    result = _fetch_url(robots_url, timeout, accept="text/plain,*/*;q=0.1")
    if urlsplit(result.url).netloc.lower() != urlsplit(page_url).netloc.lower():
        return False, "robots.txt redirected to a different host; permission not assumed", 1
    if result.status in (404, 410):
        return True, f"robots.txt absent (HTTP {result.status})", 1
    if result.status != 200:
        detail = result.error or f"HTTP {result.status}"
        return False, f"robots.txt unavailable ({detail}); permission not assumed", 1
    parser = robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(result.body.decode("utf-8", errors="replace").splitlines())
    if not parser.can_fetch(USER_AGENT, page_url):
        return False, "robots.txt disallows this listings URL", 1
    return True, "robots.txt allows this collector", 1


def _blocked_page(html: str) -> bool:
    lowered = html.lower()
    markers = (
        "access denied",
        "attention required! | cloudflare",
        "cf-chl-",
        "captcha",
        "verify you are human",
        "unusual traffic",
    )
    return any(marker in lowered for marker in markers)


def _explicit_empty(adapter: str, html: str) -> bool:
    if adapter == "json":
        try:
            document = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return False
        records = document.get("listings") if isinstance(document, dict) else document
        return isinstance(records, list) and not records
    lowered = _clean(html).lower()
    if adapter == "managebuilding":
        return (
            "id=\"rentals-container\"" in lowered or "id='rentals-container'" in lowered
        ) and "there are no available rentals at this time" in lowered
    has_shell = "js-listings-container" in lowered or "id=\"result_container\"" in lowered
    messages = (
        "there are no available listings at this time",
        "no available listings were found",
        "no listings match your search",
    )
    return has_shell and any(message in lowered for message in messages)


def _pagination_present(html: str) -> bool:
    return bool(
        re.search(r"\brel\s*=\s*['\"]next['\"]", html, re.I)
        or re.search(r"class\s*=\s*['\"][^'\"]*\bpagination\b", html, re.I)
        or re.search(r"[?&]page=\d+", html, re.I)
    )


def _json_pagination_present(payload: str) -> bool:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError:
        return False
    return isinstance(document, dict) and bool(
        document.get("next") or document.get("next_url") or document.get("has_more") is True
    )


def _result(status: str, message: str, requests: int, listings: list[dict] | None = None, *, partial: bool = False) -> dict:
    return {
        "status": status,
        "listings": listings or [],
        "message": message,
        "requests": requests,
        "partial": partial,
    }


def collect_source(source: Mapping[str, object], *, timeout: int = 20) -> dict:
    """Fetch and parse one configured source with a two-request hard bound.

    The bound is one robots.txt request and one listings-page request.  Source
    configuration must explicitly enable collection and record a non-empty
    permission note.  Pagination is detected but never followed.
    """

    source_id = str(source.get("id", "")).strip()
    adapter = str(source.get("adapter", "")).strip().lower()
    page_url = str(source.get("url", "")).strip()
    permission_note = str(source.get("permission_note", "")).strip()
    if not source_id:
        return _result("error", "source id is required", 0)
    if adapter not in SUPPORTED_ADAPTERS:
        return _result("error", f"unsupported adapter {adapter!r}", 0)
    if source.get("enabled") is not True:
        return _result("error", "source is disabled; no network request made", 0)
    if not permission_note:
        return _result("error", "permission_note is required; no network request made", 0)
    parts = urlsplit(page_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return _result("error", "source URL must be an absolute HTTP(S) URL", 0)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return _result("error", "timeout must be positive", 0)

    allowed, robots_message, requests_made = _robots_permission(page_url, timeout)
    if not allowed:
        return _result("blocked", robots_message, requests_made)

    accept = "application/json,application/*+json" if adapter == "json" else "text/html,application/xhtml+xml"
    fetched = _fetch_url(page_url, timeout, accept=accept)
    requests_made += 1
    if urlsplit(fetched.url).netloc.lower() != parts.netloc.lower():
        return _result(
            "blocked",
            "listings request redirected to a different host whose robots policy was not checked",
            requests_made,
        )
    if fetched.status in (401, 403, 429):
        return _result("blocked", f"listings request blocked (HTTP {fetched.status}); {robots_message}", requests_made)
    if fetched.status != 200:
        detail = fetched.error or f"HTTP {fetched.status}"
        return _result("error", f"listings request failed ({detail}); {robots_message}", requests_made)
    if fetched.error:
        return _result("error", f"listings request failed ({fetched.error}); {robots_message}", requests_made)
    json_content = fetched.content_type in ("application/json", "text/json") or fetched.content_type.endswith("+json")
    html_content = fetched.content_type in ("text/html", "application/xhtml+xml", "")
    if (adapter == "json" and not json_content) or (adapter != "json" and not html_content):
        return _result("error", f"unexpected content type {fetched.content_type!r}", requests_made)

    html = fetched.body.decode("utf-8", errors="replace")
    if adapter != "json" and _blocked_page(html):
        return _result("blocked", "response is a block or human-verification page; no bypass attempted", requests_made)
    try:
        listings = parse(adapter, fetched.body, fetched.url, source_id, observed_at=_utc_now())
    except Exception as exc:
        return _result("error", f"parser failed: {type(exc).__name__}: {exc}", requests_made)
    if listings:
        partial = _json_pagination_present(html) if adapter == "json" else _pagination_present(html)
        noun = "record" if adapter == "json" else "card"
        message = f"Parsed {len(listings)} listing {noun}(s) from one page; {robots_message}."
        if partial:
            message += " Partial result: pagination is present and unhandled."
        return _result("success", message, requests_made, listings, partial=partial)
    if _explicit_empty(adapter, html):
        return _result("empty", f"Recognized source page explicitly reports no available rentals; {robots_message}.", requests_made)
    return _result(
        "error",
        "No recognized listing cards or explicit empty-state evidence; source markup may have changed.",
        requests_made,
    )


__all__ = ["PARSER_VERSIONS", "SUPPORTED_ADAPTERS", "collect_source", "parse"]
