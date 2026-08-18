from __future__ import annotations

import csv
import importlib.util
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

WRAPPER = Path(__file__).with_name("nexus-acquire-crossleague-fantasy-open-v1-2.py")
spec = importlib.util.spec_from_file_location("nexus_crossleague_fantasy_open_v1_2", WRAPPER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {WRAPPER}")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
mod = w.mod


def parse_comunio_profile_links_fixed(html: bytes, base: str) -> list[dict]:
    soup = mod.BeautifulSoup(html, "lxml")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        # Comunio emits both absolute-path (/csprofile/...) and relative
        # (csprofile/...) hrefs depending on language/layout.
        m = re.search(r"(?:^|/)(?:csprofile|profile)(?:/\d+)?/(\d+)-([^/?#]+)", href)
        if not m:
            continue
        pid = int(m.group(1))
        if pid in seen:
            continue
        seen.add(pid)
        tr = a.find_parent("tr")
        cells = [mod.clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")] if tr else []
        out.append({
            "player_id": pid,
            "slug": m.group(2),
            "player_name": mod.clean_text(a.get_text(" ", strip=True)),
            "discovery_href": mod.urljoin(base, href),
            "search_cells": cells,
        })
    return out


def find_pool_players(obj):
    return mod.find_pool_players(obj)


def parallel_mpg_capture(root: Path, master_rows: list[dict], inventories: dict) -> dict:
    provider_root = mod.mkdir(root / "mpg")
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
            obj, raw, final, status = mod.request_json(url)
            mod.write_json(provider_root / f"{name}.json", obj)
            metadata[name] = {"status": status, "url": final, "sha256": mod.sha_bytes(raw)}
            candidate_ids.update(mod.recursive_candidate_ids(obj))
        except Exception as exc:
            metadata[name] = {"error": str(exc), "url": url}
    mod.write_json(provider_root / "metadata-capture.json", metadata)

    pool_root = mod.mkdir(provider_root / "player-pools")
    jobs = [(cid, season) for cid in sorted(candidate_ids) for season in mod.MPG_SEASON_VALUES]

    def fetch_pool(job):
        championship_id, season_value = job
        url = f"{base}/championship-players-pool/{championship_id}"
        try:
            raw, final, status = mod.request_bytes(url, params={"season": season_value}, attempts=3)
            if status != 200:
                return {"championship_id": championship_id, "season_parameter": season_value, "empty": True, "http_status": status}
            try:
                obj = json.loads(raw.decode("utf-8"))
            except Exception:
                return {"championship_id": championship_id, "season_parameter": season_value, "empty": True, "http_status": status, "error": "NON_JSON"}
            players = find_pool_players(obj)
            if not players:
                return {"championship_id": championship_id, "season_parameter": season_value, "empty": True, "http_status": status}
            digest = mod.sha_bytes(raw)
            capture_dir = mod.mkdir(pool_root / str(championship_id) / str(season_value))
            mod.write_json(capture_dir / "pool.json", obj)
            flat_rows = []
            local_master = []
            fields = set()
            for player in players:
                flat = mod.flatten(player)
                fields.update(flat.keys())
                flat_rows.append(flat)
                pid = flat.get("id") or flat.get("playerId") or flat.get("player.id") or flat.get("mpgId")
                name = mod.clean_text(" ".join(str(x or "") for x in [flat.get("firstName"), flat.get("lastName")])) or mod.clean_text(flat.get("name") or flat.get("playerName"))
                local_master.append({
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
            return {
                "championship_id": championship_id,
                "season_parameter": season_value,
                "players": len(players),
                "url": final,
                "sha256": digest,
                "master": local_master,
                "fields": fields,
            }
        except Exception as exc:
            return {"championship_id": championship_id, "season_parameter": season_value, "url": url, "error": str(exc)}

    nonempty = []
    errors = []
    field_set = set()
    seen_digests = set()
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(fetch_pool, job) for job in jobs]
        for fut in as_completed(futures):
            res = fut.result()
            if res.get("error"):
                errors.append({k: v for k, v in res.items() if k not in {"master", "fields"}})
                continue
            if res.get("empty"):
                continue
            digest = res["sha256"]
            duplicate = digest if digest in seen_digests else None
            seen_digests.add(digest)
            master_rows.extend(res.pop("master"))
            field_set.update(res.pop("fields"))
            res["duplicate_payload_sha"] = duplicate
            nonempty.append(res)
            print("MPG_POOL", res["championship_id"], res["season_parameter"], res["players"], flush=True)

    inventories["MPG_POOL_PLAYER_FIELDS"] = sorted(field_set)
    nonempty.sort(key=lambda x: (x["championship_id"], x["season_parameter"]))
    mod.write_json(provider_root / "nonempty-pools.json", nonempty)
    mod.write_json(provider_root / "pool-errors.json", errors)
    return {
        "metadata": metadata,
        "candidate_championship_ids": sorted(candidate_ids),
        "nonempty_pools": nonempty,
        "error_count": len(errors),
    }


mod.parse_comunio_profile_links = parse_comunio_profile_links_fixed
mod.mpg_capture = parallel_mpg_capture

if __name__ == "__main__":
    mod.main()
