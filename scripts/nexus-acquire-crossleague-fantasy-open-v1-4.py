from __future__ import annotations

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

WRAPPER = Path(__file__).with_name("nexus-acquire-crossleague-fantasy-open-v1-3.py")
spec = importlib.util.spec_from_file_location("nexus_crossleague_fantasy_open_v1_3", WRAPPER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {WRAPPER}")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
mod = w.mod


def biwenger_capture(root: Path):
    provider_root = mod.mkdir(root / "biwenger")
    base_catalog = "https://cf.biwenger.com/api/v2/competitions/la-liga/data"
    base_player = "https://cf.biwenger.com/api/v2/players/la-liga"
    headers = dict(mod.HEADERS)
    headers.update({"Referer": "https://biwenger.as.com/players", "Accept": "application/json, text/plain, */*"})

    # request_bytes uses the module's standard headers. Biwenger's public CDN
    # endpoint currently accepts those; Referer is retained in provenance docs.
    catalogs = []
    catalog_fields = set()
    player_catalog_rows = []
    unique_players = {}

    for score in [1, 2, 3, 4]:
        try:
            raw, final, status = mod.request_bytes(base_catalog, params={"lang": "en", "score": score})
            if status != 200:
                catalogs.append({"score": score, "status": status, "url": final, "valid": False})
                continue
            obj = json.loads(raw.decode("utf-8"))
            players = ((obj.get("data") or {}).get("players") or {}) if isinstance(obj, dict) else {}
            if isinstance(players, list):
                iterable = [(str(i), p) for i, p in enumerate(players)]
            elif isinstance(players, dict):
                iterable = list(players.items())
            else:
                iterable = []
            if not iterable:
                catalogs.append({"score": score, "status": status, "url": final, "sha256": mod.sha_bytes(raw), "valid": False, "players": 0})
                continue
            capture = provider_root / f"catalog-score-{score}.json"
            capture.write_bytes(raw)
            for key, player in iterable:
                if not isinstance(player, dict):
                    continue
                catalog_fields.update(player.keys())
                pid = player.get("id") or key
                slug = player.get("slug")
                name = mod.clean_text(player.get("name"))
                unique_players[str(pid)] = {"id": pid, "slug": slug, "name": name}
                player_catalog_rows.append({
                    "provider": "BIWENGER",
                    "competition": "LaLiga",
                    "season": "2026-27",
                    "provider_player_id": pid,
                    "player_name": name,
                    "team": player.get("teamID"),
                    "source_url": final,
                    "source_local_path": str(capture.relative_to(root)),
                    "source_sha256": mod.sha_bytes(raw),
                    "record_type": f"PUBLIC_CATALOG_SCORE_{score}",
                    "provider_fields_json": json.dumps(player, ensure_ascii=False, default=str, separators=(",", ":")),
                })
            catalogs.append({"score": score, "status": status, "url": final, "sha256": mod.sha_bytes(raw), "valid": True, "players": len(iterable)})
        except Exception as exc:
            catalogs.append({"score": score, "url": base_catalog, "valid": False, "error": str(exc)})
    mod.write_json(provider_root / "catalog-manifest.json", catalogs)

    detail_root = mod.mkdir(provider_root / "players")
    detail_fields = set()
    detail_rows = []
    errors = []
    fields = "*%2Cteam%2Cfitness%2Creports(points%2Chome%2Cevents%2Cstatus(status%2CstatusText)%2Cmatch(*%2Cround%2Chome%2Caway)%2Cstar)%2Cprices%2Ccompetition%2Cseasons%2Cnews%2Cthreads"

    def fetch_detail(p):
        slug = p.get("slug")
        if not slug:
            return {"player": p, "error": "MISSING_SLUG"}
        url = f"{base_player}/{slug}"
        try:
            raw, final, status = mod.request_bytes(url, params={"fields": fields, "score": 2, "lang": "en"}, attempts=3)
            if status != 200:
                return {"player": p, "url": final, "status": status, "error": f"HTTP_{status}"}
            obj = json.loads(raw.decode("utf-8"))
            path = detail_root / f"{p['id']}-{slug}.json"
            path.write_bytes(raw)
            return {"player": p, "url": final, "status": status, "sha256": mod.sha_bytes(raw), "obj": obj, "path": path}
        except Exception as exc:
            return {"player": p, "url": url, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch_detail, p) for p in unique_players.values()]
        for fut in as_completed(futures):
            res = fut.result()
            p = res["player"]
            if res.get("error"):
                errors.append({"provider_player_id": p.get("id"), "player_name": p.get("name"), "slug": p.get("slug"), "url": res.get("url"), "error": res["error"], "status": res.get("status")})
                continue
            obj = res["obj"]
            data = (obj.get("data") or {}) if isinstance(obj, dict) else {}
            if isinstance(data, dict):
                detail_fields.update(data.keys())
            detail_rows.append({
                "provider": "BIWENGER",
                "competition": "LaLiga",
                "season": "2026-27",
                "provider_player_id": p.get("id"),
                "player_name": mod.clean_text(data.get("name") if isinstance(data, dict) else p.get("name")),
                "team": ((data.get("team") or {}).get("id") if isinstance(data, dict) and isinstance(data.get("team"), dict) else None),
                "source_url": res["url"],
                "source_local_path": str(res["path"].relative_to(root)),
                "source_sha256": res["sha256"],
                "record_type": "PUBLIC_PLAYER_DETAIL_SCORE_2",
                "provider_fields_json": json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")),
            })
    mod.write_json(provider_root / "player-detail-errors.json", errors)

    return {
        "catalogs": catalogs,
        "unique_catalog_players": len(unique_players),
        "detail_profiles_ok": len(detail_rows),
        "detail_profile_errors": len(errors),
        "catalog_fields": sorted(catalog_fields),
        "detail_fields": sorted(detail_fields),
        "rows": player_catalog_rows + detail_rows,
    }


