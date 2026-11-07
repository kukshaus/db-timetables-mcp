"""FastMCP server exposing Deutsche Bahn station departures and arrivals (read-only)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from .client import BERLIN, DBApiError, TimetablesClient

mcp = FastMCP(
    name="Deutsche Bahn Timetables",
    instructions=(
        "Live departures and arrivals for German railway stations from the official "
        "Deutsche Bahn Timetables API: planned times, delays, platform changes, "
        "cancellations and disruption notes. Read-only. Times are local Berlin time."
    ),
)

_client: TimetablesClient | None = None


def _get_client() -> TimetablesClient:
    global _client
    if _client is None:
        _client = TimetablesClient()
    return _client


def _parse_start(start: str | None) -> datetime:
    if not start:
        return datetime.now(BERLIN).replace(second=0, microsecond=0)
    try:
        value = datetime.fromisoformat(start)
    except ValueError as exc:
        raise ToolError(f"start must look like '2026-11-08T07:30', got '{start}'") from exc
    return value.replace(tzinfo=BERLIN) if value.tzinfo is None else value.astimezone(BERLIN)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def find_station(
    query: Annotated[str, Field(description="Station name or part of it, e.g. 'Dresden Hbf' or 'Köln'")],
) -> list[dict]:
    """Find German railway stations by name. Returns name, EVA number and DS100 code."""
    try:
        stations = await _get_client().find_stations(query)
    except DBApiError as exc:
        raise ToolError(str(exc)) from exc
    return [{"name": s.name, "eva": s.eva, "ds100": s.ds100} for s in stations]


async def _board(station: str, kind: Literal["departure", "arrival"], start: str | None,
                 hours: int, limit: int) -> dict:
    client = _get_client()
    try:
        st = await client.resolve_station(station)
        events = await client.events(st.eva, kind, _parse_start(start), hours)
    except DBApiError as exc:
        raise ToolError(str(exc)) from exc
    rows = [e.to_dict(kind) for e in events[:limit]]
    return {
        "station": st.name,
        "eva": st.eva,
        "count": len(rows),
        "delayed": sum(1 for r in rows if r["delay_min"] >= 5),
        "cancelled": sum(1 for r in rows if r["cancelled"]),
        f"{kind}s": rows,
    }


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def departures(
    station: Annotated[str, Field(description="Station name (e.g. 'Berlin Hbf') or EVA number")],
    start: Annotated[str | None, Field(description="Local Berlin time, ISO format. Default: now")] = None,
    hours: Annotated[int, Field(ge=1, le=6, description="How many hours to look ahead")] = 1,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> dict:
    """Departure board with live delays, platform changes, cancellations and messages."""
    return await _board(station, "departure", start, hours, limit)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def arrivals(
    station: Annotated[str, Field(description="Station name (e.g. 'Berlin Hbf') or EVA number")],
    start: Annotated[str | None, Field(description="Local Berlin time, ISO format. Default: now")] = None,
    hours: Annotated[int, Field(ge=1, le=6, description="How many hours to look ahead")] = 1,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> dict:
    """Arrival board with live delays, platform changes, cancellations and messages."""
    return await _board(station, "arrival", start, hours, limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
