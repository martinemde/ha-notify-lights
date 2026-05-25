"""Tests for the adapter ABC and registry with glob-based model matching."""
from custom_components.notify_lights.adapter import (
    AdapterRegistry,
    NotificationAdapter,
)


class FakeAdapter(NotificationAdapter):
    manufacturer = "Inovelli"
    model_patterns = ["VZM31*"]
    max_concurrent = 7
    supported_effects = set()
    effect_fallbacks = {}

    async def render(self, target, active):
        pass

    async def clear(self, target):
        pass


def test_register_and_lookup():
    registry = AdapterRegistry()
    adapter = FakeAdapter()
    registry.register(adapter)
    assert registry.get_adapter("Inovelli", "VZM31-SN") is adapter


def test_no_match_returns_none():
    registry = AdapterRegistry()
    assert registry.get_adapter("Unknown", "XYZ") is None


def test_glob_matching():
    registry = AdapterRegistry()
    adapter = FakeAdapter()
    registry.register(adapter)
    assert registry.get_adapter("Inovelli", "VZM31-SN v2.18") is adapter
    assert registry.get_adapter("Inovelli", "VZM35-SN") is None
