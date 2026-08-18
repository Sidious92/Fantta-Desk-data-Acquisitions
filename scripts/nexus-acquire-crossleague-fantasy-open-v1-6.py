from __future__ import annotations

import importlib.util
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

BASE = Path(__file__).with_name("nexus-acquire-crossleague-fantasy-open-v1-5.py")
spec = importlib.util.spec_from_file_location("nexus_crossleague_fantasy_open_v1_5", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {BASE}")
v5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v5)

core = v5.mod
wrapper = v5.w

TARGET_SEASON_IDS = {
    2022: "2021-22",
    2023: "2022-23",
    2024: "2023-24",
    2025: "2024-25",
    2026: "2025-26",
}


def _clean(value) -> str:
    return core.clean_text(value)


def _comunio_row_item(anchor, base: str) -> dict | None:
    href = anchor.get("href") or ""
    m = re.search(r"(?:^|/)(?:csprofile|profile)(?:/\d+)?/(\d+)-([^/?#]+)", href)
    if not m:
        return None
    pid = int(m.group(1))
    tr = anchor.find_parent("tr")
    if tr is None:
        return None
    cells = []
    for td in tr.find_all(["td", "th"], recursive=False):
        text = _clean(td.get_text(" ", strip=True))
        imgs = []
        for img in td.find_all("img"):
            meta = {k: _clean(img.get(k)) for k in ["alt", "title", "src"] if img.get(k)}
            if meta:
                imgs.append(meta)
        links = []
        for a in td.find_all("a", href=True):
            links.append({"text": _clean(a.get_text(" ", strip=True)), "href": urljoin(base, a.get("href"))})
        cells.append({"text": text, "images": imgs, "links": links})
    name = _clean(anchor.get_text(" ", strip=True))
    return {
        "player_id": pid,
        "slug": m.group(2),
        "player_name": name,
        "profile_href": urljoin(base, href),
        "cells": cells,
    }


def _comunio_headers_from_table(table) -> list[str]:
    if table is None:
        return []
    header_row = table.find("tr")
    if header_row is None:
        return []
    return [_clean(x.get_text(" ", strip=True)) for x in header_row.find_all(["th", "td"], recursive=False)]


def comunio_capture_search_rows(root: Path, master_rows: list[dict], matchday_rows: list[dict], inventories: dict) -> dict:
    provider_root = core.mkdir(root / "comunio")
    coverage = {}
    all_headers = set()

    for cfg in core.COMUNIO:
        comp_root = core.mkdir(provider_root / cfg["key"])
        for season_end in core.COMUNIO_SEASON_ENDS:
            season = f"{season_end-1}-{str(season_end)[-2:]}"
            season_root = core.mkdir(comp_root / season)
            search_root = core.mkdir(season_root / "search-pages")
            discovered: dict[int, dict] = {}
            page_status = []
            result_headers = []

            for page in range(0, 60):
                start = page * 25
                params = {
                    "name": "",
                    "inclInactive": "1",
                    "minValue": "",
                    "maxValue": "",
                    "minPts": "",
                    "maxPts": "",
                    "season": season_end,
                    "orderBy": "points",
                    "direc": "DESC",
                    "startLimit": start,
                }
                try:
                    body, final_url, status = core.request_bytes(cfg["base"] + "/search", params=params)
                except Exception as exc:
                    page_status.append({"page": page, "startLimit": start, "error": str(exc)})
                    break

                capture_path = search_root / f"page-{page:02d}.html.gz"
                core.write_gzip(capture_path, body)
                soup = core.BeautifulSoup(body, "lxml")

                anchors = []
                for a in soup.find_all("a", href=True):
                    if re.search(r"(?:^|/)(?:csprofile|profile)(?:/\d+)?/\d+-", a.get("href") or ""):
                        anchors.append(a)

                if anchors and not result_headers:
                    result_headers = _comunio_headers_from_table(anchors[0].find_parent("table"))
                    all_headers.update(x for x in result_headers if x)

                new_count = 0
                for anchor in anchors:
                    item = _comunio_row_item(anchor, cfg["base"])
                    if item is None:
                        continue
                    pid = item["player_id"]
                    if pid in discovered:
                        continue
                    item["source_url"] = final_url
                    item["source_local_path"] = str(capture_path.relative_to(root))
                    item["source_sha256"] = core.sha_bytes(body)
                    item["page"] = page
                    item["startLimit"] = start
                    item["result_headers"] = result_headers
                    discovered[pid] = item
                    new_count += 1

                page_status.append({
                    "page": page,
                    "startLimit": start,
                    "status": status,
                    "url": final_url,
                    "profile_links": len(anchors),
                    "new_players": new_count,
                    "sha256": core.sha_bytes(body),
                })

                if not anchors or new_count == 0:
                    break

            items = list(discovered.values())
            core.write_json(season_root / "search-pages-manifest.json", page_status)
            core.write_json(season_root / "player-season-search-rows.json", items)
            core.write_json(season_root / "result-table-headers.json", result_headers)

            for item in items:
                provider_payload = {
                    "result_headers": item.get("result_headers", []),
                    "cells": item.get("cells", []),
                    "page": item.get("page"),
                    "startLimit": item.get("startLimit"),
                    "profile_href": item.get("profile_href"),
                    "season_parameter": season_end,
                    "season_parameter_verified": True,
                }
                team = None
                if len(item.get("cells", [])) > 2:
                    club_cell = item["cells"][2]
                    team = club_cell.get("text") or None
                    if not team:
                        for img in club_cell.get("images", []):
                            team = img.get("title") or img.get("alt")
                            if team:
                                break

                master_rows.append({
                    "provider": "COMUNIO",
                    "competition": cfg["competition"],
                    "season": season,
                    "provider_player_id": item["player_id"],
                    "player_name": item["player_name"],
                    "team": team,
                    "source_url": item["source_url"],
                    "source_local_path": item["source_local_path"],
                    "source_sha256": item["source_sha256"],
                    "record_type": "PLAYER_SEASON_SEARCH_ROW",
                    "provider_fields_json": json.dumps(provider_payload, ensure_ascii=False, default=str, separators=(",", ":")),
                })

            coverage[f"{cfg['key']}:{season}"] = {
                "search_rows_ok": len(items),
                "search_pages": len(page_status),
                "result_headers": result_headers,
                "season_parameter": season_end,
                "season_parameter_verified": True,
            }
            print("COMUNIO_SCOPE", f"{cfg['key']}:{season}", json.dumps(coverage[f"{cfg['key']}:{season}"], ensure_ascii=False), flush=True)

    inventories["COMUNIO_SEARCH_RESULT_COLUMNS"] = sorted(all_headers)
    inventories["COMUNIO_ACQUISITION_MODE"] = ["PUBLIC_SEARCH_RESULT_ROWS"]
    return coverage


