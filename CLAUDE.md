# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A desktop app that simulates **Modbus TCP and RTU slaves simultaneously**, for developing/testing Modbus masters. TCP and RTU slave data are fully isolated even when Slave IDs collide. It can also act as a **Modbus master/client** (`modbus_sim/master.py`, "マスター" tab): one connection at a time, FC 1–6/15/16, reads decoded per datatype + word order, optional repeating poll. `/api/master/*` routes; `ModbusMaster` runs on the same asyncio loop.

**UI migration in progress (see `doc/tauri移行計画.md`).** The PySide6 GUI has been removed. The app is now:

- **Backend** (`modbus_sim/`, Python): pymodbus core + a FastAPI/WebSocket API layer (`modbus_sim/api/`). Runs as a sidecar started by `python -m modbus_sim` / `python main.py`. In production it also serves `frontend/dist` at `/`.
- **Frontend** (`frontend/`, React 18 + TypeScript + Vite): the 4 tabs (通信設定 / TCP スレーブ / RTU スレーブ / 通信ログ). Talks to the backend over same-origin `/api` + `/ws`; `frontend/vite.config.ts` proxies both to `http://127.0.0.1:8000` in dev. Zustand store (`src/store.ts`) holds all state and owns the reconnecting WebSocket. `src/datatype.ts` is the TS port of the Python decode/encode (tested in `src/datatype.test.ts`).
- **Shell** (`src-tauri/`, Tauri v2): implemented. `src/lib.rs` picks a free port, spawns the `modbus-sim-backend` sidecar (`--host 127.0.0.1 --port <n>`), waits for the port, then opens a window at `http://127.0.0.1:<n>/`; kills the sidecar on exit. The sidecar exe bundles `frontend/dist` (via `modbus-sim.spec` `datas`) so it serves the SPA + API same-origin — no port injection / CSP work needed.
  **`tauri build` cannot run on this machine**: Windows Smart App Control is enforced and blocks cargo's unsigned build-script executables (`os error 4551`). Build via `.github/workflows/build-desktop.yml` (windows-latest, no SAC), or turn Smart App Control off locally (re-enabling needs a Windows reset). The PyInstaller backend exe builds fine under SAC.

The backend is also usable on its own via HTTP (`GET /api/state`, `/ws`, …).

### Building the desktop app

```bash
npm --prefix frontend ci && npm --prefix frontend run build   # frontend/dist
python scripts/build-backend.py                                # -> src-tauri/binaries/modbus-sim-backend-<triple>.exe
npm ci && npx tauri build                                      # -> src-tauri/target/release/bundle/nsis/*.exe
```

**Do not use `window.confirm` / `window.alert` in the frontend** — they freeze the WebView. Use the store's `askConfirm(msg)` (renders `<Modal>` from `App.tsx`) and `setError(msg)` instead.

The project's working language is Japanese: commit messages, docstrings, comments, UI strings, and error messages are all Japanese. Match that when editing.

## Commands

```bash
python main.py --open                 # start backend + open the UI in the default browser (one command)
python main.py --port 8000            # run the backend API on a fixed port, no browser
python -m modbus_sim --port 0         # same; --port 0 = OS-assigned, printed as JSON on stdout

# Tests — no Qt anymore, so no QT_QPA_PLATFORM needed
python -m pytest tests/ -v
python -m pytest tests/test_datatypes.py -v      # one file
python -m pytest tests/ -k rtu                   # by name
python -m pytest tests/test_api.py -v            # API-layer tests (FastAPI TestClient)

# Frontend (from frontend/)
npm install
npm run dev            # Vite dev server on :5173, proxies /api + /ws to :8000
npm run build          # -> frontend/dist  (the backend serves this at / in production)
npm test               # vitest — datatype.test.ts
```

Dev loop: `python main.py --port 8000` in one shell, `npm --prefix frontend run dev` in another, open http://localhost:5173.

pytest config lives in `pyproject.toml` (`asyncio_mode = "auto"`, so `async def test_*` needs no decorator; `testpaths = ["tests"]`). Test deps beyond `requirements.txt`: `pip install -e ".[test]"` (adds `pytest`, `pytest-asyncio`, `httpx`).

There is no configured linter/formatter (the `# noqa` comments are aspirational).

### Build the backend executable (PyInstaller)

```bash
pip install -e ".[build]"      # adds pyinstaller
pyinstaller modbus-sim.spec    # -> dist/modbus-sim-backend(.exe)
```

PyInstaller cannot cross-compile — build on the target OS. `console=True` in the spec so Tauri can read the sidecar's stdout (port announcement) and stderr. The Tauri build then bundles this binary as an `externalBin` (renamed with the `-<target-triple>` suffix).

