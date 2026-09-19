"""Bounded collectors for public rental result pages and normalized feeds.

Adapters keep facts at the result-card grain.  Collection checks robots.txt,
stays on one host, honors per-source page/listing/request bounds, and never
logs in, solves challenges, or follows listing detail pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import importlib
import json
import re
from typing import Any, Callable, Iterable, Mapping
from urllib import error, request, robotparser
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit


USER_AGENT = "goldblum/0.1 (local personal-use collector)"
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_PAGES = 10
MAX_LISTINGS = 5_000
MAX_REQUESTS = 20
PARSABLE_ADAPTERS = ("appfolio", "managebuilding", "showmojo", "craigslist", "sabbaticalhomes", "json")
SUPPORTED_ADAPTERS = PARSABLE_ADAPTERS + ("homeharvest", "assisted")
PARSER_VERSIONS = {
    "appfolio": "appfolio-html-v2",
    "managebuilding": "managebuilding-html-v2",
    "showmojo": "showmojo-gallery-html-v1",
    "craigslist": "craigslist-static-html-v1",
    "sabbaticalhomes": "sabbaticalhomes-city-html-v1",
    "json": "json-feed-v2",
    "homeharvest": "homeharvest-v1",
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


def _square_feet(value: str) -> int | float | None:
    match = re.search(r"([0-9][0-9,]*(?:\.\d+)?)\s*(?:sq\.?\s*ft\.?|square\s+feet)\b", value, re.I)
    return _number(match.group(1).replace(",", "") if match else None)


def _string_list(value: object, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        items = re.split(r"\s*[|;,]\s*", value)
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        raise ValueError(f"JSON listing {field_name} must be a string, array, or null")
    result = []
    for item in items:
        if not isinstance(item, (str, int, float)) or isinstance(item, bool):
            raise ValueError(f"JSON listing {field_name} values must be scalar")
        cleaned = _clean(str(item))
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result or None


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (str, int, float)):
        return _clean(str(value)) or None
    if isinstance(value, Mapping):
        parts = [f"{key}: {_as_text(item)}" for key, item in value.items() if _as_text(item)]
        return "; ".join(parts) or None
    if isinstance(value, (list, tuple, set)):
        parts = [_as_text(item) for item in value]
        return "; ".join(item for item in parts if item) or None
    return _clean(str(value)) or None


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
    sqft: int | float | None = None,
    available_date: str | None = None,
    property_type: str | None = None,
    amenities: list[str] | None = None,
    pets: str | None = None,
    parking: str | None = None,
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
        "sqft": sqft,
        "available_date": available_date or None,
        "property_type": property_type or None,
        "amenities": amenities,
        "pets": pets or None,
        "parking": parking or None,
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
        sqft_text = next(
            (value for key, value in facts.items() if key in {"SQUARE FEET", "SQ FT", "SQ. FT.", "SIZE"}),
            "",
        )
        sqft = _square_feet(sqft_text) or _number(sqft_text.replace(",", ""))
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
                sqft=sqft,
                available_date=available or None,
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
            sqft=_json_number(record.get("sqft"), "sqft"),
            available_date=_json_scalar(record.get("available_date"), "available_date"),
            property_type=_json_scalar(record.get("property_type"), "property_type"),
            amenities=_string_list(record.get("amenities"), "amenities"),
            pets=_as_text(record.get("pets")),
            parking=_as_text(record.get("parking")),
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
        sqft = _number(card.attrs.get("data-square-feet")) or _square_feet(feature_text)
        if sqft is not None and sqft <= 0:
            sqft = None

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
                sqft=sqft,
                available_date=available or None,
                property_type=property_type or None,
                observed_at=observed_at,
                notes=notes,
            )
        )
    return rows


def _parse_showmojo(root: _Node, base_url: str, source: str, observed_at: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for card in _nodes(root, lambda node: node.tag == "div" and "js-listing" in _classes(node)):
        provider_id = card.attrs.get("id", "")
        if provider_id.startswith("uid_"):
            provider_id = provider_id[4:]
        link = _first(card, lambda node: node.tag == "a" and re.search(r"/l/[a-z0-9]+/", node.attrs.get("href", ""), re.I) is not None)
        if not provider_id and link:
            match = re.search(r"/l/([a-z0-9]+)/", link.attrs["href"], re.I)
            provider_id = match.group(1) if match else ""
        if not provider_id or provider_id in seen:
            continue
        seen.add(provider_id)
        street_unit = _text(_first(card, _has_class("listing-address-header")))
        locality = _text(_first(card, _has_class("listing-city-state-zip")))
        address, unit = _split_managebuilding_title(street_unit, locality)
        text = _text(card)
        bedrooms = bathrooms = sqft = None
        for icon in _nodes(card, _has_class("listing-icon-wrap")):
            image = _first(icon, lambda node: node.tag == "img")
            icon_name = image.attrs.get("src", "").lower() if image else ""
            value = _coerce_number(_text(icon))
            if "bed-" in icon_name and bedrooms is None:
                bedrooms = value
            elif "bath-" in icon_name and bathrooms is None:
                bathrooms = value
            elif ("square" in icon_name or "ruler" in icon_name) and sqft is None:
                sqft = value
        rent_info = _text(_first(card, _has_class("rent-info")))
        available = None
        available_match = re.search(r"Available\s+(.+?)(?:\s+[·|]|$)", rent_info, re.I)
        if available_match:
            available = _clean(available_match.group(1))
        property_type = None
        for candidate in ("Apartment", "House", "Condo", "Townhouse", "Duplex"):
            if re.search(rf"\b{candidate}\b", rent_info, re.I):
                property_type = candidate.lower()
                break
        row = _listing(
            source=source,
            provider_id=provider_id,
            url=_canonical_url(base_url, link.attrs["href"]) if link else base_url,
            title=_text(_first(card, _has_class("listing-title"))),
            address=address,
            unit=unit,
            grain="unit" if unit else "property",
            rent=_money(_text(_first(card, _has_class("price"))) or rent_info),
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            sqft=sqft or _square_feet(text),
            available_date=available,
            property_type=property_type,
            pets="reported in card text" if re.search(r"\bpets?\b", text, re.I) else None,
            parking="reported in card text" if re.search(r"\b(?:parking|garage)\b", text, re.I) else None,
            observed_at=observed_at,
        )
        row["lat"] = _coerce_number(card.attrs.get("data-lat"))
        row["lon"] = _coerce_number(card.attrs.get("data-long"))
        rows.append(row)
    return rows


def _coerce_number(value: object) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if not match:
            return None
        parsed = float(match.group())
    else:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _jsonld_items(root: _Node) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for script in _nodes(
        root,
        lambda node: node.tag == "script" and node.attrs.get("type", "").lower() == "application/ld+json",
    ):
        try:
            value = json.loads(_text(script))
        except (json.JSONDecodeError, TypeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                documents.extend(child for child in graph if isinstance(child, dict))
            else:
                documents.append(item)
    return documents


def _parse_craigslist(root: _Node, base_url: str, source: str, observed_at: str) -> list[dict]:
    """Parse Craigslist's public static search cards; no detail requests."""

    schema_items: list[dict[str, Any]] = []
    for document in _jsonld_items(root):
        candidates = document.get("itemListElement")
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict):
                    item = candidate.get("item", candidate)
                    if isinstance(item, dict):
                        schema_items.append(item)

    rows: list[dict] = []
    seen: set[str] = set()
    cards = list(_nodes(root, lambda node: node.tag == "li" and "cl-static-search-result" in _classes(node)))
    for index, card in enumerate(cards):
        link = _first(card, lambda node: node.tag == "a" and bool(node.attrs.get("href")))
        if link is None:
            continue
        exact_url = _canonical_url(base_url, link.attrs["href"])
        id_match = re.search(r"/(\d+)(?:\.html)?/?$", urlsplit(exact_url).path)
        provider_id = id_match.group(1) if id_match else hashlib.sha256(exact_url.encode()).hexdigest()[:20]
        if provider_id in seen:
            continue
        seen.add(provider_id)
        schema = schema_items[index] if index < len(schema_items) else {}
        address_value = schema.get("address")
        if isinstance(address_value, Mapping):
            address = _clean(", ".join(
                str(address_value.get(key, ""))
                for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode")
                if address_value.get(key)
            ))
        else:
            address = _as_text(address_value)
        text = _text(card)
        bedrooms, bathrooms = _bed_bath(text)
        bedrooms = _coerce_number(schema.get("numberOfBedrooms")) if bedrooms is None else bedrooms
        bathrooms = _coerce_number(schema.get("numberOfBathroomsTotal")) if bathrooms is None else bathrooms
        geo = schema.get("geo") if isinstance(schema.get("geo"), Mapping) else schema
        location = _text(_first(card, _has_class("location")))
        notes = f"Search-card location: {location}" if location and not address else None
        pets = "reported in card text" if re.search(r"\b(?:cats?|dogs?|pets?)\b", text, re.I) else None
        parking = "reported in card text" if re.search(r"\b(?:parking|garage)\b", text, re.I) else None
        row = _listing(
            source=source,
            provider_id=provider_id,
            url=exact_url,
            title=card.attrs.get("title") or _text(_first(card, _has_class("title"))),
            address=address,
            unit=None,
            grain="unknown",
            rent=_money(_text(_first(card, _has_class("price"))) or text),
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            sqft=_square_feet(text),
            property_type=_as_text(schema.get("@type")),
            pets=pets,
            parking=parking,
            observed_at=observed_at,
            notes=notes,
        )
        row["lat"] = _coerce_number(geo.get("latitude")) if isinstance(geo, Mapping) else None
        row["lon"] = _coerce_number(geo.get("longitude")) if isinstance(geo, Mapping) else None
        rows.append(row)
    return rows


