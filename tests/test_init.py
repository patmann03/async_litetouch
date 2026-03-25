"""Tests for litetouch/__init__.py — integration setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


class TestAsyncSetupEntry:
    async def test_creates_bridge_with_correct_host_port(
        self, mock_hass, mock_config_entry
    ):
        from litetouch import async_setup_entry
        from litetouch.const import DOMAIN

        with patch("litetouch.LiteTouchBridge") as MockBridge:
            mock_bridge = AsyncMock()
            MockBridge.return_value = mock_bridge
            mock_hass.data = {}

            await async_setup_entry(mock_hass, mock_config_entry)

            MockBridge.assert_called_once()
            call_args = MockBridge.call_args
            assert call_args[0][0] == "10.0.0.1"  # host
            assert call_args[0][1] == 10001        # port

    async def test_starts_bridge(self, mock_hass, mock_config_entry):
        from litetouch import async_setup_entry
        from litetouch.const import DOMAIN

        with patch("litetouch.LiteTouchBridge") as MockBridge:
            mock_bridge = AsyncMock()
            MockBridge.return_value = mock_bridge
            mock_hass.data = {}

            await async_setup_entry(mock_hass, mock_config_entry)

            mock_bridge.start.assert_awaited_once()

    async def test_stores_bridge_in_hass_data(self, mock_hass, mock_config_entry):
        from litetouch import async_setup_entry
        from litetouch.const import DOMAIN

        with patch("litetouch.LiteTouchBridge") as MockBridge:
            mock_bridge = AsyncMock()
            MockBridge.return_value = mock_bridge
            mock_hass.data = {}

            await async_setup_entry(mock_hass, mock_config_entry)

            assert DOMAIN in mock_hass.data
            assert "test_entry_id" in mock_hass.data[DOMAIN]
            assert mock_hass.data[DOMAIN]["test_entry_id"]["bridge"] is mock_bridge

    async def test_registers_services(self, mock_hass, mock_config_entry):
        from litetouch import async_setup_entry

        with patch("litetouch.LiteTouchBridge") as MockBridge:
            mock_bridge = AsyncMock()
            MockBridge.return_value = mock_bridge
            mock_hass.data = {}

            await async_setup_entry(mock_hass, mock_config_entry)

            # At least one service should have been registered
            assert mock_hass.services.async_register.call_count >= 1

    async def test_forwards_setup_to_light_platform(self, mock_hass, mock_config_entry):
        from litetouch import async_setup_entry

        with patch("litetouch.LiteTouchBridge") as MockBridge:
            mock_bridge = AsyncMock()
            MockBridge.return_value = mock_bridge
            mock_hass.data = {}

            await async_setup_entry(mock_hass, mock_config_entry)

            mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
                mock_config_entry, ["light"]
            )

    async def test_registers_shutdown_handler(self, mock_hass, mock_config_entry):
        from litetouch import async_setup_entry

        with patch("litetouch.LiteTouchBridge") as MockBridge:
            mock_bridge = AsyncMock()
            MockBridge.return_value = mock_bridge
            mock_hass.data = {}

            await async_setup_entry(mock_hass, mock_config_entry)

            mock_config_entry.async_on_unload.assert_called()

    async def test_returns_true(self, mock_hass, mock_config_entry):
        from litetouch import async_setup_entry

        with patch("litetouch.LiteTouchBridge") as MockBridge:
            mock_bridge = AsyncMock()
            MockBridge.return_value = mock_bridge
            mock_hass.data = {}

            result = await async_setup_entry(mock_hass, mock_config_entry)

            assert result is True


# ---------------------------------------------------------------------------
# async_unload_entry
# ---------------------------------------------------------------------------


class TestAsyncUnloadEntry:
    def _setup_hass_data(self, mock_hass, mock_config_entry, bridge):
        from litetouch.const import DOMAIN
        mock_hass.data = {DOMAIN: {"test_entry_id": {"bridge": bridge, "config": mock_config_entry}}}

    async def test_stops_bridge(self, mock_hass, mock_config_entry):
        from litetouch import async_unload_entry

        mock_bridge = AsyncMock()
        self._setup_hass_data(mock_hass, mock_config_entry, mock_bridge)

        await async_unload_entry(mock_hass, mock_config_entry)

        mock_bridge.stop.assert_awaited_once()

    async def test_unloads_light_platform(self, mock_hass, mock_config_entry):
        from litetouch import async_unload_entry

        mock_bridge = AsyncMock()
        self._setup_hass_data(mock_hass, mock_config_entry, mock_bridge)

        await async_unload_entry(mock_hass, mock_config_entry)

        mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(
            mock_config_entry, ["light"]
        )

    async def test_removes_entry_from_hass_data_on_success(
        self, mock_hass, mock_config_entry
    ):
        from litetouch import async_unload_entry
        from litetouch.const import DOMAIN

        mock_bridge = AsyncMock()
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        self._setup_hass_data(mock_hass, mock_config_entry, mock_bridge)

        await async_unload_entry(mock_hass, mock_config_entry)

        assert "test_entry_id" not in mock_hass.data.get(DOMAIN, {})

    async def test_calls_unload_services_when_last_entry(
        self, mock_hass, mock_config_entry
    ):
        from litetouch import async_unload_entry
        from litetouch.const import DOMAIN

        mock_bridge = AsyncMock()
        # Only one entry — after removal, no entries remain
        mock_hass.data = {
            DOMAIN: {"test_entry_id": {"bridge": mock_bridge, "config": mock_config_entry}}
        }

        with patch("litetouch.async_unload_services") as mock_unload_svc:
            await async_unload_entry(mock_hass, mock_config_entry)
            mock_unload_svc.assert_called_once_with(mock_hass)

    async def test_skips_unload_services_when_other_entries_remain(
        self, mock_hass, mock_config_entry
    ):
        from litetouch import async_unload_entry
        from litetouch.const import DOMAIN

        mock_bridge = AsyncMock()
        other_bridge = AsyncMock()
        # Two entries — one remains after this unload
        mock_hass.data = {
            DOMAIN: {
                "test_entry_id": {"bridge": mock_bridge, "config": mock_config_entry},
                "other_entry": {"bridge": other_bridge, "config": MagicMock()},
            }
        }

        with patch("litetouch.async_unload_services") as mock_unload_svc:
            await async_unload_entry(mock_hass, mock_config_entry)
            mock_unload_svc.assert_not_called()

    async def test_returns_unload_ok(self, mock_hass, mock_config_entry):
        from litetouch import async_unload_entry

        mock_bridge = AsyncMock()
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        self._setup_hass_data(mock_hass, mock_config_entry, mock_bridge)

        result = await async_unload_entry(mock_hass, mock_config_entry)
        assert result is True


# ---------------------------------------------------------------------------
# async_setup (YAML import path)
# ---------------------------------------------------------------------------


class TestAsyncSetup:
    async def test_yaml_config_triggers_import_flow(self, mock_hass):
        from litetouch import async_setup
        from litetouch.const import DOMAIN

        config = {DOMAIN: {"host": "10.0.0.1", "port": 10001}}
        result = await async_setup(mock_hass, config)

        assert result is True
        mock_hass.async_create_task.assert_called()

    async def test_no_domain_config_returns_true(self, mock_hass):
        from litetouch import async_setup
        from litetouch.const import DOMAIN

        result = await async_setup(mock_hass, {})
        assert result is True
        mock_hass.async_create_task.assert_not_called()