## Architecture

### Process / async model

- One process, one `asyncio` event loop (uvicorn's). Every pymodbus server and coroutine runs on it — there is no separate thread anymore (the old `AsyncRunner` is gone).
- `modbus_sim/api/server.py::create_app()` builds the FastAPI app. A background `poller()` task runs every `AppState.POLL_INTERVAL_SEC` (0.4 s): advances auto-changing register values for both registries, `sync_from_server()`, recomputes activity, and broadcasts deltas over `/ws` (`modbus_sim/api/hub.py`).
- `modbus_sim/api/state.py::AppState` holds the registries, the `ModbusServerManager`, `CommSettings`, the `SettingsStore`, dirty flags, and all snapshot/serialization helpers (`point_to_dict`, `full_state`, …).
- Server-manager callbacks (`on_log`, `on_tcp_state_change`, …) just set dirty flags; the poller does the actual broadcasting.

### Data layer (`modbus_sim/datastore.py`, the core file)

Module globals: `tcp_registry` and `rtu_registry` are two independent `SlaveRegistry` instances. `registry` / `tcp_registry` are the same object (back-compat alias). `AppState` uses these module globals directly.

```
SlaveRegistry            per comm mode; holds slaves, tags, activity timestamps, selection
  └─ SlaveDatastore      per slave_id; owns full 65536-length memory arrays per kind
       └─ RegisterPoint  per (address, kind); the user-edited row (raw, datatype, tag, faults, auto)
```

- `SlaveDatastore` builds pymodbus `SimDevice`/`SimData` covering the **entire** register space as a single block per kind. This is deliberate: points added while the server is running stay readable (no `ILLEGAL ADDRESS`). See the comment in `_simdata_for_kind`.
- `bind_runtime` / `unbind_runtime` link a datastore to a running server's block lists. Writes are mirrored **both** into the datastore's own memory arrays **and** into the live server block lists.
- `make_action()` returns the async callback pymodbus invokes per request. It:
  - applies fault injection via `_apply_faults` (response delay, forced exception code, or `NO_RESPONSE` hang that a disconnect/stop cancels),
  - copies register/coil state between datastore memory and the server's block arrays,
  - mirrors client writes back into `RegisterPoint.raw`.
- Coils / discrete inputs are stored as full `bool` arrays and packed into 16-bit registers via `SimUtils.bitsToRegisters`, with block-start offset handling in `_sync_bits_to_registers`.
- Multi-register datatypes: `INT32` / `FLOAT32` span 2 registers, `FLOAT64` spans 4. Word/byte order is **per-slave** (`SlaveDatastore.word_order`, `WordOrder` enum `ABCD`/`CDAB`/`BADC`/`DCBA` in `modbus_sim/wordorder.py`; `ABCD` = big-endian = the legacy behavior). `_write_raw` / `raw_from_memory(word_order=)` / `format_decoded_display` / `parse_decoded_input` all take it; `set_word_order` rewrites existing multi-register points. `ValueKind.register_span` / `is_float` drive the generic paths. Address must be ≤ `REGISTER_COUNT - span`. `validate_datatype_value` rejects out-of-range ints/floats before `struct.pack` can raise. Fault and auto-change features apply to **Holding/Input Registers only**.
- Per-slave fault knobs beyond per-register: `frame_fault` / `frame_fault_rate` (`FrameFault` enum `none`/`bad_crc`/`truncate`/`drop`) — `server_manager`'s TX `trace_packet` hook calls `packet_log.corrupt_frame()` with probability `rate` on outgoing frames for that device id.
- Device identification (FC 43) is server-wide: `modbus_sim/identity.py::DeviceIdentity` → `ModbusDeviceIdentification` passed to `start_tcp` / `start_rtu`. FC 8 (Diagnostics) is handled by pymodbus with no extra config.
- `raw` (decimal, in memory) vs "decoded" (hex display); `parse_decoded_input` accepts `0x1234`, `1234h`, or bare `1234` — all hex. Floats: the decoded hex is the IEEE-754 bit pattern (8 / 16 hex digits).

### Server lifecycle (`server_manager.py`, `logging_handler.py`)

- `ModbusServerManager` starts/stops `LoggingModbusTcpServer` / `LoggingModbusSerialServer` on the async loop. `slave_registry=` kwarg is a test shim that points TCP and RTU at one registry.
- On start failure (e.g. port in use) it intentionally does **not** assign `self._tcp_server` / `_rtu_server`, so `*_running` doesn't get stuck True. There are regression tests for this (`test_server_manager_robustness.py`).
- `logging_handler.py` subclasses the pymodbus server + request handler to detect malformed **TCP** MBAP frames (protocol id ≠ 0, bad length) and emit `INVALID` log lines. This check is TCP-only — applying it to RTU misreads the slave address as a protocol id and drops valid frames (fixed in commit `3bfffe6`).
- `packet_log.py` is pure functions: summarize a Modbus ADU into a human log line, detect invalid frames. Trace callbacks in `server_manager.py` also call `registry.touch_activity(slave_id)` to drive the green/grey status dots (`ACTIVITY_TIMEOUT_SEC = 3.0`).

### Settings

- `settings_store.py` — thin JSON read/write only (`load()`, `write_payload()`). Persisted to `~/.modbus_sim/settings.json` (`%USERPROFILE%\.modbus_sim\settings.json` on Windows). Keys: `tcp`, `rtu`, `tcp_slaves`, `rtu_slaves`, `tcp_selected_slave_id`, `rtu_selected_slave_id`. A legacy top-level `slaves` key is migrated into the TCP registry.
- `settings_model.py` — Qt-free `CommSettings` ⇔ dict conversion (`comm_to_dict`, `apply_dict_to_comm`, defensively coded against corrupt values) plus `comm_to_tcp_config` / `comm_to_rtu_config` (validation that raises `ValueError` with a Japanese message).
- `AppState.schedule_save()` debounces 500 ms and offloads the JSON write with `asyncio.to_thread`.

### Frontend grid

`frontend/src/components/RegisterGrid.tsx` virtualizes rows with `@tanstack/react-virtual` (fixed 30px rows, padding-`<tr>` pattern; `.grid-wrap` is the bounded scroll container). Cells are `EditableCell` — controlled, but only re-sync from the server value while **not focused**, so poller ticks don't clobber in-progress edits. `datatype.ts` mirrors `datastore.py` + `wordorder.py` (tested in `datatype.test.ts`).

### Register bulk ops (`registry_ops.py`)

Qt-free pure functions extracted from the old slave panel: `add_register_range`, `import_register_map_text` (CSV/TSV/clipboard parsing), `duplicate_points`, `next_free_address`, `parse_kind` / `parse_datatype`, `datatype_choices_for`. Used by the API layer.

### API layer (`modbus_sim/api/`)

- `server.py` — `create_app()`, all REST routes (`/api/state`, `/api/settings`, `/api/slaves/{mode}` CRUD, `/api/slaves/{mode}/{id}/points` CRUD + `range` / `import` / `duplicate`, `/api/server/{mode}/start|stop`, `/api/log/clear`), `/ws`, lifespan (starts/stops the poller and the modbus servers). `{mode}` = `tcp`|`rtu`, `{kind}` slug = `hr`|`ir`|`coil`|`di`. Request bodies are pydantic models; `_apply_point_body` rebuilds a `RegisterPoint` via `dataclasses.replace` so a partial edit keeps advanced (fault/delay/auto) settings.
- `state.py` — `AppState`, kind-slug mapping, `point_to_dict`.
- `hub.py` — WebSocket connection set + `broadcast()`.
- `__main__.py` — argparse (`--host` / `--port`, `--port 0` = OS-assigned), prints `{"event":"listening","port":…}` on stdout, mounts `frontend/dist` at `/` if present, runs uvicorn.

### Platform helpers

`platform_util.py` — OS detection; `privileged_tcp_ports_restricted()` blocks ports < 1024 on Linux/WSL (enforced in `settings_model.comm_to_tcp_config`). The old WSL Qt bootstrap (`xcb_util.py`, `fonts_util.py`) is gone — Tauri uses the OS-native WebView.

## Tests

`tests/` covers datastore/datatypes, strict boundary checks (`test_strict.py` — also port-policy via `settings_model`), comm-log formatting, RTU over pymodbus `NULLMODEM_HOST`, live register updates after server start, delete ops (datastore level), bulk register ops (`registry_ops` unit tests), advanced fault/delay/auto settings (datastore + API), settings robustness (`settings_model` + `SettingsStore`), the API layer (`test_api.py`, FastAPI `TestClient`), word/byte order (`test_wordorder.py`), device identification / FC 8 (`test_identity.py`), and packet-level frame faults (`test_frame_fault.py`). TCP tests allocate ports from `itertools.count` starting around 16000–19100. ~207 pass.

Known pre-existing failure (not caused by the migration): `test_server_manager_robustness.py::test_tcp_running_state_recovers_after_bind_failure` — Windows lets the second bind to a loopback port succeed, so the expected error isn't raised.

Frontend tests: `frontend/src/datatype.test.ts` (vitest) checks the decode/encode port against the same cases as `test_datatypes.py` / `test_strict.py`. Tauri tests do not exist yet.
