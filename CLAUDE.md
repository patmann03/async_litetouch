# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Home Assistant custom integration for Savant SSL-P018 / 5000LC LiteTouch lighting controllers. It communicates over TCP using the LiteTouch RTC ASCII protocol (comma-delimited messages terminated with `\r`). The integration is `iot_class: local_push` — the controller pushes state updates; HA does not poll.

The integration lives entirely under `litetouch/` and is installed by symlinking or copying that directory into a Home Assistant `custom_components/litetouch/` folder.

## Configuration

Lights are configured via `configuration.yaml` (YAML-only, no config flow). See `litetouch/yaml_config.yaml` for a full working example. Required per-light fields: `name`, `module` (4-digit hex string), `output` (0–7). Optional: `loadid` (1-based; stored internally as 0-based), `station`, `button`, `location`, `floor`, `ltcode`.

## Architecture

```
litetouch/
  __init__.py          # async_setup: reads YAML config, creates bridge + entities
  light.py             # LiteTouchLightEntity (HomeAssistant LightEntity)
  litetouch_bridge.py  # LiteTouchBridge: module-level cache, push fan-out
  litetouch_rtc.py     # LiteTouchClient + _LiteTouchTransport: TCP protocol
  services.py          # HA service registrations
  const.py             # Config key constants
```

### Layer responsibilities

**`_LiteTouchTransport`** (in `litetouch_rtc.py`): One persistent TCP connection. Runs a reader task that reads until `\r`. Maintains a list of `(matcher, future)` waiters — `request()` registers a waiter then calls `send()`. Unsolicited messages that match no waiter are dispatched to `on_message`. Includes exponential-backoff auto-reconnect and a keepalive loop (default 15s, sends `R,SIEVN,7`).

**`LiteTouchClient`** (in `litetouch_rtc.py`): Pool of `_LiteTouchTransport` instances. Commands are round-robined across `command_connections` transports. An optional dedicated `event` transport receives unsolicited notifications (RMODU, RLEDU, REVNT) without competing with command ACKs.

**`LiteTouchBridge`** (in `litetouch_bridge.py`): Owns `LiteTouchClient`. Maintains `_module_levels: Dict[int, List[int]]` — a per-module cache of 8 output levels (0–100, -1 = unknown). On push update (`RMODU`), updates cache and fires all registered listener callbacks. `set_output_level()` uses sparse DSMLV (only the targeted output's bit is set in the bitmap). `ensure_module_cached()` issues a DGMLV query if no cache exists yet.

**`LiteTouchLightEntity`** (in `light.py`): Standard HA `LightEntity`. On `async_added_to_hass`, enables SMODN notifications for its module and seeds the cache. Registers a listener on the bridge; when its module updates, refreshes from cache and calls `async_write_ha_state()`. Brightness is HA 0–255 ↔ LiteTouch 0–100 (helpers `pct_to_ha` / `ha_to_pct` in bridge).

**`services.py`**: Registers HA services under the `litetouch` domain: `set_clock`, `set_module_levels`, `toggle_switch`, `set_load_on`, `set_load_off`, `set_load_level`.

### Protocol notes

- All messages: `R,<CMD>[,args...]\r`
- Response kinds: `RCACK` (write ACK), `RDACK` (data write ACK), `RQRES` (query result), `RMODU` (module level push), `RLEDU` (LED state push), `REVNT` (event)
- `loadid` in config is 1-based; stored/sent as 0-based (adjusted in `LiteTouchLightEntity.__init__`)
- `rtc_backup.py` is an older version of `litetouch_rtc.py` kept for reference; it is not imported anywhere

## HA Services Available

| Service | Parameters |
|---|---|
| `litetouch.set_clock` | none (uses HA local time) |
| `litetouch.toggle_switch` | `switch` (ssso string) |
| `litetouch.set_load_on` | `loadid` (int) |
| `litetouch.set_load_off` | `loadid` (int) |
| `litetouch.set_load_level` | `loadid` (int), `brightness_level` (int) |
| `litetouch.set_module_levels` | `module`, `bitmap`, `ramp`, `levels` |