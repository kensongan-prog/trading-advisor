#!/usr/bin/env python3
"""snap.py — Take dashboard screenshots via Playwright for layout review.

Usage: python3 .claude/skills/dashboard/snap.py [url] [out_dir]

Defaults to http://localhost:8789/ and ./snaps/. Produces:
  - fold.png       : 1440×900 above-the-fold (laptop viewport)
  - full.png       : full-page scroll capture
  - rail.png       : just the Action Rail
  - halt.png       : the Next-Macro-Event spotlight
  - actionzone.png : the green-bordered setups + sim cluster
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright


def snap(url: str, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    # Three breakpoints: desktop (1440), tablet (768), mobile (iPhone 13 logical width 390).
    # Each gets a fold (viewport) shot + a full-page shot. Component closeups stay desktop-only.
    devices = [
        ("desktop", {"width": 1440, "height": 900}, False),
        ("tablet",  {"width":  768, "height": 1024}, True),
        ("mobile",  {"width":  390, "height":  844}, True),
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, viewport, is_touch in devices:
            ctx = browser.new_context(viewport=viewport, device_scale_factor=2,
                                       is_mobile=is_touch, has_touch=is_touch)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(100)
            page.screenshot(path=str(out / f"{name}_fold.png"))
            page.screenshot(path=str(out / f"{name}_full.png"), full_page=True)
            print(f"✓ {out}/{name}_fold.png + {name}_full.png")
            if name == "desktop":
                for sel, fname in [
                    (".action-rail", "rail.png"),
                    (".halt-spotlight-panel", "halt.png"),
                    (".action-zone", "actionzone.png"),
                ]:
                    el = page.query_selector(sel)
                    if el:
                        el.screenshot(path=str(out / fname))
                        print(f"✓ {out/fname}")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8789/"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "snaps")
    snap(url, out)
