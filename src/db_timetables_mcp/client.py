"""Small client for the Deutsche Bahn Timetables API (DB API Marketplace).

Docs: https://developers.deutschebahn.com/db-api-marketplace/apis/product/timetables
All times from the API are local Berlin time in ``YYMMddHHmm`` format.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

BASE_URL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
BERLIN = ZoneInfo("Europe/Berlin")


class DBApiError(RuntimeError):
    """Raised when the API answers with an error the caller should see."""


def _keychain(service: str) -> str | None:
    if not shutil.which("security"):
        return None
    out = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    return out.stdout.strip() or None


def load_credentials() -> tuple[str, str]:
    """Env vars first (DB_CLIENT_ID, DB_API_KEY), then macOS Keychain."""
    client_id = os.environ.get("DB_CLIENT_ID") or _keychain("db-api-client-id")
    api_key = os.environ.get("DB_API_KEY") or _keychain("db-api-key")
    if not client_id or not api_key:
        raise DBApiError(
            "Missing credentials. Set DB_CLIENT_ID and DB_API_KEY "
            "(free at developers.deutschebahn.com, subscribe to 'Timetables')."
        )
    return client_id, api_key


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%y%m%d%H%M").replace(tzinfo=BERLIN)


@dataclass
class Station:
    name: str
    eva: str
    ds100: str | None = None


@dataclass
class Event:
    """One arrival or departure of a train at the station."""

    train: str
    planned: datetime
    actual: datetime | None
    planned_platform: str | None
    changed_platform: str | None
    path: list[str]
    cancelled: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def delay_minutes(self) -> int:
        if not self.actual:
            return 0
        return int((self.actual - self.planned).total_seconds() // 60)

    def to_dict(self, kind: str) -> dict:
        end_label = "to" if kind == "departure" else "from"
        end = (self.path[-1] if kind == "departure" else self.path[0]) if self.path else None
        return {
            "train": self.train,
            end_label: end,
            "planned": self.planned.strftime("%Y-%m-%d %H:%M"),
            "expected": (self.actual or self.planned).strftime("%H:%M"),
            "delay_min": self.delay_minutes,
            "platform": self.changed_platform or self.planned_platform,
            "platform_changed": bool(
                self.changed_platform and self.changed_platform != self.planned_platform
            ),
            "cancelled": self.cancelled,
            "via": self.path[:-1][:4] if kind == "departure" else self.path[1:][-4:],
            "messages": self.messages,
        }


def _train_name(stop: ET.Element, event: ET.Element) -> str:
    tl = stop.find("tl")
    category = tl.get("c", "") if tl is not None else ""
    number = tl.get("n", "") if tl is not None else ""
    line = event.get("l")
    # Regional trains are known by their line ("RE 50", "S 1"), long distance by number.
    if line and category in {"S", "RE", "RB", "IRE", "Bus", "BUS", "STR"}:
        if line.upper().startswith(category.upper()):
            line = line[len(category):]
        return f"{category} {line.strip()}".strip()
    return f"{category} {number}".strip()


def _messages(*elements: ET.Element | None) -> list[str]:
    texts: list[str] = []
    for el in elements:
        if el is None:
            continue
        for m in el.findall("m"):
            text = m.get("txt") or m.get("ext")
            if text and text not in texts:
                texts.append(text)
    return texts


def parse_stations(xml: str) -> list[Station]:
    root = ET.fromstring(xml)
    return [
        Station(name=s.get("name", ""), eva=s.get("eva", ""), ds100=s.get("ds100"))
        for s in root.findall("station")
    ]


def parse_events(plan_xml: str, changes_xml: str | None, kind: str) -> list[Event]:
    """Merge the planned timetable with the live changes feed."""
    tag = "dp" if kind == "departure" else "ar"
    changes: dict[str, ET.Element] = {}
    if changes_xml:
        for s in ET.fromstring(changes_xml).findall("s"):
            changes[s.get("id", "")] = s

    events: list[Event] = []
    for stop in ET.fromstring(plan_xml).findall("s"):
        planned_el = stop.find(tag)
        if planned_el is None or planned_el.get("hi") == "1":
            continue
        change_stop = changes.get(stop.get("id", ""))
        change_el = change_stop.find(tag) if change_stop is not None else None
        get = lambda attr: change_el.get(attr) if change_el is not None else None  # noqa: E731

        path_raw = get("cpth") or planned_el.get("ppth") or ""
        events.append(
            Event(
                train=_train_name(stop, planned_el),
                planned=parse_ts(planned_el.get("pt")),
                actual=parse_ts(get("ct")),
                planned_platform=planned_el.get("pp"),
                changed_platform=get("cp"),
                path=[p for p in path_raw.split("|") if p],
                cancelled=get("cs") == "c",
                messages=_messages(change_stop, change_el),
            )
        )
    return sorted(events, key=lambda e: e.planned)


class TimetablesClient:
    def __init__(self, client_id: str | None = None, api_key: str | None = None,
                 http: httpx.AsyncClient | None = None) -> None:
        if not (client_id and api_key):
            client_id, api_key = load_credentials()
        self._http = http or httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=20,
            headers={
                "DB-Client-Id": client_id,
                "DB-Api-Key": api_key,
                "accept": "application/xml",
            },
        )

    async def _get(self, path: str, allow_404: bool = False) -> str | None:
        resp = await self._http.get(path)
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code in (401, 403):
            raise DBApiError(
                f"DB API refused the request ({resp.status_code}). Check the keys and "
                "that your app is subscribed to the Timetables plan."
            )
        if resp.status_code == 429:
            raise DBApiError("DB API rate limit reached (60 calls/min on the free plan). Try again shortly.")
        resp.raise_for_status()
        return resp.text

    async def find_stations(self, query: str) -> list[Station]:
        if query.isdigit():
            return [Station(name=query, eva=query)]
        xml = await self._get(f"/station/{quote(query, safe='')}", allow_404=True)
        return parse_stations(xml) if xml else []

    async def resolve_station(self, station: str) -> Station:
        found = await self.find_stations(station.strip())
        if not found:
            raise DBApiError(f"No station found for '{station}'. Try the exact name, e.g. 'Berlin Hbf'.")
        return found[0]

    async def events(self, eva: str, kind: str, start: datetime, hours: int) -> list[Event]:
        hours = max(1, min(hours, 6))
        changes = await self._get(f"/fchg/{eva}", allow_404=True)
        result: list[Event] = []
        for i in range(hours):
            slot = start + timedelta(hours=i)
            plan = await self._get(f"/plan/{eva}/{slot:%y%m%d}/{slot:%H}", allow_404=True)
            if plan:
                result.extend(parse_events(plan, changes, kind))
        return [e for e in result if (e.actual or e.planned) >= start]

    async def aclose(self) -> None:
        await self._http.aclose()
