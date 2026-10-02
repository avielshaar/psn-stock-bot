"""Configuration: config.yaml for behaviour, environment / .env for secrets."""
from __future__ import annotations

import copy
import os
import re

import yaml

from .notifiers import (ConsoleNotifier, GreenApiNotifier, NotifierGroup,
                        TelegramNotifier, WebhookNotifier)

DEFAULTS = {
    "amazon": {"base_url": "https://www.amazon.in", "timeout": 20, "proxy": "", "engine": "auto"},
    "monitor": {
        "interval_seconds": 90,          # base time between cycles
        "jitter_pct": 0.3,               # +-30% random jitter
        "delay_between_products": [3, 8],
        "confirm_checks": 2,             # consecutive in-stock reads before alerting
        "confirm_delay_seconds": 4,
        "out_confirm_checks": 2,         # consecutive out-of-stock reads to re-arm
        "realert_cooldown_seconds": 120,
        "alert_on_first_run": True,
        "notify_out_of_stock": False,
        "health_alert_after": 8,         # consecutive bad reads -> warn admin
        "block_alert_after": 5,          # consecutive blocked cycles -> warn admin
        "block_backoff_max_seconds": 1800,
        "state_file": "data/state.json",
    },
    "products": [],
}


def load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if v.startswith("#"):
                v = ""
            elif v[:1] not in ('"', "'"):
                v = re.split(r"\s+#", v, maxsplit=1)[0].strip()   # drop inline comment
            os.environ.setdefault(k.strip(), v.strip('"').strip("'"))


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str = "config.yaml") -> dict:
    user = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, user)
    cfg["products"] = [p for p in cfg.get("products", []) if p.get("enabled", True)]
    return cfg


def _ids(name: str):
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def build_notifiers(console_fallback: bool = True) -> NotifierGroup:
    ns = []
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if tok and _ids("TELEGRAM_CHAT_IDS"):
        ns.append(TelegramNotifier(tok, _ids("TELEGRAM_CHAT_IDS"),
                                   os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org")))
    gid, gtok = os.environ.get("GREENAPI_ID_INSTANCE", "").strip(), os.environ.get("GREENAPI_API_TOKEN", "").strip()
    if gid and gtok and _ids("GREENAPI_CHAT_IDS"):
        ns.append(GreenApiNotifier(gid, gtok, _ids("GREENAPI_CHAT_IDS"),
                                   os.environ.get("GREENAPI_API_URL", "https://api.greenapi.com")))
    if os.environ.get("WEBHOOK_URL", "").strip():
        ns.append(WebhookNotifier(os.environ["WEBHOOK_URL"].strip()))
    if not ns and console_fallback:
        ns.append(ConsoleNotifier())
    return NotifierGroup(ns)
