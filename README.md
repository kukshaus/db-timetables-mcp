# db-timetables-mcp

MCP server for live **Deutsche Bahn** station boards. Ask Claude (or any MCP client) things like:

- "When does the next train leave Dresden Hbf?"
- "Is the ICE to Berlin from Leipzig delayed?"
- "Any platform changes or cancellations at Köln Hbf in the next 2 hours?"

It uses the **official [DB Timetables API](https://developers.deutschebahn.com/db-api-marketplace/apis/product/timetables)** and merges the planned timetable with the live changes feed. It is read-only.

## Tools

| Tool | What it returns |
|---|---|
| `find_station` | Station name → EVA number and DS100 code |
| `departures` | Departure board: planned and expected time, delay, platform (and if it changed), cancellations, disruption messages, route |
| `arrivals` | Same data for arrivals, with the origin of each train |

`departures` and `arrivals` accept a station name or an EVA number, an optional `start` time (local Berlin time in ISO format, default now), `hours` (1–6) and `limit`.

## Setup

1. Create a free account at [developers.deutschebahn.com](https://developers.deutschebahn.com), create an application and subscribe it to the **Timetables** API (the free plan allows 60 calls/min).
2. Copy your **Client ID** and **Client Secret (API Key)**.
3. Add the server to your MCP client.

**Claude Code**

```bash
git clone https://github.com/kukshaus/db-timetables-mcp.git
claude mcp add db-timetables -s user \
  -e DB_CLIENT_ID=your-client-id -e DB_API_KEY=your-api-key \
  -- uv --directory /path/to/db-timetables-mcp run db-timetables-mcp
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "db-timetables": {
      "command": "uv",
      "args": ["--directory", "/path/to/db-timetables-mcp", "run", "db-timetables-mcp"],
      "env": { "DB_CLIENT_ID": "your-client-id", "DB_API_KEY": "your-api-key" }
    }
  }
}
```

On macOS you can keep the keys out of config files and store them in the Keychain instead. The server reads them when the env vars are missing:

```bash
security add-generic-password -s db-api-client-id -a "$USER" -w 'your-client-id'
security add-generic-password -s db-api-key -a "$USER" -w 'your-api-key'
```

## Example output

```
22:12  RE 50     → Leipzig Hbf        platform 9
22:18  S 2       → Dresden Flughafen  platform 14
22:22  TLX 76537 → Görlitz            platform 14
```

## Development

```bash
uv sync
uv run pytest
```

## Limits

- Covers stations operated by DB Station&Service (all major German stations).
- No journey planning (A → B with transfers). The Timetables API is per station.
- The free plan allows 60 requests/min. One board for 1 hour costs 2 requests.

## License

MIT. Not affiliated with Deutsche Bahn AG. Data © DB Station&Service AG via the DB API Marketplace.
