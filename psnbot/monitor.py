"""Core monitoring logic: decides when an in-stock alert should be sent."""
from __future__ import annotations

import logging
import random
import signal
import time
from datetime import datetime
from typing import Callable

from .amazon import (BLOCKED, ERROR, IN_STOCK, NOT_FOUND, OUT_OF_STOCK, UNKNOWN,
                     ProductStatus)
from .notifiers import NotifierGroup
from .state import StateStore

log = logging.getLogger("psnbot")

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # pragma: no cover
    _TZ = None


def format_alert(product: dict, st: ProductStatus, url: str, now: float | None = None) -> str:
    label = product.get("label") or st.title or product["asin"]
    ts = datetime.fromtimestamp(now or time.time(), _TZ).strftime("%d/%m/%Y %H:%M:%S")
    lines = [f"🎮 *יש מלאי! PlayStation Store India – {label}*"]
    if st.title:
        lines.append(f"📦 {st.title}")
    if st.price:
        lines.append(f"💰 מחיר: {st.price}")
    if st.seller:
        lines.append(f"🏪 {st.seller}")
    lines.append(f"🔗 {url}")
    lines.append(f"⏰ {ts}")
    return "\n".join(lines)


class Monitor:
    def __init__(self, cfg: dict, client, notifiers: NotifierGroup, store: StateStore,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.m = cfg, cfg["monitor"]
        self.client, self.notifiers, self.store = client, notifiers, store
        self.clock, self.sleep = clock, sleep
        self.block_streak = 0
        self.block_alerted = False
        self._stop = False

    # ---- helpers -------------------------------------------------------
    def _admin(self, text: str):
        self.notifiers.send_all("⚠️ *PSN stock bot*\n" + text)

    def _confirmed_in_stock(self, product: dict, first: ProductStatus) -> ProductStatus:
        """Re-read a few times so a single odd page doesn't cause a false alert."""
        last = first
        for _ in range(max(0, int(self.m["confirm_checks"]) - 1)):
            self.sleep(self.m["confirm_delay_seconds"])
            last = self.client.fetch(product["asin"])
            if last.state != IN_STOCK:
                return last
        return last

    # ---- single product -----------------------------------------------
    def check_product(self, product: dict) -> str:
        asin = product["asin"]
        ps = self.store.get(asin)
        st = self.client.fetch(asin)
        log.info("%s [%s] -> %s (%s)", asin, product.get("label", ""), st.state, st.reason)

        if st.state == BLOCKED:
            return BLOCKED
        if st.state in (UNKNOWN, ERROR, NOT_FOUND):
            ps["bad_streak"] += 1
            if ps["bad_streak"] >= self.m["health_alert_after"] and not ps["health_alerted"]:
                self._admin(f"{product.get('label', asin)} ({asin}): {ps['bad_streak']} קריאות רצופות "
                            f"שלא ניתן לפענח ({st.state}: {st.reason}). ייתכן ש-Amazon שינתה את העמוד.")
                ps["health_alerted"] = True
            return st.state
        ps["bad_streak"], ps["health_alerted"] = 0, False

        if st.state == IN_STOCK:
            ps["out_streak"] = 0
            st = self._confirmed_in_stock(product, st)
            if st.state != IN_STOCK:        # failed confirmation
                return st.state
            self._handle_in_stock(product, ps, st)
            ps["state"] = IN_STOCK
        elif st.state == OUT_OF_STOCK:
            ps["out_streak"] += 1
            if ps["alerted"] and ps["out_streak"] >= self.m["out_confirm_checks"]:
                ps["alerted"] = False
                if self.m["notify_out_of_stock"]:
                    self.notifiers.send_all(f"❌ אזל המלאי: {product.get('label', asin)}")
            ps["state"] = OUT_OF_STOCK
        return st.state

    def _handle_in_stock(self, product: dict, ps: dict, st: ProductStatus):
        if ps["alerted"]:
            return
        if ps["state"] is None and not self.m["alert_on_first_run"]:
            ps["alerted"] = True            # already in stock when we started: stay quiet
            return
        mp = product.get("max_price")
        if mp and st.price_value and st.price_value > float(mp):
            log.info("%s in stock but price %s > max_price %s - skipping", product["asin"], st.price_value, mp)
            return
        now = self.clock()
        if now - ps["last_alert"] < self.m["realert_cooldown_seconds"]:
            return
        url = self.client.product_url(product["asin"])
        sent = self.notifiers.send_all(format_alert(product, st, url, now))
        if sent:
            ps["alerted"], ps["last_alert"] = True, now
            log.info("ALERT sent for %s via %d channel(s)", product["asin"], sent)
        else:
            log.error("alert for %s failed on all channels; will retry next cycle", product["asin"])

    # ---- cycle / loop --------------------------------------------------
    def run_once(self) -> bool:
        """Check all products. Returns True if Amazon blocked us."""
        blocked = False
        lo, hi = self.m["delay_between_products"]
        for i, product in enumerate(self.cfg["products"]):
            if self._stop:
                break
            if i:
                self.sleep(random.uniform(lo, hi))
            if self.check_product(product) == BLOCKED:
                blocked = True
                break
        self.store.save()
        if blocked:
            self.block_streak += 1
            if self.block_streak >= self.m["block_alert_after"] and not self.block_alerted:
                self._admin(f"Amazon חוסמת אותי ({self.block_streak} מחזורים רצופים). "
                            "הבוט ממשיך לנסות עם האטה; שקול proxy / IP ביתי / הגדלת interval.")
                self.block_alerted = True
        else:
            if self.block_alerted:
                self._admin("החסימה הוסרה, הניטור חזר לעבוד ✅")
            self.block_streak, self.block_alerted = 0, False
        return blocked

    def next_delay(self, blocked: bool) -> float:
        base = float(self.m["interval_seconds"])
        if blocked:
            base = min(float(self.m["block_backoff_max_seconds"]), base * (2 ** self.block_streak))
        j = float(self.m["jitter_pct"])
        return max(1.0, base * random.uniform(1 - j, 1 + j))

    def stop(self, *_):
        self._stop = True

    def run_forever(self):
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        log.info("monitoring %d product(s) every ~%ss", len(self.cfg["products"]), self.m["interval_seconds"])
        while not self._stop:
            blocked = self.run_once()
            delay = self.next_delay(blocked)
            log.info("next cycle in %.0fs%s", delay, " (backoff)" if blocked else "")
            end = time.time() + delay
            while not self._stop and time.time() < end:
                time.sleep(min(1.0, end - time.time()))
        self.store.save()
        log.info("stopped")
