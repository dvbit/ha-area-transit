"""Minimal Home Assistant stubs so the detection logic can be tested anywhere.

The state machine (`gate.py`) and the chain detector (`chain.py`) only use a
handful of Home Assistant primitives: a clock, a delayed-call helper and a
state-change subscription. Stubbing those keeps the tests fast, deterministic
and runnable without a Home Assistant installation, while still exercising the
real production code.

Full integration tests (config flow, entities, restore) belong to
`pytest-homeassistant-custom-component` and are out of scope here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import sys
import types
from typing import Any

import pytest

REPO_ROOT = __file__.rsplit("/tests/", 1)[0]
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

_EPOCH = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class Clock:
    """Controllable clock shared by the stubs."""

    def __init__(self) -> None:
        """Start the clock at a fixed instant."""
        self.now = _EPOCH


CLOCK = Clock()


@dataclass
class _Timer:
    """A pending `async_call_later` callback."""

    fire_at: datetime
    action: Callable[[datetime], None]
    cancelled: bool = False


@dataclass
class FakeHass:
    """Stand-in for `HomeAssistant`, exposing only what the code needs."""

    timers: list[_Timer] = field(default_factory=list)
    listeners: dict[str, list[Callable[[Any], None]]] = field(default_factory=dict)

    def advance(self, seconds: float) -> None:
        """Move the clock forward, firing every timer due in the interval."""
        target = CLOCK.now + timedelta(seconds=seconds)
        while True:
            due = [t for t in self.timers if not t.cancelled and t.fire_at <= target]
            if not due:
                break
            timer = min(due, key=lambda t: t.fire_at)
            CLOCK.now = timer.fire_at
            timer.cancelled = True
            self.timers.remove(timer)
            timer.action(CLOCK.now)
        CLOCK.now = target

    def fire(self, entity_id: str, new: str = "on", old: str = "off") -> None:
        """Push a state change event to whoever subscribed to `entity_id`."""
        event = types.SimpleNamespace(
            data={
                "entity_id": entity_id,
                "new_state": types.SimpleNamespace(state=new),
                "old_state": types.SimpleNamespace(state=old)
                if old is not None
                else None,
            }
        )
        for action in list(self.listeners.get(entity_id, ())):
            action(event)


def _install_stubs() -> None:
    """Register the fake `homeassistant.*` modules in `sys.modules`."""

    def module(name: str, **attrs: Any) -> types.ModuleType:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    def passthrough(func):
        """Stand-in for `@callback`, which is a no-op marker at runtime."""
        return func

    ha = module("homeassistant")
    ha.__path__ = []  # type: ignore[attr-defined]

    module(
        "homeassistant.core",
        CALLBACK_TYPE=Callable[[], None],
        Event=object,
        EventStateChangedData=dict,
        HomeAssistant=FakeHass,
        callback=passthrough,
    )

    class _Platform(StrEnum):
        """Subset of `homeassistant.const.Platform`."""

        SENSOR = "sensor"

    module("homeassistant.const", STATE_ON="on", CONF_NAME="name", Platform=_Platform)

    class _Subscriptable:
        """Base class accepting `Class[T]` subscripting like the real ones."""

        def __class_getitem__(cls, _item: Any) -> type:
            return cls

    class _ConfigSubentry(_Subscriptable):  # pragma: no cover - typing only
        data: dict[str, Any]
        subentry_id: str
        title: str

    class _ConfigEntry(_Subscriptable):  # pragma: no cover - typing only
        pass

    module(
        "homeassistant.config_entries",
        ConfigSubentry=_ConfigSubentry,
        ConfigEntry=_ConfigEntry,
    )

    helpers = module("homeassistant.helpers")
    helpers.__path__ = []  # type: ignore[attr-defined]
    module("homeassistant.helpers.area_registry", async_get=lambda hass: None)

    def async_call_later(hass: FakeHass, delay, action):
        """Queue a callback and return its unsubscribe function."""
        seconds = delay.total_seconds() if hasattr(delay, "total_seconds") else delay
        timer = _Timer(fire_at=CLOCK.now + timedelta(seconds=seconds), action=action)
        hass.timers.append(timer)

        def _cancel() -> None:
            timer.cancelled = True
            if timer in hass.timers:
                hass.timers.remove(timer)

        return _cancel

    def async_track_state_change_event(hass: FakeHass, entity_ids, action):
        """Subscribe `action` to the given entities."""
        for entity_id in entity_ids:
            hass.listeners.setdefault(entity_id, []).append(action)

        def _cancel() -> None:
            for entity_id in entity_ids:
                hass.listeners[entity_id].remove(action)

        return _cancel

    module(
        "homeassistant.helpers.event",
        async_call_later=async_call_later,
        async_track_state_change_event=async_track_state_change_event,
    )

    util = module("homeassistant.util")
    util.__path__ = []  # type: ignore[attr-defined]
    module("homeassistant.util.dt", utcnow=lambda: CLOCK.now)


_install_stubs()


@pytest.fixture
def hass() -> FakeHass:
    """Return a fresh fake hass with the clock reset."""
    CLOCK.now = _EPOCH
    return FakeHass()
