import copy

from psnbot.amazon import BLOCKED, ERROR, IN_STOCK, OUT_OF_STOCK, UNKNOWN, ProductStatus
from psnbot.config import DEFAULTS
from psnbot.monitor import Monitor
from psnbot.notifiers import Notifier, NotifierGroup
from psnbot.state import StateStore


class FakeClient:
    def __init__(self):
        self.seq = []          # queued states
        self.default = OUT_OF_STOCK
        self.price = "₹1,000.00"

    def product_url(self, asin):
        return f"https://www.amazon.in/dp/{asin}"

    def fetch(self, asin):
        state = self.seq.pop(0) if self.seq else self.default
        return ProductStatus(asin, state, title="Rs.1000 PSN", price=self.price,
                             price_value=float(self.price.replace("₹", "").replace(",", "")),
                             seller="Seller X", reason="fake")


class Rec(Notifier):
    name = "rec"

    def __init__(self, ok=True):
        self.msgs, self.ok = [], ok

    def send(self, text):
        self.msgs.append(text)
        return self.ok


def make(products=None, **over):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["monitor"].update({"confirm_checks": 2, "realert_cooldown_seconds": 0, "state_file": ""})
    cfg["monitor"].update(over)
    cfg["products"] = products or [{"asin": "B1", "label": "₹1000"}]
    client, rec = FakeClient(), Rec()
    t = [1000.0]
    mon = Monitor(cfg, client, NotifierGroup([rec]), StateStore(""),
                  clock=lambda: t[0], sleep=lambda s: None)
    return mon, client, rec, t


def cycle(mon, client, state):
    client.default = state
    return mon.check_product(mon.cfg["products"][0])


def test_alert_on_transition_once():
    mon, c, rec, _ = make()
    cycle(mon, c, OUT_OF_STOCK)
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 1
    assert "https://www.amazon.in/dp/B1" in rec.msgs[0] and "₹1,000.00" in rec.msgs[0]
    cycle(mon, c, IN_STOCK)
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 1                      # no spam while it stays in stock


def test_rearm_after_two_out_reads():
    mon, c, rec, _ = make()
    cycle(mon, c, IN_STOCK)
    cycle(mon, c, OUT_OF_STOCK)                    # single out read: not re-armed yet
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 1
    cycle(mon, c, OUT_OF_STOCK)
    cycle(mon, c, OUT_OF_STOCK)
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 2


def test_confirmation_filters_flapping_read():
    mon, c, rec, _ = make()
    c.seq = [IN_STOCK, OUT_OF_STOCK]               # first read in stock, confirm read says out
    mon.check_product(mon.cfg["products"][0])
    assert rec.msgs == []


def test_quiet_when_already_in_stock_and_alert_on_first_run_false():
    mon, c, rec, _ = make(alert_on_first_run=False)
    cycle(mon, c, IN_STOCK)
    cycle(mon, c, IN_STOCK)
    assert rec.msgs == []
    cycle(mon, c, OUT_OF_STOCK)
    cycle(mon, c, OUT_OF_STOCK)
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 1


def test_alert_on_first_run_true_by_default():
    mon, c, rec, _ = make()
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 1


def test_failed_send_retries_next_cycle():
    mon, c, rec, _ = make()
    rec.ok = False
    cycle(mon, c, IN_STOCK)
    assert mon.store.get("B1")["alerted"] is False
    rec.ok = True
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 2                      # 1 failed attempt + 1 successful


def test_cooldown_delays_alert():
    mon, c, rec, t = make(realert_cooldown_seconds=300)
    mon.store.get("B1")["last_alert"] = t[0] - 10
    cycle(mon, c, IN_STOCK)
    assert rec.msgs == []
    t[0] += 400
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 1


def test_max_price_filter():
    mon, c, rec, _ = make(products=[{"asin": "B1", "label": "x", "max_price": 900}])
    cycle(mon, c, IN_STOCK)
    assert rec.msgs == []
    c.price = "₹850.00"
    cycle(mon, c, IN_STOCK)
    assert len(rec.msgs) == 1


def test_unknown_never_alerts_but_warns_admin_once():
    mon, c, rec, _ = make(health_alert_after=3)
    for _ in range(6):
        cycle(mon, c, UNKNOWN)
    assert len(rec.msgs) == 1 and "PSN stock bot" in rec.msgs[0]


def test_blocked_triggers_backoff_and_single_admin_alert():
    mon, c, rec, _ = make(block_alert_after=2)
    c.default = BLOCKED
    assert mon.run_once() is True
    d1 = mon.next_delay(True)
    mon.run_once()
    mon.run_once()
    assert len([m for m in rec.msgs if "חוסמת" in m]) == 1
    assert mon.next_delay(True) > d1 * 0.5
    c.default = OUT_OF_STOCK
    mon.run_once()
    assert any("הוסרה" in m for m in rec.msgs)     # recovery message


def test_error_state_does_not_alert():
    mon, c, rec, _ = make()
    cycle(mon, c, ERROR)
    assert rec.msgs == []


def test_notify_out_of_stock_option():
    mon, c, rec, _ = make(notify_out_of_stock=True)
    cycle(mon, c, IN_STOCK)
    cycle(mon, c, OUT_OF_STOCK)
    cycle(mon, c, OUT_OF_STOCK)
    assert any("אזל" in m for m in rec.msgs)