def rebuild_file_inventory(root: Path):
    inventory = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name == "file-inventory.json":
            continue
        inventory.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": mod.sha_file(path)})
    mod.write_json(root / "file-inventory.json", inventory)
    return inventory


def main():
    # Run FPL + fixed/parallel Comunio + parallel MPG first.
    mod.main()
    root = mod.OUT

    biw = biwenger_capture(root)
    idx = root / "normalized" / "provider-player-season-index.csv"
    df = pd.read_csv(idx, low_memory=False)
    if biw["rows"]:
        bdf = pd.DataFrame(biw["rows"])
        for col in df.columns:
            if col not in bdf.columns:
                bdf[col] = None
        for col in bdf.columns:
            if col not in df.columns:
                df[col] = None
        df = pd.concat([df, bdf[df.columns]], ignore_index=True)
        df.to_csv(idx, index=False)

    fields_path = root / "field-inventory.json"
    fields = json.load(open(fields_path, encoding="utf-8"))
    fields["BIWENGER_CATALOG_FIELDS"] = biw["catalog_fields"]
    fields["BIWENGER_PLAYER_DETAIL_FIELDS"] = biw["detail_fields"]
    mod.write_json(fields_path, fields)

    manifest_path = root / "manifest.json"
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    manifest["schema"] = "NEXUS_CROSSLEAGUE_FANTASY_OPEN_ACQUISITION_V1_1"
    manifest["providers"]["BIWENGER"] = {k: v for k, v in biw.items() if k != "rows"}
    provider_counts = df["provider"].value_counts(dropna=False).to_dict()
    manifest["normalized"]["provider_player_season_rows"] = int(len(df))
    manifest["normalized"]["provider_counts"] = {str(k): int(v) for k, v in provider_counts.items()}
    manifest["capture_completed"] = mod.now_iso()
    mod.write_json(manifest_path, manifest)

    inventory = rebuild_file_inventory(root)
    print(json.dumps({
        "status": "PASS",
        "schema": manifest["schema"],
        "provider_player_season_rows": len(df),
        "provider_counts": manifest["normalized"]["provider_counts"],
        "biwenger_unique_players": biw["unique_catalog_players"],
        "biwenger_detail_profiles_ok": biw["detail_profiles_ok"],
        "files": len(inventory),
        "output": str(root),
    }, indent=2))


if __name__ == "__main__":
    main()
