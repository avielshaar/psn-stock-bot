"""End to end: real AmazonClient + real Telegram/Green API notifiers against local mock servers."""
import copy

import pytest

from psnbot.amazon import AmazonClient
from psnbot.config import DEFAULTS
from psnbot.monitor import Monitor
from psnbot.notifiers import GreenApiNotifier, NotifierGroup, TelegramNotifier
from psnbot.state import StateStore
from mock_servers import MockWorld, fixture


@pytest.fixture
def world():
    w = MockWorld().start()
    yield w
    w.stop()


def build(world, tmp_path):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["monitor"].update(confirm_checks=2, realert_cooldown_seconds=0,
                          state_file=str(tmp_path / "state.json"))
    cfg["products"] = [{"asin": "B07K6RYVHR", "label": "₹1000"},
                       {"asin": "B07K6PVR8B", "label": "₹3000"}]
    notifiers = NotifierGroup([
        TelegramNotifier("TOKEN123", ["-1001"], api_url=world.url),
        GreenApiNotifier("1101", "WATOKEN", ["972500000000-1234@g.us"], api_url=world.url),
    ])
    mon = Monitor(cfg, AmazonClient(world.url), notifiers, StateStore(cfg["monitor"]["state_file"]),
                  sleep=lambda s: None)
    return mon


def test_full_flow(world, tmp_path):
    world.pages["B07K6RYVHR"] = (200, fixture("oos.html"))
    world.pages["B07K6PVR8B"] = (200, fixture("oos.html"))
    mon = build(world, tmp_path)
    mon.run_once()
    assert world.requests == []                              # nothing in stock -> silence

    world.pages["B07K6RYVHR"] = (200, fixture("instock.html"))   # stock appears
    mon.run_once()
    paths = [p for p, _ in world.requests]
    assert "/botTOKEN123/sendMessage" in paths
    assert "/waInstance1101/sendMessage/WATOKEN" in paths
    tg = next(d for p, d in world.requests if p.endswith("/sendMessage") and "bot" in p)
    wa = next(d for p, d in world.requests if "waInstance" in p)
    assert tg["chat_id"] == "-1001" and "<b>" in tg["text"] and "B07K6RYVHR" in tg["text"]
    assert wa["chatId"].endswith("@g.us") and "₹1,000.00" in wa["message"]
    n = len(world.requests)

    mon.run_once()                                           # still in stock -> no duplicates
    assert len(world.requests) == n

    # state survives restart: new Monitor, same state file, still no duplicate alert
    mon2 = build(world, tmp_path)
    mon2.run_once()
    assert len(world.requests) == n


def test_captcha_from_server_backs_off(world, tmp_path):
    world.pages["B07K6RYVHR"] = (503, fixture("captcha.html"))
    mon = build(world, tmp_path)
    assert mon.run_once() is True
    assert world.requests == []


def test_notification_failure_is_retried(world, tmp_path):
    world.pages["B07K6RYVHR"] = (200, fixture("instock.html"))
    world.pages["B07K6PVR8B"] = (200, fixture("oos.html"))
    world.fail_notify = True
    mon = build(world, tmp_path)
    mon.run_once()
    assert mon.store.get("B07K6RYVHR")["alerted"] is False
    world.fail_notify = False
    before = len(world.requests)
    mon.run_once()
    assert len(world.requests) > before
    assert mon.store.get("B07K6RYVHR")["alerted"] is True
