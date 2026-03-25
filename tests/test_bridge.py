"""Tests for litetouch/litetouch_bridge.py — helpers, cache, listeners, connection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from litetouch.litetouch_bridge import (
    LiteTouchBridge,
    bitmask_for_output,
    ha_to_pct,
    pct_to_ha,
)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


class TestPctToHa:
    def test_zero(self):
        assert pct_to_ha(0) == 0

    def test_negative(self):
        assert pct_to_ha(-5) == 0

    def test_one(self):
        # 1 * 255 / 100 = 2.55 → rounds to 3, clamped to max(1, 3) = 3
        assert pct_to_ha(1) >= 1

    def test_fifty(self):
        # 50 * 255 / 100 = 127.5 → 128
        assert pct_to_ha(50) == 128

    def test_hundred(self):
        assert pct_to_ha(100) == 255

    def test_result_never_zero_for_positive(self):
        for v in range(1, 101):
            assert pct_to_ha(v) >= 1

    def test_max_clamped_to_255(self):
        assert pct_to_ha(100) == 255


class TestHaToPct:
    def test_zero(self):
        assert ha_to_pct(0) == 0

    def test_negative(self):
        assert ha_to_pct(-1) == 0

    def test_one(self):
        assert ha_to_pct(1) >= 1

    def test_midpoint(self):
        # 128 * 100 / 255 ≈ 50.2 → 50
        assert ha_to_pct(128) == 50

    def test_max(self):
        assert ha_to_pct(255) == 100

    def test_result_never_zero_for_positive(self):
        for v in range(1, 256):
            assert ha_to_pct(v) >= 1

    def test_max_clamped_to_100(self):
        assert ha_to_pct(255) == 100


class TestBitmaskForOutput:
    def test_output_0(self):
        assert bitmask_for_output(0) == "01"

    def test_output_1(self):
        assert bitmask_for_output(1) == "02"

    def test_output_3(self):
        assert bitmask_for_output(3) == "08"

    def test_output_7(self):
        assert bitmask_for_output(7) == "80"

    def test_output_4(self):
        assert bitmask_for_output(4) == "10"

    def test_result_is_hex_string(self):
        result = bitmask_for_output(2)
        assert isinstance(result, str)
        int(result, 16)  # must be parseable as hex


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------


class TestBridgeConnectionState:
    def test_connected_false_initially(self, real_bridge):
        assert real_bridge.connected is False

    def test_connected_true_after_change(self, real_bridge):
        real_bridge._on_connection_change(True)
        assert real_bridge.connected is True

    def test_connected_false_after_disconnect(self, real_bridge):
        real_bridge._on_connection_change(True)
        real_bridge._on_connection_change(False)
        assert real_bridge.connected is False

    def test_add_connection_listener_called_on_change(self, real_bridge):
        states: list = []
        real_bridge.add_connection_listener(lambda c: states.append(c))

        real_bridge._on_connection_change(True)
        real_bridge._on_connection_change(False)

        assert states == [True, False]

    def test_remove_connection_listener_stops_calls(self, real_bridge):
        states: list = []
        remove = real_bridge.add_connection_listener(lambda c: states.append(c))

        real_bridge._on_connection_change(True)
        remove()
        real_bridge._on_connection_change(False)

        assert states == [True]  # False not received after removal

    def test_connection_listener_exception_does_not_propagate(self, real_bridge):
        def bad_cb(c):
            raise RuntimeError("boom")

        real_bridge.add_connection_listener(bad_cb)
        # Should not raise
        real_bridge._on_connection_change(True)


# ---------------------------------------------------------------------------
# Module cache
# ---------------------------------------------------------------------------


class TestModuleCache:
    async def test_ensure_module_cached_calls_get_module_levels(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [50, 0, 0, 0, 0, 0, 0, 0])
        )
        await real_bridge.ensure_module_cached("0007")
        mock_client.get_module_levels.assert_awaited_once_with("0007")

    async def test_ensure_module_cached_idempotent(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [50, 0, 0, 0, 0, 0, 0, 0])
        )
        await real_bridge.ensure_module_cached("0007")
        await real_bridge.ensure_module_cached("0007")
        # Only called once
        assert mock_client.get_module_levels.await_count == 1

    async def test_ensure_module_cached_pads_to_8(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [50, 75])  # only 2 levels
        )
        await real_bridge.ensure_module_cached("0007")
        module_int = int("0007", 16)
        assert len(real_bridge._module_levels[module_int]) == 8

    async def test_ensure_module_cached_applies_bitmap(self, real_bridge, mock_client):
        # Bitmap 0x01 means only output 0 is ON
        mock_client.get_module_levels = AsyncMock(
            return_value=("01", [80, 50, 0, 0, 0, 0, 0, 0])
        )
        await real_bridge.ensure_module_cached("0007")
        module_int = int("0007", 16)
        cached = real_bridge._module_levels[module_int]
        assert cached[0] == 80  # output 0 — ON in bitmap → level kept
        assert cached[1] == 0   # output 1 — OFF in bitmap → level forced to 0

    def test_get_output_level_pct_returns_cached(self, real_bridge):
        module_int = 7
        real_bridge._module_levels[module_int] = [50, 75, 0, 0, 0, 0, 0, 0]
        assert real_bridge.get_output_level_pct(module_int, 0) == 50
        assert real_bridge.get_output_level_pct(module_int, 1) == 75

    def test_get_output_level_pct_unknown_returns_none(self, real_bridge):
        module_int = 7
        real_bridge._module_levels[module_int] = [-1, 0, 0, 0, 0, 0, 0, 0]
        assert real_bridge.get_output_level_pct(module_int, 0) is None

    def test_get_output_level_pct_missing_module_returns_none(self, real_bridge):
        assert real_bridge.get_output_level_pct(999, 0) is None

    def test_get_output_level_pct_out_of_range_returns_none(self, real_bridge):
        module_int = 7
        real_bridge._module_levels[module_int] = [50] * 8
        assert real_bridge.get_output_level_pct(module_int, -1) is None
        assert real_bridge.get_output_level_pct(module_int, 8) is None


# ---------------------------------------------------------------------------
# Module listeners
# ---------------------------------------------------------------------------


class TestModuleListeners:
    def test_add_listener_registered_and_called(self, real_bridge):
        calls: list = []
        real_bridge.add_listener(lambda m: calls.append(m))
        real_bridge._on_module_update(7, "FF", [50, 0, 0, 0, 0, 0, 0, 0])
        assert calls == [7]

    def test_remove_listener_stops_calls(self, real_bridge):
        calls: list = []
        remove = real_bridge.add_listener(lambda m: calls.append(m))

        real_bridge._on_module_update(7, "FF", [50] * 8)
        remove()
        real_bridge._on_module_update(7, "FF", [50] * 8)

        assert len(calls) == 1

    def test_on_module_update_updates_cache(self, real_bridge):
        real_bridge._on_module_update(7, "FF", [10, 20, 30, 40, 50, 60, 70, 80])
        assert real_bridge._module_levels[7] == [10, 20, 30, 40, 50, 60, 70, 80]

    def test_on_module_update_pads_short_levels(self, real_bridge):
        real_bridge._on_module_update(7, "FF", [50, 75])
        assert len(real_bridge._module_levels[7]) == 8
        assert real_bridge._module_levels[7][2] == -1

    def test_on_module_update_truncates_long_levels(self, real_bridge):
        real_bridge._on_module_update(7, "FF", list(range(12)))
        assert len(real_bridge._module_levels[7]) == 8

    def test_on_module_update_dispatches_all_listeners(self, real_bridge):
        calls1: list = []
        calls2: list = []
        real_bridge.add_listener(lambda m: calls1.append(m))
        real_bridge.add_listener(lambda m: calls2.append(m))

        real_bridge._on_module_update(7, "FF", [50] * 8)

        assert calls1 == [7]
        assert calls2 == [7]

    def test_listener_exception_does_not_stop_others(self, real_bridge):
        calls: list = []

        def bad_cb(m):
            raise RuntimeError("explode")

        real_bridge.add_listener(bad_cb)
        real_bridge.add_listener(lambda m: calls.append(m))

        real_bridge._on_module_update(7, "FF", [50] * 8)

        # Second listener still called despite first raising
        assert calls == [7]


# ---------------------------------------------------------------------------
# set_output_level
# ---------------------------------------------------------------------------


class TestSetOutputLevel:
    async def test_calls_set_module_levels_with_correct_bitmap(
        self, real_bridge, mock_client
    ):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [0, 0, 0, 0, 0, 0, 0, 0])
        )
        await real_bridge.set_output_level("0007", 0, 75)

        mock_client.set_module_levels.assert_awaited_once()
        args = mock_client.set_module_levels.call_args[0]
        assert args[0] == "0007"   # module_hex
        assert args[1] == "01"     # bitmap for output 0
        assert args[3] == [75]     # sparse level

    async def test_updates_cache_with_new_level(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [0, 0, 0, 0, 0, 0, 0, 0])
        )
        await real_bridge.set_output_level("0007", 0, 75)

        module_int = int("0007", 16)
        assert real_bridge._module_levels[module_int][0] == 75

    async def test_uses_default_transition(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [0, 0, 0, 0, 0, 0, 0, 0])
        )
        real_bridge._default_transition = 5
        await real_bridge.set_output_level("0007", 0, 50)

        args = mock_client.set_module_levels.call_args[0]
        assert args[2] == 5  # transition

    async def test_uses_explicit_transition(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [0, 0, 0, 0, 0, 0, 0, 0])
        )
        await real_bridge.set_output_level("0007", 0, 50, transition=10)

        args = mock_client.set_module_levels.call_args[0]
        assert args[2] == 10

    async def test_zero_level_sent_as_zero(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [50, 0, 0, 0, 0, 0, 0, 0])
        )
        await real_bridge.set_output_level("0007", 0, 0)

        args = mock_client.set_module_levels.call_args[0]
        assert args[3] == [0]

    async def test_unknown_cache_level_defaults_to_zero(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [-1, -1, -1, -1, -1, -1, -1, -1])
        )
        await real_bridge.set_output_level("0007", 0, 50)

        args = mock_client.set_module_levels.call_args[0]
        assert args[3] == [50]  # not -1

    async def test_correct_bitmap_for_output_3(self, real_bridge, mock_client):
        mock_client.get_module_levels = AsyncMock(
            return_value=("FF", [0, 0, 0, 0, 0, 0, 0, 0])
        )
        await real_bridge.set_output_level("0007", 3, 60)

        args = mock_client.set_module_levels.call_args[0]
        assert args[1] == "08"  # bitmask for output 3


# ---------------------------------------------------------------------------
# set_module_levels passthrough
# ---------------------------------------------------------------------------


class TestSetModuleLevels:
    async def test_calls_client_set_module_levels(self, real_bridge, mock_client):
        await real_bridge.set_module_levels("0007", "FF", 3, [50, 75])
        mock_client.set_module_levels.assert_awaited_once_with("0007", "FF", 3, [50, 75])


# ---------------------------------------------------------------------------
# Bridge lifecycle
# ---------------------------------------------------------------------------


class TestBridgeLifecycle:
    async def test_start_calls_client_start(self, real_bridge, mock_client):
        mock_client.start = AsyncMock()
        await real_bridge.start()
        mock_client.start.assert_awaited_once()

    async def test_stop_calls_client_close(self, real_bridge, mock_client):
        mock_client.close = AsyncMock()
        await real_bridge.stop()
        mock_client.close.assert_awaited_once()
