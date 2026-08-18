from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

OUT = Path(os.environ.get("NEXUS_CROSSLEAGUE_FANTASY_OUT", "/mnt/data/nexus-crossleague-fantasy-open-v1"))
SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
FPL_SEASONS = SEASONS + ["2026-27"]
MPG_SEASON_VALUES = [2021, 2022, 2023, 2024, 2025, 2026]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FantaNexusResearch/1.0; public-data-acquisition)",
    "Accept-Language": "en-US,en;q=0.8",
}
TIMEOUT = 30

COMUNIO = [
    {"key": "bundesliga", "competition": "1. Bundesliga", "base": "https://stats.comunio.de"},
    {"key": "bundesliga2", "competition": "2. Bundesliga", "base": "https://stats.comduo.comunio.de"},
    {"key": "laliga", "competition": "Primera Division", "base": "https://stats.comunio.es"},
    {"key": "superlig", "competition": "Super Lig", "base": "https://stats.comunio.com.tr"},
]
COMUNIO_SEASON_ENDS = [2022, 2023, 2024, 2025, 2026]


def now_iso() -> str:
    return pd.Timestamp.utcnow().isoformat()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, obj: Any, pretty: bool = True) -> None:
    mkdir(path.parent)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2 if pretty else None, separators=None if pretty else (",", ":")),
        encoding="utf-8",
    )


def write_gzip(path: Path, data: bytes) -> None:
    mkdir(path.parent)
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(data)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def request_bytes(url: str, params: dict | None = None, attempts: int = 4) -> tuple[bytes, str, int]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200:
                return r.content, r.url, r.status_code
            if r.status_code in {404, 410}:
                return r.content, r.url, r.status_code
            r.raise_for_status()
        except Exception as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}: {last}")


def request_json(url: str, params: dict | None = None, attempts: int = 4) -> tuple[Any, bytes, str, int]:
    raw, final_url, status = request_bytes(url, params=params, attempts=attempts)
    if status != 200:
        raise RuntimeError(f"HTTP {status}: {final_url}")
    return json.loads(raw.decode("utf-8")), raw, final_url, status


def flatten(obj: Any, prefix: str = "", out: dict | None = None) -> dict:
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            flatten(v, key, out)
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    else:
        out[prefix] = obj
    return out


def fpl_capture(root: Path, master_rows: list[dict], inventories: dict) -> dict:
    provider_root = mkdir(root / "fpl")
    archive_root = mkdir(provider_root / "archive")
    tmp = Path(tempfile.mkdtemp(prefix="fpl-archive-"))
    repo = tmp / "repo"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", "https://github.com/vaastav/Fantasy-Premier-League.git", str(repo)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "sparse-checkout", "set", *[f"data/{s}" for s in FPL_SEASONS]],
            check=True,
        )
        archive_sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        copied = []
        fpl_fields = set()
        gw_fields = set()
        for season in FPL_SEASONS:
            src = repo / "data" / season
            if not src.exists():
                continue
            dst = archive_root / season
            shutil.copytree(src, dst, dirs_exist_ok=True)
            copied.append(season)
            players_raw = dst / "players_raw.csv"
            if players_raw.exists():
                df = pd.read_csv(players_raw, low_memory=False)
                fpl_fields.update(map(str, df.columns))
                for row in df.to_dict(orient="records"):
                    pid = row.get("id")
                    name = clean_text(f"{row.get('first_name', '')} {row.get('second_name', '')}") or clean_text(row.get("web_name"))
                    master_rows.append({
                        "provider": "FPL_ARCHIVE",
                        "competition": "Premier League",
                        "season": season,
                        "provider_player_id": pid,
                        "player_name": name,
                        "team": row.get("team"),
                        "source_url": f"https://github.com/vaastav/Fantasy-Premier-League/tree/master/data/{season}",
                        "source_local_path": str(players_raw.relative_to(root)),
                        "source_sha256": sha_file(players_raw),
                        "record_type": "PLAYER_SEASON_AGGREGATE",
                        "provider_fields_json": json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")),
                    })
            merged_gw = dst / "gws" / "merged_gw.csv"
            if merged_gw.exists():
                try:
                    gw_df = pd.read_csv(merged_gw, low_memory=False)
                    gw_fields.update(map(str, gw_df.columns))
                except Exception:
                    pass
        inventories["FPL_ARCHIVE_PLAYER_FIELDS"] = sorted(fpl_fields)
        inventories["FPL_ARCHIVE_GAMEWEEK_FIELDS"] = sorted(gw_fields)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    api_root = mkdir(provider_root / "official-api-current")
    bootstrap, raw, url, _ = request_json("https://fantasy.premierleague.com/api/bootstrap-static/")
    (api_root / "bootstrap-static.json").write_bytes(raw)
    elements = bootstrap.get("elements", []) if isinstance(bootstrap, dict) else []
    inventories["FPL_CURRENT_BOOTSTRAP_ELEMENT_FIELDS"] = sorted({k for e in elements if isinstance(e, dict) for k in e.keys()})

    summaries_root = mkdir(api_root / "element-summary")
    summary_inventory = set()
    history_inventory = set()
    history_past_inventory = set()
    summary_errors = []

    def fetch_element(element: dict) -> dict:
        pid = int(element["id"])
        u = f"https://fantasy.premierleague.com/api/element-summary/{pid}/"
        try:
            obj, b, final, status = request_json(u)
            p = summaries_root / f"{pid}.json"
            p.write_bytes(b)
            return {"pid": pid, "obj": obj, "url": final, "status": status, "sha": sha_bytes(b)}
        except Exception as exc:
            return {"pid": pid, "error": str(exc), "url": u}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch_element, e) for e in elements if isinstance(e, dict) and e.get("id") is not None]
        for fut in as_completed(futures):
            item = fut.result()
            if item.get("error"):
                summary_errors.append(item)
                continue
            obj = item["obj"]
            summary_inventory.update(obj.keys() if isinstance(obj, dict) else [])
            for h in obj.get("history", []) if isinstance(obj, dict) else []:
                if isinstance(h, dict):
                    history_inventory.update(h.keys())
            for h in obj.get("history_past", []) if isinstance(obj, dict) else []:
                if isinstance(h, dict):
                    history_past_inventory.update(h.keys())
    inventories["FPL_ELEMENT_SUMMARY_TOP_FIELDS"] = sorted(summary_inventory)
    inventories["FPL_ELEMENT_SUMMARY_HISTORY_FIELDS"] = sorted(history_inventory)
    inventories["FPL_ELEMENT_SUMMARY_HISTORY_PAST_FIELDS"] = sorted(history_past_inventory)
    write_json(api_root / "element-summary-errors.json", summary_errors)

    return {
        "archive_seasons_copied": copied,
        "archive_head_sha": archive_sha,
        "current_bootstrap_elements": len(elements),
        "element_summaries_ok": len(elements) - len(summary_errors),
        "element_summaries_errors": len(summary_errors),
        "bootstrap_sha256": sha_bytes(raw),
        "bootstrap_url": url,
    }