def _parse_sabbaticalhomes(root: _Node, base_url: str, source: str, observed_at: str) -> list[dict]:
    """Parse the site's single-page city carousel without fetching details."""

    rows: list[dict] = []
    seen: set[str] = set()
    for card in _nodes(root, lambda node: "listing-card" in _classes(node)):
        link = _first(card, lambda node: node.tag == "a" and re.search(r"/rental/\d+", node.attrs.get("href", "")) is not None)
        if link is None:
            continue
        match = re.search(r"/rental/(\d+)", link.attrs["href"])
        if not match or match.group(1) in seen:
            continue
        provider_id = match.group(1)
        seen.add(provider_id)
        text = _text(card)
        bedrooms, bathrooms = _bed_bath(text)
        rate = re.search(r"From\s+(?:[A-Z]{3}\s+)?\$([0-9,]+(?:\.\d+)?)\s*/\s*(\w+)", text, re.I)
        rent = None
        notes = None
        if rate:
            if rate.group(2).lower().startswith("month"):
                rent = _number(rate.group(1).replace(",", ""))
            else:
                notes = f"Non-monthly advertised rate retained as text: {rate.group(0)}"
        available = ""
        available_match = re.search(r"Available\s+(.+?)(?:From\s+(?:[A-Z]{3}\s+)?\$|View Description|$)", text, re.I)
        if available_match:
            available = _clean(available_match.group(1))
        title_node = _first(card, lambda node: bool(node.attrs.get("data-listing-title")))
        title = title_node.attrs.get("data-listing-title", "") if title_node else ""
        if not title:
            title = _text(_first(card, _has_class("listing-card-title")))
        rows.append(_listing(
            source=source,
            provider_id=provider_id,
            url=_canonical_url(base_url, link.attrs["href"]),
            title=title,
            address=None,
            unit=None,
            grain="property",
            rent=rent,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            sqft=_square_feet(text),
            available_date=available or None,
            property_type="furnished home",
            pets="reported in card text" if re.search(r"\bpets?\b", text, re.I) else None,
            parking="reported in card text" if re.search(r"\b(?:parking|garage)\b", text, re.I) else None,
            observed_at=observed_at,
            notes=notes,
        ))
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
    """Parse one supported result page or normalized JSON feed without I/O.

    Unknown values remain ``None``.  An empty list alone does not mean the
    source is empty; ``collect_source`` separately requires an explicit empty
    message from a recognized source page.
    """

    adapter = adapter.strip().lower()
    if adapter not in PARSABLE_ADAPTERS:
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
        parser = {
            "appfolio": _parse_appfolio,
            "managebuilding": _parse_managebuilding,
            "showmojo": _parse_showmojo,
            "craigslist": _parse_craigslist,
            "sabbaticalhomes": _parse_sabbaticalhomes,
        }[adapter]
        rows = parser(root, base_url, source_id.strip(), captured_at)
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
        return False, "robots.txt redirected to a different host; collection stopped", 1
    if result.status in (404, 410):
        return True, f"robots.txt absent (HTTP {result.status})", 1
    if result.status != 200:
        detail = result.error or f"HTTP {result.status}"
        return False, f"robots.txt unavailable ({detail}); collection stopped", 1
    parser = robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(result.body.decode("utf-8", errors="replace").splitlines())
    if not parser.can_fetch(USER_AGENT, page_url):
        return False, "robots.txt disallows this listings URL", 1
    return True, "robots.txt allows this path (this is not a terms-of-use determination)", 1


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
    if adapter == "showmojo":
        return "js-no-listings" in lowered and "js-listing not-active" not in lowered
    if adapter == "craigslist":
        return "cl-search-view" in lowered and any(
            message in lowered for message in ("no results", "nothing found", "zero results")
        )
    if adapter == "sabbaticalhomes":
        return bool(re.search(r"explore\s+0\s+home rental listings", lowered))
    has_shell = "js-listings-container" in lowered or "id=\"result_container\"" in lowered
    messages = (
        "there are no available listings at this time",
        "no available listings were found",
        "no listings match your search",
    )
    return has_shell and any(message in lowered for message in messages)


