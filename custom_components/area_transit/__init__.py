"""The Area Transit integration.

Detects a person moving from one area to another by validating the order in
which the motion sensors of a gate fire, and chains contiguous gates into a
single journey (SPEC.md).

Set-up order matters: the gates are built first (the sensor platform needs
their configuration to create devices and entities), the platforms are
forwarded next, and only then the trackers start listening — so no transit is
detected before an entity is able to record it.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import AreaTransitConfigEntry, AreaTransitManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: AreaTransitConfigEntry) -> bool:
    """Set up Area Transit from the hub config entry."""
    manager = AreaTransitManager(hass, entry)
    manager.async_setup()
    entry.runtime_data = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    manager.async_start()
    entry.async_on_unload(manager.async_shutdown)
    # Adding, editing or removing a gate subentry updates the hub entry:
    # reload so the trackers and the entities match the new configuration.
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    _LOGGER.debug("Config entry '%s' set up", entry.title)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: AreaTransitConfigEntry
) -> bool:
    """Unload the hub config entry and every platform it owns."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _LOGGER.debug("Config entry '%s' unloaded: %s", entry.title, unloaded)
    return unloaded


async def async_update_listener(
    hass: HomeAssistant, entry: AreaTransitConfigEntry
) -> None:
    """Reload the integration after an options or subentry change."""
    _LOGGER.debug("Configuration changed, reloading '%s'", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)
