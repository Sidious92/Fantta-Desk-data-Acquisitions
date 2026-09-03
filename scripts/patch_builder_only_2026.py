from pathlib import Path
p=Path('scripts/build_five_season_transfer_ledgers.py')
s=p.read_text(encoding='utf-8')
for old in ['YEARS = [2022, 2023, 2024, 2025, 2026]','YEARS = [2022, 2023, 2024, 2025]']:
    if old in s:
        s=s.replace(old,'YEARS = [2026]')
        break
else:
    raise SystemExit('YEARS declaration not found; fail closed')
p.write_text(s,encoding='utf-8')
print('isolated 2026-27 acquisition')
