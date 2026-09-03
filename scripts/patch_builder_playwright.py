from pathlib import Path

p = Path('scripts/build_five_season_transfer_ledgers.py')
s = p.read_text(encoding='utf-8')
old = '''def fetch_expanded(year: int) -> tuple[str, str]:
    urls = [
        f"https://www.transfermarkt.com/serie-a/transfers/wettbewerb/IT1/saison_id/{year}/leihe/1/intern/1/plus/",
        f"https://www.transfermarkt.com/serie-a/transfers/wettbewerb/IT1/saison_id/{year}/intern/1/leihe/1/plus/",
    ]
    last = None
    for u in urls:
        r = requests.get(u, headers=HEADERS, timeout=45)
        last = (u, r)
        if r.status_code == 200 and "Transfers" in r.text and "Transfer record" in r.text:
            return u, r.text
    u, r = last
    raise RuntimeError(f"Transfermarkt fetch failed year={year} status={r.status_code} url={u}")
'''
new = '''def fetch_expanded(year: int) -> tuple[str, str]:
    urls = [
        f"https://www.transfermarkt.com/serie-a/transfers/wettbewerb/IT1/saison_id/{year}/leihe/1/intern/1/plus/",
        f"https://www.transfermarkt.com/serie-a/transfers/wettbewerb/IT1/saison_id/{year}/intern/1/leihe/1/plus/",
    ]
    last_status = None
    for u in urls:
        r = requests.get(u, headers=HEADERS, timeout=45)
        last_status = r.status_code
        if r.status_code == 200 and "Transfers" in r.text and "Transfer record" in r.text:
            return u, r.text

    # Transfermarkt commonly returns HTTP 202 anti-bot challenges to datacenter IPs.
    # Browser fallback keeps the acquisition reproducible while still failing closed
    # if the real rendered transfer table cannot be reached.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="en-US",
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()
        for u in urls:
            resp = page.goto(u, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(5000)
            html = page.content()
            if "Transfers" in html and "Transfer record" in html and "table" in html:
                browser.close()
                return u, html
        browser.close()
    raise RuntimeError(f"Transfermarkt browser fallback failed year={year} initial_status={last_status}")
'''
if old not in s:
    raise SystemExit('expected fetch_expanded block not found; fail closed')
p.write_text(s.replace(old, new), encoding='utf-8')
print('patched fetch_expanded with Playwright fallback')