def mpg_capture_strict(root: Path, master_rows: list[dict], inventories: dict) -> dict:
    provider_root = core.mkdir(root / "mpg")
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
            obj, raw, final, status = core.request_json(url)
            core.write_json(provider_root / f"{name}.json", obj)
            metadata[name] = {"status": status, "url": final, "sha256": core.sha_bytes(raw)}
            candidate_ids.update(core.recursive_candidate_ids(obj))
        except Exception as exc:
            metadata[name] = {"error": str(exc), "url": url}
    core.write_json(provider_root / "metadata-capture.json", metadata)

    pool_root = core.mkdir(provider_root / "player-pools")
    jobs = [(cid, season_value) for cid in sorted(candidate_ids) for season_value in core.MPG_SEASON_VALUES]
    query_results = []
    errors = []
    field_set = set()

    def fetch_pool(job):
        championship_id, season_value = job
        url = f"{base}/championship-players-pool/{championship_id}"
        try:
            raw, final, status = core.request_bytes(url, params={"season": season_value}, attempts=3)
            if status != 200:
                return {"championship_id": championship_id, "season_parameter": season_value, "status": status, "empty": True, "url": final}
            try:
                obj = json.loads(raw.decode("utf-8"))
            except Exception:
                return {"championship_id": championship_id, "season_parameter": season_value, "status": status, "empty": True, "url": final, "error": "NON_JSON"}
            players = core.find_pool_players(obj)
            if not players:
                return {"championship_id": championship_id, "season_parameter": season_value, "status": status, "empty": True, "url": final}

            digest = core.sha_bytes(raw)
            capture_dir = core.mkdir(pool_root / str(championship_id) / f"query-season-{season_value}")
            raw_path = capture_dir / "pool.json"
            core.write_json(raw_path, obj)
            flat_rows = []
            fields = set()
            for player in players:
                flat = core.flatten(player)
                flat_rows.append(flat)
                fields.update(flat.keys())
            pd.DataFrame(flat_rows).to_csv(capture_dir / "pool-flattened.csv", index=False)
            return {
                "championship_id": championship_id,
                "season_parameter": season_value,
                "status": status,
                "url": final,
                "sha256": digest,
                "players": len(players),
                "raw_path": str(raw_path.relative_to(root)),
                "flat_rows": flat_rows,
                "fields": fields,
            }
        except Exception as exc:
            return {"championship_id": championship_id, "season_parameter": season_value, "url": url, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(fetch_pool, job) for job in jobs]
        for fut in as_completed(futures):
            result = fut.result()
            if result.get("error") and not result.get("flat_rows"):
                errors.append({k: v for k, v in result.items() if k not in {"flat_rows", "fields"}})
            if result.get("flat_rows"):
                field_set.update(result.get("fields", set()))
                query_results.append(result)

    by_championship: dict[int, list[dict]] = defaultdict(list)
    for result in query_results:
        by_championship[int(result["championship_id"])].append(result)

    unique_payload_groups = []
    normalized_group_count = 0
    for championship_id, results in sorted(by_championship.items()):
        by_digest: dict[str, list[dict]] = defaultdict(list)
        for result in results:
            by_digest[result["sha256"]].append(result)

        digest_count = len(by_digest)
        for digest, group in sorted(by_digest.items(), key=lambda kv: min(x["season_parameter"] for x in kv[1])):
            group = sorted(group, key=lambda x: x["season_parameter"])
            query_params = [int(x["season_parameter"]) for x in group]
            representative = group[0]
            if digest_count == 1 and len(query_params) > 1:
                season_label = "UNVERSIONED_CURRENT"
                record_type = "PLAYER_POOL_UNVERSIONED"
            else:
                season_label = f"PARAM_{representative['season_parameter']}"
                record_type = "PLAYER_POOL_SEASON_PARAMETER_UNVERIFIED"

            group_meta = {
                "championship_id": championship_id,
                "sha256": digest,
                "players": representative["players"],
                "query_season_parameters": query_params,
                "season_parameter_semantics_verified": False,
                "normalized_season_label": season_label,
                "record_type": record_type,
                "representative_source_url": representative["url"],
                "representative_source_local_path": representative["raw_path"],
            }
            unique_payload_groups.append(group_meta)
            normalized_group_count += 1

            for flat in representative["flat_rows"]:
                pid = flat.get("id") or flat.get("playerId") or flat.get("player.id") or flat.get("mpgId")
                name = _clean(" ".join(str(x or "") for x in [flat.get("firstName"), flat.get("lastName")])) or _clean(flat.get("name") or flat.get("playerName"))
                payload = {
                    "player": flat,
                    "_capture_meta": {
                        "query_season_parameters": query_params,
                        "season_parameter_semantics_verified": False,
                        "payload_group_sha256": digest,
                        "normalized_season_label": season_label,
                    },
                }
                master_rows.append({
                    "provider": "MPG",
                    "competition": f"MPG_CHAMPIONSHIP_{championship_id}",
                    "season": season_label,
                    "provider_player_id": pid,
                    "player_name": name,
                    "team": flat.get("clubId") or flat.get("club.id") or flat.get("teamId") or flat.get("team.id"),
                    "source_url": representative["url"],
                    "source_local_path": representative["raw_path"],
                    "source_sha256": digest,
                    "record_type": record_type,
                    "provider_fields_json": json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")),
                })

    query_manifest = []
    for result in sorted(query_results, key=lambda x: (x["championship_id"], x["season_parameter"])):
        query_manifest.append({
            "championship_id": result["championship_id"],
            "season_parameter": result["season_parameter"],
            "status": result["status"],
            "players": result["players"],
            "url": result["url"],
            "sha256": result["sha256"],
            "raw_path": result["raw_path"],
        })

    inventories["MPG_POOL_PLAYER_FIELDS"] = sorted(field_set)
    inventories["MPG_SEASON_PARAMETER_SEMANTICS"] = ["UNVERIFIED"]
    core.write_json(provider_root / "nonempty-query-responses.json", query_manifest)
    core.write_json(provider_root / "unique-payload-groups.json", unique_payload_groups)
    core.write_json(provider_root / "pool-errors.json", errors)

    return {
        "metadata": metadata,
        "candidate_championship_ids": sorted(candidate_ids),
        "nonempty_query_responses": query_manifest,
        "unique_payload_groups": unique_payload_groups,
        "unique_payload_group_count": normalized_group_count,
        "season_parameter_semantics_verified": False,
        "fake_historical_seasons_created": False,
        "error_count": len(errors),
    }


