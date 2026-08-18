from __future__ import annotations

import importlib.util
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

BASE = Path(__file__).with_name("nexus-acquire-crossleague-fantasy-open-v1.py")
spec = importlib.util.spec_from_file_location("nexus_crossleague_fantasy_open_v1", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {BASE}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def championship_ids_only(obj):
    ids = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower().replace("_", "")
            if "championship" in key and key.endswith("id"):
                try:
                    iv = int(v)
                    if 0 < iv < 1000:
                        ids.add(iv)
                except Exception:
                    pass
            ids.update(championship_ids_only(v))
    elif isinstance(obj, list):
        for v in obj:
            ids.update(championship_ids_only(v))
    return ids


def capture_comunio_scope(root: Path, cfg: dict, season_end: int):
    season = f"{season_end-1}-{str(season_end)[-2:]}"
    season_root = mod.mkdir(root / "comunio" / cfg["key"] / season)
    search_root = mod.mkdir(season_root / "search-pages")
    profile_root = mod.mkdir(season_root / "profiles")
    discovered = {}
    page_status = []

    for page in range(0, 40):
        start = page * 25
        params = {"lang": "en", "season": season_end, "orderBy": "points", "direc": "DESC", "startLimit": start}
        try:
            body, final_url, status = mod.request_bytes(cfg["base"] + "/search.php", params=params)
        except Exception as exc:
            page_status.append({"page": page, "startLimit": start, "error": str(exc)})
            break
        mod.write_gzip(search_root / f"page-{page:02d}.html.gz", body)
        links = mod.parse_comunio_profile_links(body, cfg["base"])
        new_count = 0
        for item in links:
            if item["player_id"] not in discovered:
                discovered[item["player_id"]] = item
                new_count += 1
        page_status.append({"page": page, "startLimit": start, "status": status, "url": final_url, "links": len(links), "new": new_count, "sha256": mod.sha_bytes(body)})
        if not links or new_count == 0:
            break

    mod.write_json(season_root / "search-pages-manifest.json", page_status)
    mod.write_json(season_root / "discovered-players.json", list(discovered.values()))

    def fetch_profile(item):
        pid, slug = item["player_id"], item["slug"]
        url = f"{cfg['base']}/profile/{season_end}/{pid}-{slug}"
        try:
            body, final_url, status = mod.request_bytes(url, params={"lang": "en"})
            mod.write_gzip(profile_root / f"{pid}-{slug}.html.gz", body)
            return {"item": item, "url": final_url, "status": status, "sha256": mod.sha_bytes(body), "tables": mod.html_tables(body)}
        except Exception as exc:
            return {"item": item, "url": url, "error": str(exc), "tables": []}

    results, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(fetch_profile, item) for item in discovered.values()]
        for fut in as_completed(futures):
            result = fut.result()
            item = result["item"]
            if result.get("error"):
                errors.append({"player_id": item["player_id"], "player_name": item["player_name"], "url": result["url"], "error": result["error"]})
            else:
                results.append(result)
    mod.write_json(season_root / "profile-errors.json", errors)

    local_master, local_table_rows = [], []
    columns = set()
    for result in results:
        item = result["item"]
        for table in result["tables"]:
            columns.update(table.get("columns", []))
            for row_idx, rec in enumerate(table.get("rows", [])):
                local_table_rows.append({
                    "provider": "COMUNIO",
                    "competition": cfg["competition"],
                    "season": season,
                    "provider_player_id": item["player_id"],
                    "player_name": item["player_name"],
                    "table_index": table["table_index"],
                    "row_index": row_idx,
                    "source_url": result["url"],
                    "provider_fields_json": json.dumps(rec, ensure_ascii=False, separators=(",", ":")),
                })
        local_master.append({
            "provider": "COMUNIO",
            "competition": cfg["competition"],
            "season": season,
            "provider_player_id": item["player_id"],
            "player_name": item["player_name"],
            "team": None,
            "source_url": result["url"],
            "source_local_path": str((profile_root / f"{item['player_id']}-{item['slug']}.html.gz").relative_to(root)),
            "source_sha256": result["sha256"],
            "record_type": "PLAYER_SEASON_PROFILE",
            "provider_fields_json": json.dumps({"search_cells": item.get("search_cells", []), "tables": result["tables"]}, ensure_ascii=False, separators=(",", ":")),
        })
    return {
        "key": f"{cfg['key']}:{season}",
        "coverage": {"discovered_players": len(discovered), "profiles_ok": len(results), "profile_errors": len(errors), "search_pages": len(page_status)},
        "master": local_master,
        "table_rows": local_table_rows,
        "columns": columns,
    }


def parallel_comunio_capture(root: Path, master_rows: list[dict], matchday_rows: list[dict], inventories: dict):
    mod.mkdir(root / "comunio")
    coverage = {}
    all_columns = set()
    scopes = [(cfg, season_end) for cfg in mod.COMUNIO for season_end in mod.COMUNIO_SEASON_ENDS]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(capture_comunio_scope, root, cfg, season_end) for cfg, season_end in scopes]
        for fut in as_completed(futures):
            res = fut.result()
            coverage[res["key"]] = res["coverage"]
            master_rows.extend(res["master"])
            matchday_rows.extend(res["table_rows"])
            all_columns.update(res["columns"])
            print("COMUNIO_SCOPE", res["key"], json.dumps(res["coverage"], separators=(",", ":")), flush=True)
    inventories["COMUNIO_PROFILE_TABLE_COLUMNS"] = sorted(all_columns)
    return dict(sorted(coverage.items()))


mod.recursive_candidate_ids = championship_ids_only
mod.comunio_capture = parallel_comunio_capture

if __name__ == "__main__":
    mod.main()
