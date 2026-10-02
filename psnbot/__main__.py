from __future__ import annotations

import argparse
import logging
import sys

import requests

from .amazon import AmazonClient
from .config import build_notifiers, load_config, load_env_file
from .monitor import Monitor, format_alert
from .notifiers import GreenApiNotifier
from .state import StateStore


def _client(cfg):
    a = cfg["amazon"]
    return AmazonClient(a["base_url"], a["timeout"], a.get("proxy", ""), a.get("engine", "auto"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="psnbot", description="PlayStation India gift-card stock alerts")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="monitor forever")
    sub.add_parser("once", help="one check cycle, then exit")
    p = sub.add_parser("check", help="fetch+parse one ASIN and print the result")
    p.add_argument("asin")
    p.add_argument("--save", metavar="FILE", help="also save the raw HTML to FILE (for debugging)")
    sub.add_parser("verify", help="fetch every configured product and show its title/state (checks ASIN vs label)")
    sub.add_parser("test-notify", help="send a test message to all configured channels")
    sub.add_parser("telegram-chat-id", help="print chat ids that recently wrote to your bot")
    sub.add_parser("greenapi-groups", help="list WhatsApp groups (to find the @g.us id)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    load_env_file()
    cfg = load_config(args.config)

    if args.cmd == "check":
        cl = _client(cfg)
        print(f"engine            : {cl.engine}")
        if args.save:
            from .amazon import parse_product_html
            code, html = cl.fetch_html(args.asin)
            open(args.save, "w", encoding="utf-8").write(html)
            st = parse_product_html(args.asin, html, code)
            print(f"saved {len(html)} bytes to {args.save}")
        else:
            st = cl.fetch(args.asin)
        for k, v in st.__dict__.items():
            print(f"{k:18}: {v}")
        return 0
    if args.cmd == "verify":
        import time, random
        from .amazon import label_matches, BLOCKED
        cl, bad = _client(cfg), 0
        for i, pr in enumerate(cfg["products"]):
            if i:
                time.sleep(random.uniform(3, 6))
            st = cl.fetch(pr["asin"])
            ok = label_matches(pr.get("label", ""), st.title)
            flag = "OK " if ok and st.title else "?? "
            bad += 0 if (ok and st.title) else 1
            print(f"{flag}{pr['asin']}  label={pr.get('label','')}  state={st.state}\n     title: {st.title or '-'}")
            if st.state == BLOCKED:
                print("     (blocked - try again in a minute)")
        print("\nall products match their labels" if not bad else f"\n{bad} product(s) need attention (?? lines)")
        return 0 if not bad else 1
    if args.cmd == "test-notify":
        n = build_notifiers().send_all("✅ בדיקה: בוט מלאי PlayStation India מחובר ועובד.")
        print(f"sent via {n} channel(s)")
        return 0 if n else 1
    if args.cmd == "telegram-chat-id":
        import os
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        api = os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org")
        r = requests.get(f"{api}/bot{tok}/getUpdates", timeout=15).json()
        seen = {}
        for u in r.get("result", []):
            m = u.get("message") or u.get("channel_post") or u.get("my_chat_member", {})
            c = m.get("chat") if m else None
            if c:
                seen[c["id"]] = c.get("title") or c.get("username") or c.get("first_name", "")
        print(seen or "no chats yet - write /start to the bot (or add it to the group and write something)")
        return 0
    if args.cmd == "greenapi-groups":
        import os
        g = GreenApiNotifier(os.environ["GREENAPI_ID_INSTANCE"], os.environ["GREENAPI_API_TOKEN"], [],
                             os.environ.get("GREENAPI_API_URL", "https://api.greenapi.com"))
        for cid, name in g.list_groups():
            print(cid, "-", name)
        return 0

    if not cfg["products"]:
        print("no products in config.yaml", file=sys.stderr)
        return 2
    mon = Monitor(cfg, _client(cfg), build_notifiers(), StateStore(cfg["monitor"]["state_file"]))
    if args.cmd == "once":
        mon.run_once()
        return 0
    mon.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