def biwenger_capture_historical(root: Path):
    provider_root = core.mkdir(root / "biwenger")
    base_catalog = "https://cf.biwenger.com/api/v2/competitions/la-liga/data"
    base_player = "https://cf.biwenger.com/api/v2/players/la-liga"
    score_candidates = list(range(1, 13))

    catalogs = []
    catalog_fields = set()
    current_catalog_rows = []
    unique_players: dict[str, dict] = {}
    valid_scores = []

    for score in score_candidates:
        try:
            raw, final, status = core.request_bytes(base_catalog, params={"lang": "en", "score": score}, attempts=3)
            if status != 200:
                catalogs.append({"score": score, "status": status, "url": final, "valid": False})
                continue
            obj = json.loads(raw.decode("utf-8"))
            players = ((obj.get("data") or {}).get("players") or {}) if isinstance(obj, dict) else {}
            if isinstance(players, dict):
                iterable = list(players.items())
            elif isinstance(players, list):
                iterable = [(str(i), p) for i, p in enumerate(players)]
            else:
                iterable = []
            iterable = [(key, p) for key, p in iterable if isinstance(p, dict)]
            if not iterable:
                catalogs.append({"score": score, "status": status, "url": final, "sha256": core.sha_bytes(raw), "valid": False, "players": 0})
                continue

            valid_scores.append(score)
            capture = provider_root / f"catalog-score-{score}.json"
            capture.write_bytes(raw)
            digest = core.sha_bytes(raw)
            for key, player in iterable:
                catalog_fields.update(player.keys())
                pid = player.get("id") or key
                slug = player.get("slug")
                name = _clean(player.get("name"))
                if slug:
                    unique_players[str(pid)] = {"id": pid, "slug": slug, "name": name}
                current_catalog_rows.append({
                    "provider": "BIWENGER",
                    "competition": "LaLiga",
                    "season": "2026-27",
                    "provider_player_id": pid,
                    "player_name": name,
                    "team": player.get("teamID"),
                    "source_url": final,
                    "source_local_path": str(capture.relative_to(root)),
                    "source_sha256": digest,
                    "record_type": f"PUBLIC_CATALOG_SCORE_{score}",
                    "provider_fields_json": json.dumps({"score_mode": score, "catalog_player": player}, ensure_ascii=False, default=str, separators=(",", ":")),
                })
            catalogs.append({"score": score, "status": status, "url": final, "sha256": digest, "valid": True, "players": len(iterable)})
        except Exception as exc:
            catalogs.append({"score": score, "url": base_catalog, "valid": False, "error": str(exc)})

    core.write_json(provider_root / "catalog-manifest.json", catalogs)

    metadata_root = core.mkdir(provider_root / "player-metadata-score-2")
    metadata_fields = set()
    metadata_errors = []
    metadata_results = {}
    metadata_rows = []
    metadata_fields_param = "*,team,reports,seasons,prices,fitness,competition"

    def fetch_metadata(p: dict):
        url = f"{base_player}/{p['slug']}"
        try:
            raw, final, status = core.request_bytes(url, params={"fields": metadata_fields_param, "score": 2, "lang": "en"}, attempts=3)
            if status != 200:
                return {"player": p, "status": status, "url": final, "error": f"HTTP_{status}"}
            obj = json.loads(raw.decode("utf-8"))
            data = (obj.get("data") or {}) if isinstance(obj, dict) else {}
            path = metadata_root / f"{p['id']}-{p['slug']}.json"
            path.write_bytes(raw)
            return {"player": p, "status": status, "url": final, "sha256": core.sha_bytes(raw), "path": path, "data": data}
        except Exception as exc:
            return {"player": p, "url": url, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(fetch_metadata, p) for p in unique_players.values()]
        for fut in as_completed(futures):
            res = fut.result()
            p = res["player"]
            if res.get("error"):
                metadata_errors.append({"provider_player_id": p.get("id"), "player_name": p.get("name"), "slug": p.get("slug"), "status": res.get("status"), "url": res.get("url"), "error": res["error"]})
                continue
            data = res["data"] if isinstance(res.get("data"), dict) else {}
            metadata_fields.update(data.keys())
            metadata_results[str(p["id"])] = res
            metadata_rows.append({
                "provider": "BIWENGER",
                "competition": "LaLiga",
                "season": "2026-27",
                "provider_player_id": p["id"],
                "player_name": _clean(data.get("name") or p.get("name")),
                "team": ((data.get("team") or {}).get("id") if isinstance(data.get("team"), dict) else None),
                "source_url": res["url"],
                "source_local_path": str(res["path"].relative_to(root)),
                "source_sha256": res["sha256"],
                "record_type": "PLAYER_METADATA_SCORE_2",
                "provider_fields_json": json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")),
            })

    core.write_json(provider_root / "player-metadata-errors.json", metadata_errors)

    historical_root = core.mkdir(provider_root / "historical-reports")
    historical_rows = []
    historical_errors = []
    history_fields = set()
    requested_jobs = []

    for _, res in metadata_results.items():
        data = res["data"]
        seasons = data.get("seasons") or []
        available_ids = set()
        for s in seasons:
            if not isinstance(s, dict):
                continue
            try:
                sid = int(s.get("id"))
            except Exception:
                continue
            available_ids.add(sid)
        p = res["player"]
        for season_id, season_label in TARGET_SEASON_IDS.items():
            if season_id not in available_ids:
                continue
            for score in valid_scores:
                requested_jobs.append((p, score, season_id, season_label))

    def fetch_history(job):
        p, score, season_id, season_label = job
        url = f"{base_player}/{p['slug']}"
        try:
            raw, final, status = core.request_bytes(url, params={"fields": "reports", "score": score, "season": season_id, "lang": "en"}, attempts=3)
            if status != 200:
                return {"player": p, "score": score, "season_id": season_id, "season_label": season_label, "status": status, "url": final, "error": f"HTTP_{status}"}
            obj = json.loads(raw.decode("utf-8"))
            data = (obj.get("data") or {}) if isinstance(obj, dict) else {}
            reports = data.get("reports") or [] if isinstance(data, dict) else []
            path_dir = core.mkdir(historical_root / f"score-{score}" / season_label)
            path = path_dir / f"{p['id']}-{p['slug']}.json"
            path.write_bytes(raw)
            return {"player": p, "score": score, "season_id": season_id, "season_label": season_label, "status": status, "url": final, "sha256": core.sha_bytes(raw), "path": path, "data": data, "reports": reports}
        except Exception as exc:
            return {"player": p, "score": score, "season_id": season_id, "season_label": season_label, "url": url, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(fetch_history, job) for job in requested_jobs]
        for fut in as_completed(futures):
            res = fut.result()
            p = res["player"]
            if res.get("error"):
                historical_errors.append({"provider_player_id": p.get("id"), "player_name": p.get("name"), "slug": p.get("slug"), "score": res.get("score"), "season_id": res.get("season_id"), "season": res.get("season_label"), "status": res.get("status"), "url": res.get("url"), "error": res["error"]})
                continue
            data = res["data"] if isinstance(res.get("data"), dict) else {}
            history_fields.update(data.keys())
            payload = {"score_mode": res["score"], "biwenger_season_id": res["season_id"], "season_mapping_verified_from_player_seasons": True, "reports": res["reports"]}
            historical_rows.append({
                "provider": "BIWENGER",
                "competition": "LaLiga",
                "season": res["season_label"],
                "provider_player_id": p["id"],
                "player_name": p.get("name"),
                "team": None,
                "source_url": res["url"],
                "source_local_path": str(res["path"].relative_to(root)),
                "source_sha256": res["sha256"],
                "record_type": f"PLAYER_SEASON_REPORTS_SCORE_{res['score']}",
                "provider_fields_json": json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")),
            })

    core.write_json(provider_root / "historical-report-errors.json", historical_errors)

    history_by_score = defaultdict(int)
    history_by_season = defaultdict(int)
    nonempty_history_by_score = defaultdict(int)
    nonempty_history_by_season = defaultdict(int)
    for row in historical_rows:
        score = row["record_type"].rsplit("_", 1)[-1]
        history_by_score[score] += 1
        history_by_season[row["season"]] += 1
        try:
            payload = json.loads(row["provider_fields_json"])
            n = len(payload.get("reports") or [])
        except Exception:
            n = 0
        if n:
            nonempty_history_by_score[score] += 1
            nonempty_history_by_season[row["season"]] += 1

    return {
        "catalogs": catalogs,
        "score_candidates": score_candidates,
        "valid_scores": valid_scores,
        "unique_catalog_players": len(unique_players),
        "metadata_requested": len(unique_players),
        "metadata_ok": len(metadata_rows),
        "metadata_errors": len(metadata_errors),
        "historical_requests": len(requested_jobs),
        "historical_rows_ok": len(historical_rows),
        "historical_errors": len(historical_errors),
        "historical_rows_by_score": dict(history_by_score),
        "historical_rows_by_season": dict(history_by_season),
        "nonempty_historical_rows_by_score": dict(nonempty_history_by_score),
        "nonempty_historical_rows_by_season": dict(nonempty_history_by_season),
        "catalog_fields": sorted(catalog_fields),
        "metadata_fields": sorted(metadata_fields),
        "historical_data_fields": sorted(history_fields),
        "rows": current_catalog_rows + metadata_rows + historical_rows,
    }


core.comunio_capture = comunio_capture_search_rows
core.mpg_capture = mpg_capture_strict
wrapper.biwenger_capture = biwenger_capture_historical

if __name__ == "__main__":
    wrapper.main()