def _html_next_url(payload: str, page_url: str) -> str | None:
    root = _document(payload)
    next_link = _first(
        root,
        lambda node: node.tag == "a"
        and bool(node.attrs.get("href"))
        and (
            "next" in node.attrs.get("rel", "").lower().split()
            or "next" in _classes(node)
            or _text(node).strip().lower() in {"next", "next page", "›", "»"}
        ),
    )
    return urljoin(page_url, next_link.attrs["href"]) if next_link else None


def _json_next_url(payload: str, page_url: str) -> str | None:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    candidate: object = document.get("next_url") or document.get("next")
    if not candidate and isinstance(document.get("links"), dict):
        candidate = document["links"].get("next")
    if not candidate and isinstance(document.get("pagination"), dict):
        pagination = document["pagination"]
        candidate = pagination.get("next_url") or pagination.get("next")
    if isinstance(candidate, dict):
        candidate = candidate.get("href") or candidate.get("url")
    if isinstance(candidate, str) and candidate.strip():
        return urljoin(page_url, candidate.strip())
    if document.get("has_more") is True:
        parts = urlsplit(page_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        cursor = document.get("next_cursor")
        if cursor not in (None, ""):
            query["cursor"] = str(cursor)
        else:
            current = _coerce_number(document.get("page") or query.get("page") or 1)
            if not isinstance(current, int):
                return None
            query["page"] = str(current + 1)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    return None


def _bounded_int(value: object, default: int, maximum: int, field_name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive integer") from None
    if parsed < 1 or parsed > maximum:
        raise ValueError(f"{field_name} must be between 1 and {maximum}")
    return parsed


def _search_number(search: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        if key in search and search[key] not in (None, ""):
            value = _coerce_number(search[key])
            if value is None:
                raise ValueError(f"search.{key} must be numeric")
            return float(value)
    return None


def _filter_listings(rows: list[dict], search: Mapping[str, object]) -> tuple[list[dict], int]:
    """Apply known-fact filters; unknown values stay in the review queue."""

    max_rent = _search_number(search, "rent_max", "max_rent", "price_max", "budget_max")
    if max_rent is None:
        residents = _search_number(search, "residents")
        budget_per_person = _search_number(search, "budget_per_person")
        if residents is not None and budget_per_person is not None:
            max_rent = residents * budget_per_person
    bounds = {
        "rent": (
            _search_number(search, "rent_min", "price_min"),
            max_rent,
        ),
        "bedrooms": (
            _search_number(search, "bedrooms_min", "min_bedrooms", "beds_min"),
            _search_number(search, "bedrooms_max", "beds_max"),
        ),
        "bathrooms": (
            _search_number(search, "bathrooms_min", "min_bathrooms", "baths_min"),
            _search_number(search, "bathrooms_max", "baths_max"),
        ),
        "sqft": (
            _search_number(search, "sqft_min", "min_sqft"),
            _search_number(search, "sqft_max"),
        ),
    }
    requested_types = search.get("property_types") or search.get("property_type")
    if isinstance(requested_types, str):
        types = {requested_types.strip().lower()}
    elif isinstance(requested_types, (list, tuple, set)):
        types = {str(value).strip().lower() for value in requested_types if str(value).strip()}
    elif requested_types is None:
        types = set()
    else:
        raise ValueError("search.property_types must be a string or array")
    pets_required = search.get("pets_required") is True
    parking_required = search.get("parking_required") is True

    kept: list[dict] = []
    dropped = 0
    for row in rows:
        mismatch = False
        for field_name, (minimum, maximum) in bounds.items():
            value = row.get(field_name)
            if value is None:
                continue
            number = float(value)
            if minimum is not None and number < minimum or maximum is not None and number > maximum:
                mismatch = True
                break
        property_type = row.get("property_type")
        if not mismatch and types and property_type is not None and str(property_type).strip().lower() not in types:
            mismatch = True
        if not mismatch and pets_required and row.get("pets") is not None:
            mismatch = str(row["pets"]).strip().lower() in {"no", "false", "none", "not allowed", "no pets"}
        if not mismatch and parking_required and row.get("parking") is not None:
            mismatch = str(row["parking"]).strip().lower() in {"no", "false", "none", "not available", "no parking"}
        if mismatch:
            dropped += 1
        else:
            kept.append(row)
    return kept, dropped


def _coverage(rows: list[dict], *, pages_attempted: int = 0, pages_succeeded: int = 0,
              parsed: int | None = None, duplicates: int = 0, filtered: int = 0) -> dict:
    return {
        "pages_attempted": pages_attempted,
        "pages_succeeded": pages_succeeded,
        "records_parsed": len(rows) if parsed is None else parsed,
        "records_returned": len(rows),
        "duplicates_skipped": duplicates,
        "known_rent": sum(row.get("rent") is not None for row in rows),
        "known_bedrooms": sum(row.get("bedrooms") is not None for row in rows),
        "known_sqft": sum(row.get("sqft") is not None for row in rows),
        "unknown_sqft_retained": sum(row.get("sqft") is None for row in rows),
        "filtered_known_mismatches": filtered,
    }


def _result(status: str, message: str, requests: int | None, listings: list[dict] | None = None, *,
            partial: bool = False, coverage: dict | None = None, errors: list[str] | None = None,
            resume_url: str | None = None) -> dict:
    rows = listings or []
    result = {
        "status": status,
        "listings": rows,
        "message": message,
        "requests": requests,
        "partial": partial,
        "coverage": coverage or _coverage(rows),
        "errors": errors or [],
    }
    if resume_url:
        result["resume_url"] = resume_url
    return result


def _fetch_with_retry(url: str, timeout: int, *, accept: str, retries: int,
                      request_budget: int) -> tuple[_Fetch, int]:
    attempts = 0
    result = _Fetch(0, url, b"", "", "request budget exhausted")
    while attempts < request_budget:
        result = _fetch_url(url, timeout, accept=accept)
        attempts += 1
        if result.status not in (0, 408, 500, 502, 503, 504) or attempts > retries:
            break
    return result, attempts


def _record_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        mapped = value.model_dump(mode="json")
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    if hasattr(value, "dict"):
        mapped = value.dict()
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    return {}


def _nested(record: Mapping[str, Any], *paths: str) -> object:
    for path in paths:
        value: object = record
        for part in path.split("."):
            if not isinstance(value, Mapping) or part not in value:
                value = None
                break
            value = value[part]
        if value not in (None, "", [], {}):
            return value
    return None


def _homeharvest_rows(raw: object, source_id: str, observed_at: str) -> list[dict]:
    if hasattr(raw, "to_dict"):
        records = raw.to_dict(orient="records")
    elif isinstance(raw, (list, tuple)):
        records = list(raw)
    else:
        raise ValueError("HomeHarvest returned an unsupported result type")
    rows: list[dict] = []
    for index, value in enumerate(records):
        record = _record_mapping(value)
        if not record:
            continue
        provider_id = _nested(record, "listing_id", "property_id", "mls_id", "mls")
        if provider_id in (None, ""):
            provider_id = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()[:24]
        full_baths = _coerce_number(_nested(record, "description.full_baths", "full_baths", "baths_full", "bathrooms"))
        half_baths = _coerce_number(_nested(record, "description.half_baths", "half_baths", "baths_half")) or 0
        bathrooms = (float(full_baths) + 0.5 * float(half_baths)) if full_baths is not None else None
        address_value = _nested(record, "address.formatted_address", "formatted_address", "full_street_line")
        if not address_value:
            address_value = ", ".join(
                str(part) for part in (
                    _nested(record, "address.street", "street"),
                    _nested(record, "address.city", "city"),
                    _nested(record, "address.state", "state"),
                    _nested(record, "address.zip_code", "zip_code"),
                ) if part
            )
        exact_rent = _coerce_number(_nested(record, "list_price", "price"))
        rent_min = _coerce_number(_nested(record, "list_price_min"))
        rent_max = _coerce_number(_nested(record, "list_price_max"))
        rent_note = None
        if exact_rent is None and rent_min is not None and rent_min == rent_max:
            exact_rent = rent_min
        elif exact_rent is None and (rent_min is not None or rent_max is not None):
            rent_note = f"Advertised rent range: {rent_min if rent_min is not None else 'unknown'} to {rent_max if rent_max is not None else 'unknown'}"
        description_text = _as_text(_nested(record, "description.text", "text"))
        pets = _as_text(_nested(record, "pet_policy", "pets"))
        if pets is None and description_text:
            pet_match = re.search(r"\b(?:cats?|dogs?|pets?)\b[^.;]{0,60}", description_text, re.I)
            pets = _clean(pet_match.group(0)) if pet_match else None
        row = _listing(
            source=source_id,
            provider_id=str(provider_id),
            url=_as_text(_nested(record, "property_url", "permalink", "url")),
            title=_as_text(_nested(record, "style", "description.type", "property_type")),
            address=_as_text(address_value),
            unit=_as_text(_nested(record, "address.unit", "unit")),
            grain="unit" if _nested(record, "address.unit", "unit") else "property",
            rent=exact_rent,
            bedrooms=_coerce_number(_nested(record, "description.beds", "beds", "bedrooms")),
            bathrooms=bathrooms,
            sqft=_coerce_number(_nested(record, "description.sqft", "sqft")),
            property_type=_as_text(_nested(record, "description.type", "property_type", "style")),
            amenities=_string_list(_nested(record, "tags", "amenities"), "amenities"),
            pets=pets,
            parking=_as_text(_nested(record, "parking", "parking_garage", "description.garage", "garage")),
            observed_at=observed_at,
            notes=rent_note,
        )
        row["lat"] = _coerce_number(_nested(record, "location.latitude", "latitude"))
        row["lon"] = _coerce_number(_nested(record, "location.longitude", "longitude"))
        row["parser_version"] = PARSER_VERSIONS["homeharvest"]
        row["source_content_sha256"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, default=str).encode()
        ).hexdigest()
        rows.append(row)
    return rows


def _collect_homeharvest(source: Mapping[str, object], source_id: str) -> dict:
    search = source.get("search") or {}
    if not isinstance(search, Mapping):
        return _result("error", "source search must be an object", 0)
    location = search.get("location") or search.get("city")
    if not isinstance(location, str) or not location.strip():
        return _result("error", "HomeHarvest requires search.location", 0)
    try:
        module = importlib.import_module("homeharvest")
        scrape_property = getattr(module, "scrape_property")
    except (ImportError, AttributeError):
        return _result("error", "Optional dependency missing: install the collect extra (uv sync --extra collect in a checkout)", 0)
    try:
        max_listings = _bounded_int(source.get("max_listings"), 200, MAX_LISTINGS, "max_listings")
        kwargs: dict[str, object] = {
            "location": location.strip(),
            "listing_type": "for_rent",
            "limit": max_listings,
            "parallel": False,
            "extra_property_data": False,
        }
        aliases = {
            "beds_min": ("beds_min", "bedrooms_min", "min_bedrooms"),
            "beds_max": ("beds_max", "bedrooms_max"),
            "baths_min": ("baths_min", "bathrooms_min", "min_bathrooms"),
            "baths_max": ("baths_max", "bathrooms_max"),
            "price_min": ("price_min", "rent_min"),
            "price_max": ("price_max", "rent_max", "max_rent", "budget_max"),
            "past_days": ("past_days",),
        }
        for target, keys in aliases.items():
            for key in keys:
                if search.get(key) not in (None, ""):
                    kwargs[target] = search[key]
                    break
        # Deliberately omit sqft_min/max: provider-side filtering could silently
        # discard records whose square footage is unknown.
        raw = scrape_property(**kwargs)
        rows = _homeharvest_rows(raw, source_id, _utc_now())
        reached_limit = len(rows) >= max_listings
        rows, filtered = _filter_listings(rows, search)
        partial = reached_limit
        message = (
            f"HomeHarvest returned {len(rows)} normalized rental record(s). "
            "The library does not expose an exact underlying HTTP request count."
        )
        if partial:
            message += " Result reached max_listings and may be partial."
        return _result("success" if rows else "empty", message, None, rows, partial=partial,
                       coverage=_coverage(rows, parsed=len(rows) + filtered, filtered=filtered))
    except Exception as exc:
        return _result("error", f"HomeHarvest failed: {type(exc).__name__}: {exc}", None,
                       errors=[f"{type(exc).__name__}: {exc}"])


def collect_source(source: Mapping[str, object], *, timeout: int = 20) -> dict:
    """Collect one source under explicit page, listing, request, and host bounds."""

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
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return _result("error", "timeout must be positive", 0)
    if adapter == "assisted":
        return _result(
            "unimplemented",
            str(source.get("assisted_reason") or "No scripted collector is implemented for this source; use the documented user-assisted workflow."),
            0,
        )
    if adapter == "homeharvest":
        return _collect_homeharvest(source, source_id)

    parts = urlsplit(page_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return _result("error", "source URL must be an absolute HTTP(S) URL", 0)
    try:
        max_pages = _bounded_int(source.get("max_pages"), 1, MAX_PAGES, "max_pages")
        max_listings = _bounded_int(source.get("max_listings"), 500, MAX_LISTINGS, "max_listings")
        retries = _bounded_int(source.get("retries"), 1, 2, "retries")
        default_requests = min(MAX_REQUESTS, 1 + max_pages + min(max_pages, 2))
        max_requests = _bounded_int(source.get("max_requests"), default_requests, MAX_REQUESTS, "max_requests")
    except ValueError as exc:
        return _result("error", str(exc), 0)
    if max_requests < 2:
        return _result("error", "max_requests must leave room for robots.txt and one page", 0)
    search = source.get("search") or {}
    if not isinstance(search, Mapping):
        return _result("error", "source search must be an object", 0)
    start_url = str(source.get("resume_url") or page_url).strip()
    if urlsplit(start_url).netloc.lower() != parts.netloc.lower():
        return _result("error", "resume_url must use the configured source host", 0)

    allowed, robots_message, requests_made = _robots_permission(page_url, timeout)
    if not allowed:
        return _result("blocked", robots_message, requests_made)

    accept = "application/json,application/*+json" if adapter == "json" else "text/html,application/xhtml+xml"
    rows: list[dict] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    errors: list[str] = []
    duplicates = 0
    pages_attempted = 0
    pages_succeeded = 0
    next_url: str | None = start_url
    explicit_empty = False
    listing_cap_truncated = False

    while next_url and pages_attempted < max_pages and len(rows) < max_listings and requests_made < max_requests:
        if next_url in seen_pages:
            errors.append(f"pagination repeated URL: {next_url}")
            break
        if urlsplit(next_url).netloc.lower() != parts.netloc.lower():
            errors.append("pagination pointed to a different host; collection stopped")
            break
        seen_pages.add(next_url)
        request_budget = max_requests - requests_made
        fetched, attempts = _fetch_with_retry(
            next_url, timeout, accept=accept, retries=retries, request_budget=request_budget
        )
        pages_attempted += 1
        requests_made += attempts
        if urlsplit(fetched.url).netloc.lower() != parts.netloc.lower():
            errors.append("listings request redirected to a different host whose robots policy was not checked")
            break
        if fetched.status in (401, 403, 429):
            errors.append(f"listings request blocked (HTTP {fetched.status}); no bypass attempted")
            break
        if fetched.status != 200 or fetched.error:
            errors.append(f"listings request failed ({fetched.error or f'HTTP {fetched.status}'})")
            break
        json_content = fetched.content_type in ("application/json", "text/json") or fetched.content_type.endswith("+json")
        html_content = fetched.content_type in ("text/html", "application/xhtml+xml", "")
        if (adapter == "json" and not json_content) or (adapter != "json" and not html_content):
            errors.append(f"unexpected content type {fetched.content_type!r}")
            break
        payload = fetched.body.decode("utf-8", errors="replace")
        if adapter != "json" and _blocked_page(payload):
            errors.append("response is a block or human-verification page; no bypass attempted")
            break
        try:
            page_rows = parse(adapter, fetched.body, fetched.url, source_id, observed_at=_utc_now())
        except Exception as exc:
            errors.append(f"parser failed: {type(exc).__name__}: {exc}")
            break
        pages_succeeded += 1
        explicit_empty = _explicit_empty(adapter, payload)
        if not page_rows and not explicit_empty:
            errors.append("No recognized listing cards or explicit empty-state evidence; source markup may have changed.")
            break
        for row in page_rows:
            if row["source_id"] in seen_ids:
                duplicates += 1
                continue
            if len(rows) >= max_listings:
                listing_cap_truncated = True
                break
            seen_ids.add(row["source_id"])
            rows.append(row)
        candidate = _json_next_url(payload, fetched.url) if adapter == "json" else _html_next_url(payload, fetched.url)
        if candidate and urlsplit(candidate).netloc.lower() != parts.netloc.lower():
            errors.append("pagination pointed to a different host; collection stopped")
            next_url = candidate
            break
        next_url = candidate
        if explicit_empty:
            next_url = None

    try:
        filtered_rows, filtered = _filter_listings(rows, search)
    except ValueError as exc:
        return _result("error", str(exc), requests_made, coverage=_coverage(
            rows, pages_attempted=pages_attempted, pages_succeeded=pages_succeeded,
            parsed=len(rows) + duplicates, duplicates=duplicates,
        ))
    cap_partial = listing_cap_truncated or bool(next_url) and (
        len(rows) >= max_listings or pages_attempted >= max_pages or requests_made >= max_requests
    )
    partial = bool(errors) or cap_partial
    coverage = _coverage(
        filtered_rows,
        pages_attempted=pages_attempted,
        pages_succeeded=pages_succeeded,
        parsed=len(rows) + duplicates,
        duplicates=duplicates,
        filtered=filtered,
    )
    if filtered_rows:
        status = "partial" if partial else "success"
        message = (
            f"Parsed {len(filtered_rows)} listing record(s) across {pages_succeeded} page(s); {robots_message}."
        )
        if cap_partial:
            message += " Partial result: pagination remains after a configured page, listing, or request cap was reached."
        if errors:
            message += f" Partial result: {errors[-1]}"
        resume_url = next_url if partial and not listing_cap_truncated else None
        return _result(status, message, requests_made, filtered_rows, partial=partial,
                       coverage=coverage, errors=errors, resume_url=resume_url)
    if cap_partial and not errors:
        return _result(
            "partial",
            "No parsed records survived known-fact filters before a configured page, listing, or request cap was reached; the result remains partial.",
            requests_made,
            partial=True,
            coverage=coverage,
            resume_url=next_url if not listing_cap_truncated else None,
        )
    if errors:
        blocked = any(
            "blocked" in value or "human-verification" in value or "different host" in value
            for value in errors
        )
        return _result("blocked" if blocked else "error", errors[-1], requests_made,
                       partial=False, coverage=coverage, errors=errors, resume_url=next_url)
    if explicit_empty or rows and filtered:
        message = (
            "Recognized source page explicitly reports no available rentals."
            if explicit_empty and not rows
            else "All parsed records had known facts outside the configured search; unknown facts were retained."
        )
        return _result("empty", f"{message} {robots_message}.", requests_made,
                       coverage=coverage)
    return _result("error", "No listing records were returned.", requests_made, coverage=coverage)


__all__ = ["PARSER_VERSIONS", "SUPPORTED_ADAPTERS", "collect_source", "parse"]
