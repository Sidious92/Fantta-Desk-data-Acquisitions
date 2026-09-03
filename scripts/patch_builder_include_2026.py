from pathlib import Path

p = Path('scripts/build_five_season_transfer_ledgers.py')
s = p.read_text(encoding='utf-8')
s = s.replace('YEARS = [2022, 2023, 2024, 2025]', 'YEARS = [2022, 2023, 2024, 2025, 2026]')
old = '''def load_backbone(year: int) -> list[dict[str, str]]:
    url = f"https://raw.githubusercontent.com/eordo/transfermarkt-data/master/serie_a/{year}.csv"
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    p = OUT / f"serie-a-{year}-structured-backbone.csv"
    p.write_bytes(r.content)
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
'''
new = '''def load_backbone(year: int) -> list[dict[str, str]]:
    url = f"https://raw.githubusercontent.com/eordo/transfermarkt-data/master/serie_a/{year}.csv"
    r = requests.get(url, timeout=45)
    p = OUT / f"serie-a-{year}-structured-backbone.csv"
    if r.status_code == 404 and year == 2026:
        p.write_text("", encoding="utf-8")
        return []
    r.raise_for_status()
    p.write_bytes(r.content)
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
'''
if old not in s:
    raise SystemExit('load_backbone block not found; fail closed')
p.write_text(s.replace(old,new), encoding='utf-8')
print('extended YEARS through 2026; 2026 structured backbone optional, expanded source remains mandatory')
