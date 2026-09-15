# -*- coding: utf-8 -*-
from scripts import command_bus


def setup_function(fn):
    command_bus._HANDLERS.clear()


def test_dispatch_calls_registered_handler():
    seen = []
    command_bus.register(seen.append)
    command_bus.dispatch({"action": "move_to", "param": {"marker_id": "Landmark1"}})
    assert seen == [{"action": "move_to", "param": {"marker_id": "Landmark1"}}]


def test_dispatch_swallows_handler_exception():
    def bad(_cmd):
        raise RuntimeError("boom")

    seen = []
    command_bus.register(bad)
    command_bus.register(seen.append)
    command_bus.dispatch({"action": "talk", "param": ""})
    assert seen == [{"action": "talk", "param": ""}]


def test_register_no_duplicates():
    handler = lambda c: None
    command_bus.register(handler)
    command_bus.register(handler)
    assert command_bus._HANDLERS.count(handler) == 1
