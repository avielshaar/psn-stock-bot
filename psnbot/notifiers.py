"""Notification channels: Telegram, WhatsApp (via Green API), generic webhook, console."""
from __future__ import annotations

import html
import logging
import re
from typing import List

import requests

log = logging.getLogger("psnbot.notify")


class Notifier:
    name = "base"

    def send(self, text: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    name = "console"

    def send(self, text: str) -> bool:
        print("\n----- ALERT -----\n" + text + "\n-----------------", flush=True)
        return True


def _to_telegram_html(text: str) -> str:
    # message uses WhatsApp-style *bold*; convert to Telegram HTML
    esc = html.escape(text, quote=False)
    return re.sub(r"\*(.+?)\*", r"<b>\1</b>", esc)


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, token: str, chat_ids: List[str], api_url="https://api.telegram.org", timeout=15):
        self.token, self.chat_ids = token, chat_ids
        self.api_url, self.timeout = api_url.rstrip("/"), timeout

    def send(self, text: str) -> bool:
        ok = False
        for chat in self.chat_ids:
            try:
                r = requests.post(
                    f"{self.api_url}/bot{self.token}/sendMessage",
                    json={"chat_id": chat, "text": _to_telegram_html(text),
                          "parse_mode": "HTML", "disable_web_page_preview": False},
                    timeout=self.timeout)
                if r.status_code == 200 and r.json().get("ok"):
                    ok = True
                else:
                    log.error("telegram send failed (%s): %s", r.status_code, r.text[:200])
            except (requests.RequestException, ValueError) as e:
                log.error("telegram send error: %s", e.__class__.__name__)
        return ok


class GreenApiNotifier(Notifier):
    """WhatsApp through green-api.com. chat ids: '972501234567@c.us' or '<id>@g.us' for groups."""
    name = "whatsapp(green-api)"

    def __init__(self, id_instance: str, token: str, chat_ids: List[str],
                 api_url="https://api.greenapi.com", timeout=20):
        self.id_instance, self.token, self.chat_ids = id_instance, token, chat_ids
        self.api_url, self.timeout = api_url.rstrip("/"), timeout

    def send(self, text: str) -> bool:
        ok = False
        url = f"{self.api_url}/waInstance{self.id_instance}/sendMessage/{self.token}"
        for chat in self.chat_ids:
            try:
                r = requests.post(url, json={"chatId": chat, "message": text}, timeout=self.timeout)
                if r.status_code == 200 and "idMessage" in r.text:
                    ok = True
                else:
                    log.error("green-api send failed (%s): %s", r.status_code, r.text[:200])
            except requests.RequestException as e:
                log.error("green-api send error: %s", e.__class__.__name__)
        return ok

    def list_groups(self):
        url = f"{self.api_url}/waInstance{self.id_instance}/getContacts/{self.token}"
        r = requests.get(url, timeout=self.timeout)
        r.raise_for_status()
        return [(c.get("id"), c.get("name", "")) for c in r.json() if str(c.get("id", "")).endswith("@g.us")]


class WebhookNotifier(Notifier):
    name = "webhook"

    def __init__(self, url: str, timeout=15):
        self.url, self.timeout = url, timeout

    def send(self, text: str) -> bool:
        try:
            r = requests.post(self.url, json={"text": text, "content": text}, timeout=self.timeout)
            return 200 <= r.status_code < 300
        except requests.RequestException as e:
            log.error("webhook error: %s", e.__class__.__name__)
            return False


class NotifierGroup:
    def __init__(self, notifiers: List[Notifier]):
        self.notifiers = notifiers

    def send_all(self, text: str) -> int:
        n = 0
        for nt in self.notifiers:
            try:
                if nt.send(text):
                    n += 1
            except Exception:  # never let a notifier crash the monitor
                log.exception("notifier %s crashed", nt.name)
        return n

    def __bool__(self):
        return bool(self.notifiers)
