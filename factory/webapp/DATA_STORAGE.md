# Lager Dashboard -- Data Storage

All persistent data (lines, stations, scripts, station runs) is stored on
the Lager box via its REST API (`/dashboard/*` endpoints).  The webapp
itself is stateless -- it acts as a thin UI layer that proxies CRUD
operations to whichever box owns the data.

Ad-hoc script runs and suites are ephemeral (in-memory only).  They exist
for the lifetime of the webapp process and are lost on restart.

## Where Each Piece Lives

| Data | Storage | Persists across restart? | Accessed via |
|------|---------|--------------------------|--------------|
| Lines | Box SQLite (`dashboard_db.py`) | Yes | `BoxDataClient.list_lines()` etc. |
| Stations | Box SQLite | Yes | `BoxDataClient.list_stations()` etc. |
| Station scripts (source code) | Box SQLite (BLOB) | Yes | `BoxDataClient.list_station_scripts()` |
| Station run results | Box SQLite | Yes | `BoxDataClient.list_station_runs()` |
| Ad-hoc run results + output | In-memory `RunRecord` | No | `script_runner.get_all_runs()` |
| Ad-hoc suite results | In-memory `SuiteRecord` | No | `script_runner.get_all_suites()` |

## Key Files

| File | Role |
|------|------|
| `box_data_client.py` | HTTP client for box `/dashboard/*` endpoints |
| `script_runner.py` | Ad-hoc execution engine, in-memory only |
| `step_runner.py` | Station execution engine (WebSocket + SSH), persists to box API |
| `routes/api.py` | REST endpoints, creates/updates runs via `BoxDataClient` |
| `routes/box_lines.py` | Line CRUD + aggregated `/lines` view |
| `routes/box_stations.py` | Station CRUD + script management |
| `routes/box_station_runner.py` | Interactive step runner + WebSocket |
| `routes/results.py` | Results page, aggregates from all box APIs |
| `routes/dashboard.py` | Dashboard, aggregates lines from all boxes |

## How Data Flows

### Station Runs (interactive step runner)

```
Browser                     Flask (port 5001)             Lager Box (port 5000)
  |                              |                        |
  |-- POST /api/station-run/start -->                     |
  |   {station_id, box_id}       |                        |
  |                              |-- BoxDataClient ------>|
  |                              |   create_station_run() |
  |                              |   list_station_scripts()|
  |                              |                        |
  |              start StepRunSession in daemon thread     |
  |                              |                        |
  |<--- {run_id, steps} --------|                        |
  |                              |                        |
  |== WebSocket /ws/run/<id> ===>|                        |
  |                              |-- SSH + docker exec -->|
  |                              |                        |
  |<-- events (via WS) ---------|                        |
  |-- responses (via WS) ------>|-- stdin -------------->|
  |                              |                        |
  |<-- lager-factory-complete ---|                        |
  |                              |                        |
  |-- POST /api/station-run/<id>/stop -->                 |
  |   {box_id, status, ...}      |                        |
  |                              |-- BoxDataClient ------>|
  |                              |   update_station_run() |
```

### Ad-hoc Script Runs (drag-and-drop)

```
Browser                     Flask (port 5001)             Lager Box
  |                              |                        |
  |-- POST /api/run ----------->|                        |
  |   {box_id, script, name}    |                        |
  |                              |                        |
  |              create RunRecord (in-memory)             |
  |              start daemon thread                      |
  |                              |                        |
  |<--- {run_id} ---------------|                        |
  |                              |                        |
  |-- GET /api/stream/<id> ---->|  (SSE connection)      |
  |                              |-- SSH + docker exec -->|
  |                              |                        |
  |<-- SSE data: {type, line} --|                        |
  |              ...streams until script exits...         |
  |                              |                        |
  |<-- SSE data: {type: done} --|                        |
  |                              |                        |
  |              RunRecord stays in memory (ephemeral)    |
```

Ad-hoc runs are NOT persisted.  They exist only for the webapp session.
