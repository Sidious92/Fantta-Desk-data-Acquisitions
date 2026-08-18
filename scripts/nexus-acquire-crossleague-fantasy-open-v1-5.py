from __future__ import annotations

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).with_name("nexus-acquire-crossleague-fantasy-open-v1-4.py")
spec = importlib.util.spec_from_file_location("nexus_crossleague_fantasy_open_v1_4", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {BASE}")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
mod = w.mod


def biwenger_capture_all_scores(root: Path):
    provider_root = mod.mkdir(root / "biwenger")
    base_catalog = "https://cf.biwenger.com/api/v2/competitions/la-liga/data"
    base_player = "https://cf.biwenger.com/api/v2/players/la-liga"

    catalogs = []
    catalog_fields = set()
    player_catalog_rows = []
    unique_players = {}
    valid_scores = []

    # Bounded discovery: preserve every public score system that actually
    # returns a player catalog instead of hard-coding today's known IDs.
    for score in range(1, 13):
        try:
            raw, final, status = mod.request_bytes(base_catalog, params={"lang": "en", "score": score}, attempts=3)
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

            valid_scores.append(score)
            capture = provider_root / f"catalog-score-{score}.json"
            capture.write_bytes(raw)
            digest = mod.sha_bytes(raw)
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
                    "source_sha256": digest,
                    "record_type": f"PUBLIC_CATALOG_SCORE_{score}",
                    "provider_fields_json": json.dumps(player, ensure_ascii=False, default=str, separators=(",", ":")),
                })
            catalogs.append({"score": score, "status": status, "url": final, "sha256": digest, "valid": True, "players": len(iterable)})
        except Exception as exc:
            catalogs.append({"score": score, "url": base_catalog, "valid": False, "error": str(exc)})
    mod.write_json(provider_root / "catalog-manifest.json", catalogs)

    detail_fields = set()
    detail_rows = []
    errors = []
    fields = "*,team,fitness,reports(points,home,events,status(status,statusText),match(*,round,home,away),star),prices,competition,seasons,news,threads"

    def fetch_detail(score: int, p: dict):
        slug = p.get("slug")
        if not slug:
            return {"score": score, "player": p, "error": "MISSING_SLUG"}
        url = f"{base_player}/{slug}"
        try:
            raw, final, status = mod.request_bytes(url, params={"fields": fields, "score": score, "lang": "en"}, attempts=3)
            if status != 200:
                return {"score": score, "player": p, "url": final, "status": status, "error": f"HTTP_{status}"}
            obj = json.loads(raw.decode("utf-8"))
            detail_root = mod.mkdir(provider_root / "players" / f"score-{score}")
            path = detail_root / f"{p['id']}-{slug}.json"
            path.write_bytes(raw)
            return {"score": score, "player": p, "url": final, "status": status, "sha256": mod.sha_bytes(raw), "obj": obj, "path": path}
        except Exception as exc:
            return {"score": score, "player": p, "url": url, "error": str(exc)}

    jobs = [(score, p) for score in valid_scores for p in unique_players.values()]
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(fetch_detail, score, p) for score, p in jobs]
        for fut in as_completed(futures):
            res = fut.result()
            p = res["player"]
            score = res["score"]
            if res.get("error"):
                errors.append({
                    "score": score,
                    "provider_player_id": p.get("id"),
                    "player_name": p.get("name"),
                    "slug": p.get("slug"),
                    "url": res.get("url"),
                    "error": res["error"],
                    "status": res.get("status"),
                })
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
                "record_type": f"PUBLIC_PLAYER_DETAIL_SCORE_{score}",
                "provider_fields_json": json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")),
            })
    mod.write_json(provider_root / "player-detail-errors.json", errors)

    by_score_ok = {}
    for row in detail_rows:
        score = row["record_type"].rsplit("_", 1)[-1]
        by_score_ok[score] = by_score_ok.get(score, 0) + 1

    return {
        "catalogs": catalogs,
        "score_candidates": list(range(1, 13)),
        "valid_scores": valid_scores,
        "unique_catalog_players": len(unique_players),
        "detail_profiles_requested": len(jobs),
        "detail_profiles_ok": len(detail_rows),
        "detail_profile_errors": len(errors),
        "detail_profiles_ok_by_score": by_score_ok,
        "catalog_fields": sorted(catalog_fields),
        "detail_fields": sorted(detail_fields),
        "rows": player_catalog_rows + detail_rows,
    }


w.biwenger_capture = biwenger_capture_all_scores

if __name__ == "__main__":
    w.main()
