from pathlib import Path

p = Path('scripts/build_five_season_transfer_ledgers.py')
s = p.read_text(encoding='utf-8')
old = '        for table in box.select("table.items"):\n'
new = '        for table in box.find_all("table"):\n'
if old not in s:
    raise SystemExit('expected old table selector not found; fail closed')
p.write_text(s.replace(old, new), encoding='utf-8')
print('patched current Transfermarkt DOM: table.items -> box.find_all(table)')
