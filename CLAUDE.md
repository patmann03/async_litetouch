# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant custom component integrating Savant SSL-P018 / 5000LC lighting controllers via the LiteTouch RTC (Real Time Control) TCP protocol. It provides dimmable light entities with push-driven state updates.

## Development Setup

No formal build or test framework is configured. This is a Home Assistant custom component — install it by symlinking or copying `litetouch/` into your HA instance's `custom_components/litetouch/` directory.

Manual testing against a real controller:
```bash
python litetouch/sample.py
```

No linting, type-checking, or CI configuration exists yet.

## Architecture

### Layered Design

```
HA Light Entities + Services + Config Flow
         ↓
   LiteTouchBridge        (litetouch_bridge.py)
   - Module-level cache (8 outputs/module, 0–100%)
   - Listener callbacks for push updates
   - Level conversion: HA 0–255 ↔ LiteTouch 0–100%
         ↓
   LiteTouchClient        (litetouch_rtc.py)
   - Pool of command transports (default 4)
   - Optional separate event transport
         ↓
   _LiteTouchTransport    (litetouch_rtc.py)
   - Single TCP connection
   - Reconnect with exponential backoff
   - Keep-alive heartbeat (15s default)
         ↓
   Savant SSL-P018 / 5000LC controller (TCP)
```

### Key Files

- [litetouch/litetouch_rtc.py](litetouch/litetouch_rtc.py) — Full RTC protocol implementation: message parsing, transport, client API
- [litetouch/litetouch_bridge.py](litetouch/litetouch_bridge.py) — HA-facing bridge: caches module state, dispatches listener updates
- [litetouch/light/light.py](litetouch/light/light.py) — `LiteTouchLightEntity`: push-driven, no polling, brightness-only color mode
- [litetouch/services.py](litetouch/services.py) — Raw HA services (set_clock, set_module_levels, toggle_switch, set_load_*)
- [litetouch/config_flow.py](litetouch/config_flow.py) — Config and Options flows for UI setup
- [litetouch/__init__.py](litetouch/__init__.py) — Integration setup/teardown, registers services

### Protocol

ASCII, comma-delimited, `\r`-terminated over TCP.

| Direction | Command | Description |
|-----------|---------|-------------|
| Send | `DGMLV` | Get module output levels |
| Send | `DSMLV` | Set module outputs (bitmap + sparse levels) |
| Send | `CSLON`/`CSLOF` | Load group on/off |
| Send | `CINLL` | Initialize load brightness |
| Send | `SSWCH` | Simulate keypad button press |
| Send | `STCLK` | Sync clock |
| Send | `SMODN` | Subscribe to module notifications |
| Receive | `RMODU` | Push: module output levels changed |
| Receive | `RLEDU` | Push: keypad LED state changed |
| Receive | `REVNT` | Push: general event |

Responses are matched to waiting commands by the transport; unsolicited notifications are routed to registered callbacks on the event connection.

- All messages: `R,<CMD>[,args...]\r`
- Response kinds: `RCACK` (write ACK), `RDACK` (data write ACK), `RQRES` (query result), `RMODU` (module level push), `RLEDU` (LED state push), `REVNT` (event)
- `loadid` in config is 1-based; stored/sent as 0-based (adjusted in `LiteTouchLightEntity.__init__`)

### Light Configuration

Each light entity is defined by either:
- `module` + `output` (1-indexed output on a specific module), or
- `loadid` (a named load group)

Optional metadata: `station`, `button`, `location`, `floor`, `ltcode`.

The config flow supports adding lights via UI (Options flow) or legacy YAML config.

### State Sync

- On startup, entities call `get_module_levels()` which receives `DGMLV` to seed the bridge cache.
- Live updates arrive as `RMODU` push messages and are dispatched to all registered listeners.
- Commands use `DSMLV` with a bitmap to address specific outputs; off is level 0.