def parse_comunio_profile_links(html: bytes, base: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        m = re.search(r"/(?:csprofile|profile)(?:/\d+)?/(\d+)-([^/?#]+)", href)
        if not m:
            continue
        pid = int(m.group(1))
        if pid in seen:
            continue
        seen.add(pid)
        tr = a.find_parent("tr")
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")] if tr else []
        out.append({
            "player_id": pid,
            "slug": m.group(2),
            "player_name": clean_text(a.get_text(" ", strip=True)),
            "discovery_href": urljoin(base, href),
            "search_cells": cells,
        })
    return out


def html_tables(html: bytes) -> list[dict]:
    try:
        dfs = pd.read_html(StringIO(html.decode("utf-8", errors="replace")))
    except Exception:
        return []
    out = []
    for idx, df in enumerate(dfs):
        cols = []
        for col in df.columns:
            if isinstance(col, tuple):
                cols.append(" | ".join(clean_text(x) for x in col if clean_text(x)))
            else:
                cols.append(clean_text(col))
        df.columns = cols
        rows = []
        for rec in df.fillna("").astype(str).to_dict(orient="records"):
            rows.append({clean_text(k): clean_text(v) for k, v in rec.items()})
        out.append({"table_index": idx, "columns": cols, "rows": rows})
    return out


def comunio_capture(root: Path, master_rows: list[dict], matchday_rows: list[dict], inventories: dict) -> dict:
    provider_root = mkdir(root / "comunio")
    coverage = {}
    profile_table_columns = set()

    for cfg in COMUNIO:
        comp_root = mkdir(provider_root / cfg["key"])
        for season_end in COMUNIO_SEASON_ENDS:
            season = f"{season_end-1}-{str(season_end)[-2:]}"
            season_root = mkdir(comp_root / season)
            search_root = mkdir(season_root / "search-pages")
            profile_root = mkdir(season_root / "profiles")
            discovered: dict[int, dict] = {}
            page_status = []
            for page in range(0, 40):
                start = page * 25
                params = {
                    "lang": "en",
                    "season": season_end,
                    "orderBy": "points",
                    "direc": "DESC",
                    "startLimit": start,
                }
                try:
                    body, final_url, status = request_bytes(cfg["base"] + "/search.php", params=params)
                except Exception as exc:
                    page_status.append({"page": page, "startLimit": start, "error": str(exc)})
                    break
                write_gzip(search_root / f"page-{page:02d}.html.gz", body)
                links = parse_comunio_profile_links(body, cfg["base"])
                new_count = 0
                for item in links:
                    if item["player_id"] not in discovered:
                        discovered[item["player_id"]] = item
                        new_count += 1
                page_status.append({"page": page, "startLimit": start, "status": status, "url": final_url, "links": len(links), "new": new_count, "sha256": sha_bytes(body)})
                if not links or new_count == 0:
                    break
            write_json(season_root / "search-pages-manifest.json", page_status)
            write_json(season_root / "discovered-players.json", list(discovered.values()))

            errors = []
            results = []

            def fetch_profile(item: dict) -> dict:
                pid = item["player_id"]
                slug = item["slug"]
                url = f"{cfg['base']}/profile/{season_end}/{pid}-{slug}"
                try:
                    body, final_url, status = request_bytes(url, params={"lang": "en"})
                    write_gzip(profile_root / f"{pid}-{slug}.html.gz", body)
                    tables = html_tables(body)
                    return {"item": item, "url": final_url, "status": status, "sha256": sha_bytes(body), "tables": tables}
                except Exception as exc:
                    return {"item": item, "url": url, "error": str(exc), "tables": []}

            with ThreadPoolExecutor(max_workers=6) as ex:
                futures = [ex.submit(fetch_profile, item) for item in discovered.values()]
                for fut in as_completed(futures):
                    result = fut.result()
                    item = result["item"]
                    if result.get("error"):
                        errors.append({"player_id": item["player_id"], "player_name": item["player_name"], "url": result["url"], "error": result["error"]})
                        continue
                    results.append(result)
                    for table in result["tables"]:
                        profile_table_columns.update(table.get("columns", []))
                        for row_idx, rec in enumerate(table.get("rows", [])):
                            matchday_rows.append({
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
                    master_rows.append({
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
            write_json(season_root / "profile-errors.json", errors)
            coverage[f"{cfg['key']}:{season}"] = {
                "discovered_players": len(discovered),
                "profiles_ok": len(results),
                "profile_errors": len(errors),
                "search_pages": len(page_status),
            }
    inventories["COMUNIO_PROFILE_TABLE_COLUMNS"] = sorted(profile_table_columns)
    return coverage


def recursive_candidate_ids(obj: Any) -> set[int]:
    ids = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower()
            if key in {"id", "championshipid", "championship_id"}:
                try:
                    iv = int(v)
                    if 0 < iv < 1000:
                        ids.add(iv)
                except Exception:
                    pass
            ids.update(recursive_candidate_ids(v))
    elif isinstance(obj, list):
        for v in obj:
            ids.update(recursive_candidate_ids(v))
    return ids


def find_pool_players(obj: Any) -> list[dict]:
    if isinstance(obj, dict):
        for key in ["poolPlayers", "players", "championshipPlayers", "data"]:
            val = obj.get(key)
            if isinstance(val, list) and val and all(isinstance(x, dict) for x in val):
                return val
        for v in obj.values():
            found = find_pool_players(v)
            if found:
                return found
    elif isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            return obj
        for v in obj:
            found = find_pool_players(v)
            if found:
                return found
    return []


def mpg_capture(root: Path, master_rows: list[dict], inventories: dict) -> dict:
    provider_root = mkdir(root / "mpg")
    base = "https://api.mpg.football/api/data"
    metadata = {}
    candidate_ids = set(range(1, 31))
    for name, endpoint in [
        ("championships-active", "/championships/active"),
        ("championships", "/championships"),
        ("championship-clubs", "/championship-clubs"),
    ]:
        url = base + endpoint
        try:
            obj, raw, final, status = request_json(url)
            write_json(provider_root / f"{name}.json", obj)
            metadata[name] = {"status": status, "url": final, "sha256": sha_bytes(raw)}
            candidate_ids.update(recursive_candidate_ids(obj))
        except Exception as exc:
            metadata[name] = {"error": str(exc), "url": url}
    write_json(provider_root / "metadata-capture.json", metadata)

    pool_root = mkdir(provider_root / "player-pools")
    field_set = set()
    nonempty = []
    errors = []
    seen_payloads = set()

    for championship_id in sorted(candidate_ids):
        for season_value in MPG_SEASON_VALUES:
            url = f"{base}/championship-players-pool/{championship_id}"
            try:
                raw, final, status = request_bytes(url, params={"season": season_value})
                if status != 200:
                    continue
                digest = sha_bytes(raw)
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except Exception:
                    continue
                players = find_pool_players(obj)
                if not players:
                    continue
                # Keep duplicate provider responses as separate season evidence, but flag identical payloads.
                duplicate_of = digest if digest in seen_payloads else None
                seen_payloads.add(digest)
                capture_dir = mkdir(pool_root / str(championship_id) / str(season_value))
                write_json(capture_dir / "pool.json", obj)
                flat_rows = []
                for player in players:
                    flat = flatten(player)
                    field_set.update(flat.keys())
                    flat_rows.append(flat)
                    pid = flat.get("id") or flat.get("playerId") or flat.get("player.id") or flat.get("mpgId")
                    name = clean_text(" ".join(str(x or "") for x in [flat.get("firstName"), flat.get("lastName")])) or clean_text(flat.get("name") or flat.get("playerName"))
                    master_rows.append({
                        "provider": "MPG",
                        "competition": f"MPG_CHAMPIONSHIP_{championship_id}",
                        "season": str(season_value),
                        "provider_player_id": pid,
                        "player_name": name,
                        "team": flat.get("clubId") or flat.get("club.id") or flat.get("teamId") or flat.get("team.id"),
                        "source_url": final,
                        "source_local_path": str((capture_dir / "pool.json").relative_to(root)),
                        "source_sha256": digest,
                        "record_type": "PLAYER_POOL_RECORD",
                        "provider_fields_json": json.dumps(flat, ensure_ascii=False, default=str, separators=(",", ":")),
                    })
                pd.DataFrame(flat_rows).to_csv(capture_dir / "pool-flattened.csv", index=False)
                nonempty.append({
                    "championship_id": championship_id,
                    "season_parameter": season_value,
                    "players": len(players),
                    "url": final,
                    "sha256": digest,
                    "duplicate_payload_sha": duplicate_of,
                })
            except Exception as exc:
                errors.append({"championship_id": championship_id, "season_parameter": season_value, "url": url, "error": str(exc)})
    inventories["MPG_POOL_PLAYER_FIELDS"] = sorted(field_set)
    write_json(provider_root / "nonempty-pools.json", nonempty)
    write_json(provider_root / "pool-errors.json", errors)
    return {"metadata": metadata, "candidate_championship_ids": sorted(candidate_ids), "nonempty_pools": nonempty, "error_count": len(errors)}


def write_csv(path: Path, rows: list[dict]) -> None:
    mkdir(path.parent)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    mkdir(OUT)
    started = now_iso()
    master_rows: list[dict] = []
    matchday_rows: list[dict] = []
    inventories: dict[str, list[str]] = {}
    providers = {}

    providers["FPL"] = fpl_capture(OUT, master_rows, inventories)
    providers["COMUNIO"] = comunio_capture(OUT, master_rows, matchday_rows, inventories)
    providers["MPG"] = mpg_capture(OUT, master_rows, inventories)

    normalized = mkdir(OUT / "normalized")
    write_csv(normalized / "provider-player-season-index.csv", master_rows)
    write_csv(normalized / "provider-profile-table-rows.csv", matchday_rows)
    write_json(OUT / "field-inventory.json", inventories)

    provider_counts = {}
    for row in master_rows:
        provider_counts[row["provider"]] = provider_counts.get(row["provider"], 0) + 1
    table_counts = {}
    for row in matchday_rows:
        provider_counts_key = row["provider"]
        table_counts[provider_counts_key] = table_counts.get(provider_counts_key, 0) + 1

    manifest = {
        "schema": "NEXUS_CROSSLEAGUE_FANTASY_OPEN_ACQUISITION_V1",
        "status": "PASS" if master_rows else "FAIL_NO_ROWS",
        "capture_started": started,
        "capture_completed": now_iso(),
        "target_history_window": SEASONS,
        "providers": providers,
        "normalized": {
            "provider_player_season_rows": len(master_rows),
            "provider_profile_table_rows": len(matchday_rows),
            "provider_counts": provider_counts,
            "table_row_counts": table_counts,
        },
        "governance": {
            "provider_native_scores_preserved": True,
            "cross_provider_normalization_performed": False,
            "missing_values_filled": False,
            "predictive_models_modified": False,
            "decision_layer_started": False,
        },
    }
    write_json(OUT / "manifest.json", manifest)

    file_inventory = []
    for path in sorted(p for p in OUT.rglob("*") if p.is_file()):
        if path.name == "file-inventory.json":
            continue
        file_inventory.append({
            "path": str(path.relative_to(OUT)),
            "bytes": path.stat().st_size,
            "sha256": sha_file(path),
        })
    write_json(OUT / "file-inventory.json", file_inventory)
    print(json.dumps({
        "status": manifest["status"],
        "provider_player_season_rows": len(master_rows),
        "provider_profile_table_rows": len(matchday_rows),
        "provider_counts": provider_counts,
        "files": len(file_inventory),
        "output": str(OUT),
    }, indent=2))


if __name__ == "__main__":
    main()
