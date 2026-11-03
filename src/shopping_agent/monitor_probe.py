"""Standalone environment probe. No credentials, scrape calls or API server."""
import asyncio
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

if __package__:
    from .goofish_browser import protected_playwright
    from .goofish_control_flow import repair_detail_control_flow, CompatibilityError
else:
    from goofish_browser import protected_playwright
    from goofish_control_flow import repair_detail_control_flow, CompatibilityError


async def probe(root):
    checks = []
    try:
        ZoneInfo("Asia/Shanghai")
        import dotenv
        dotenv.load_dotenv = lambda *a, **kw: False
        dotenv.dotenv_values = lambda *a, **kw: {}
        sys.path.insert(0, str(root))
        from src import scraper
        checks.append(dict(code="dependencies", ok=True))
    except Exception:
        return [dict(code="dependencies", ok=False)]
    try:
        repair_detail_control_flow(scraper)
        checks.append(dict(code="control_flow", ok=True))
    except CompatibilityError:
        return [*checks, dict(code="control_flow", ok=False)]
    try:
        factory = protected_playwright(scraper.async_playwright, {"cookies": [], "origins": []})
        async with factory() as p:
            browser = await p.chromium.launch(channel=scraper._resolve_browser_channel())
            try:
                context = await browser.new_context()
                await context.route("**/*", lambda route: route.abort())
                page = await context.new_page()
                await page.goto("about:blank")
                await context.close()
            finally:
                await browser.close()
        checks.append(dict(code="browser", ok=True))
    except Exception:
        checks.append(dict(code="browser", ok=False))
    return checks


def main():
    root, output = map(lambda p: Path(p).resolve(), sys.argv[1:3])
    # Even an accidental import-time HTTP call must fail before sending data.
    def no_remote_python_connections(event, args):
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
                raise OSError("Remote connections disabled for environment probe")
    sys.addaudithook(no_remote_python_connections)
    result = asyncio.run(probe(root))
    output.write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
