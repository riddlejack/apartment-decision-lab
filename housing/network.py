"""Explicit, resumable setup of public Chicago street and transit inputs."""
from datetime import date
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import zipfile

PACE_PAGE = "https://www.pacebus.com/route-timetable-data-services"
CHICAGO = [
    {"name": "chicago.osm.pbf", "url": "https://download.bbbike.org/osm/bbbike/Chicago/Chicago.osm.pbf", "credit": "OpenStreetMap contributors, ODbL; extract by BBBike"},
    {"name": "cta.zip", "url": "https://www.transitchicago.com/downloads/sch_data/google_transit.zip", "credit": "Chicago Transit Authority"},
    {"name": "metra.zip", "url": "https://schedules.metrarail.com/gtfs/schedule.zip", "credit": "Metra"},
    {"name": "pace.zip", "url": PACE_PAGE, "credit": "Pace Suburban Bus; agency terms, noncommercial use"},
]


class FeedLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href", "")
        url = urljoin(PACE_PAGE, href)
        if tag == "a" and urlparse(url).hostname == "www.pacebus.com" and urlparse(url).path.lower().endswith(".zip") and "gtfs" in url.lower():
            self.links.append(url)


def _request(url):
    return urlopen(Request(url, headers={"User-Agent": "Goldblum/0.4 (public routing data download)"}), timeout=90)


def _download(url, target, max_bytes=300 * 1024 * 1024):
    """Leave existing files intact if a transfer or format check fails."""
    temporary = target.with_suffix(target.suffix + ".part")
    digest, size = hashlib.sha256(), 0
    try:
        with _request(url) as response, temporary.open("wb") as output:
            if int(response.headers.get("Content-Length", 0)) > max_bytes:
                raise ValueError("Download exceeds 300 MB; use a smaller city extract")
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("Download exceeds 300 MB; use a smaller city extract")
                digest.update(chunk)
                output.write(chunk)
        if target.suffix == ".zip":
            with zipfile.ZipFile(temporary) as archive:
                names = set(archive.namelist())
                if not {"stops.txt", "trips.txt", "stop_times.txt"} <= names or not {"calendar.txt", "calendar_dates.txt"} & names:
                    raise ValueError("Downloaded archive is not a GTFS schedule feed")
        else:
            with temporary.open("rb") as stream:
                if size < 100 or b"OSMHeader" not in stream.read(65536):
                    raise ValueError("Downloaded file is not an OSM PBF extract")
        if os.name == "posix":
            temporary.chmod(0o600)
        temporary.replace(target)
        return {"bytes": size, "sha256": digest.hexdigest()}
    finally:
        temporary.unlink(missing_ok=True)


def prepare(workspace, config, *, download=False, refresh=False, city=None):
    city = city or config.get("city", "Chicago")
    if city.strip().lower() not in {"chicago", "chicago, il", "chicago, illinois"}:
        raise ValueError("Automatic network setup currently supports Chicago. For another city, place its OSM PBF and GTFS files together and set routing.network_dir and timezone; see docs/ROUTING.md.")
    folder = Path(workspace) / "network"
    result = {"directory": str(folder), "files": [dict(item) for item in CHICAGO], "downloaded": False,
              "note": "Chicago city extract, not the entire commuter region. Use a larger extract for suburban destinations. Downloads run only with --download; existing files are reused unless --refresh."}
    if not download:
        return result
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    changed = False
    try:
        for item in result["files"]:
            target = folder / item["name"]
            if target.exists() and not refresh:
                item["status"] = "reused"
                continue
            url = item["url"]
            if url == PACE_PAGE:
                with _request(PACE_PAGE) as response:
                    html = response.read(2 * 1024 * 1024).decode("utf-8")
                parser = FeedLinks()
                parser.feed(html)
                if not parser.links:
                    raise ValueError("Pace download link changed. Download its GTFS feed manually from " + PACE_PAGE)
                url = parser.links[0]
            item.update(_download(url, target), status="downloaded", url=url)
            changed = True
    finally:
        # These are derived caches only; refresh must never reuse an older graph.
        if changed:
            for name in ("network.dat", "network_settings.json"):
                (folder / name).unlink(missing_ok=True)
    from .config import save_config
    settings = config.setdefault("routing", {})
    settings.update(network_dir=str(folder))
    settings.setdefault("date", date.today().isoformat())
    settings.setdefault("threads", 2)
    settings.setdefault("max_memory_gb", 4)
    result["downloaded"] = True
    (folder / "sources.json").write_text(json.dumps(result, indent=2) + "\n")
    save_config(workspace, config)
    return result
