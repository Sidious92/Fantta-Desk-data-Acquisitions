#!/usr/bin/env python3
import argparse, hashlib, json, re, subprocess, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path


def run_gh(args, *, stdout_path=None):
    cmd = ["gh", "api", *args]
    if stdout_path:
        with open(stdout_path, "wb") as fh:
            p = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE)
        return p.returncode, None, p.stderr.decode("utf-8", "replace")
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr


def api_json(endpoint):
    rc, out, err = run_gh([endpoint])
    if rc != 0:
        return None, err.strip()
    try:
        return json.loads(out), None
    except Exception as exc:
        return None, f"invalid JSON from gh api: {exc}"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_inventory(path):
    files = []
    canonical = hashlib.sha256()
    with zipfile.ZipFile(path, "r") as zf:
        infos = sorted((i for i in zf.infolist() if not i.is_dir()), key=lambda i: i.filename)
        for info in infos:
            h = hashlib.sha256()
            with zf.open(info, "r") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            files.append({"path": info.filename, "size": info.file_size, "sha256": digest})
            canonical.update(f"{info.filename}\t{info.file_size}\t{digest}\n".encode())
    return files, canonical.hexdigest()


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "artifact"


def discover(repo, prefix):
    all_items = []
    page = 1
    while True:
        payload, err = api_json(f"repos/{repo}/actions/artifacts?per_page=100&page={page}")
        if payload is None:
            raise RuntimeError(f"artifact discovery failed: {err}")
        batch = payload.get("artifacts", [])
        if not batch:
            break
        all_items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    items = []
    for artifact in all_items:
        name = artifact.get("name", "")
        if name.startswith(prefix) and not name.startswith("nexus-d0-"):
            items.append({
                "logical_id": f"artifact-{artifact['id']}",
                "artifact_id": artifact["id"],
                "expected_name": name,
                "source_run_id": ((artifact.get("workflow_run") or {}).get("id")),
                "class": "PUBLIC_RUNNER_ARTIFACT_PRESERVED_UNCLASSIFIED",
                "scientific_admission": "NOT_PROMOTED_BY_D0",
                "availability_policy": "record_if_unavailable",
            })
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inventory")
    mode.add_argument("--discover-prefix")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--release-tag", required=True)
    args = parser.parse_args()

    stage = Path(args.stage)
    stage.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    if args.inventory:
        inventory = json.loads(Path(args.inventory).read_text())
        items = inventory.get("artifacts", [])
        already_permanent = inventory.get("already_permanent", [])
        policy = inventory.get("freeze_policy", {})
        inventory_schema = inventory.get("schema")
    else:
        items = discover(args.repo, args.discover_prefix)
        already_permanent = []
        policy = {
            "raw_mutation": "FORBIDDEN",
            "outer_zip_semantics": "PRESERVATION_CONTAINER_ONLY",
            "authority_hash": "PER_INTERNAL_FILE_SHA256",
            "scientific_promotion": "NONE",
            "replacement_policy": "NEVER_OVERWRITE; CREATE_NEW_VERSION"
        }
        inventory_schema = "DYNAMIC_PUBLIC_NEXUS_ARTIFACT_DISCOVERY_V1"

    results = []
    hard_failures = []
    for item in items:
        artifact_id = int(item["artifact_id"])
        metadata, err = api_json(f"repos/{args.repo}/actions/artifacts/{artifact_id}")
        record = {
            "logical_id": item.get("logical_id"),
            "artifact_id": artifact_id,
            "class": item.get("class"),
            "scientific_admission": item.get("scientific_admission", "NOT_PROMOTED_BY_D0"),
            "source_run_id": item.get("source_run_id"),
            "expected_name": item.get("expected_name"),
            "expected_declared_actions_digest": item.get("declared_actions_digest"),
            "availability_policy": item.get("availability_policy", "required_preserve"),
        }
        if metadata is None:
            record["freeze_status"] = "UNAVAILABLE_AT_FREEZE"
            record["metadata_error"] = err
            results.append(record)
            if record["availability_policy"] == "required_preserve":
                hard_failures.append(f"{artifact_id}: metadata unavailable: {err}")
            continue

        record["github_metadata"] = {
            key: metadata.get(key) for key in
            ("id", "name", "size_in_bytes", "archive_download_url", "expired", "created_at", "expires_at", "updated_at", "digest")
        }
        if record["expected_name"] and metadata.get("name") != record["expected_name"]:
            hard_failures.append(f"{artifact_id}: name mismatch")
            record["freeze_status"] = "METADATA_MISMATCH"
            results.append(record)
            continue
        if metadata.get("expired"):
            record["freeze_status"] = "EXPIRED_UNRECOVERED_AT_D0"
            results.append(record)
            continue

        asset = f"{artifact_id}--{safe_name(metadata.get('name', 'artifact'))}.zip"
        destination = stage / asset
        rc, _, download_error = run_gh([f"repos/{args.repo}/actions/artifacts/{artifact_id}/zip"], stdout_path=destination)
        if rc != 0:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            record["freeze_status"] = "DOWNLOAD_FAILED_AT_D0"
            record["download_error"] = download_error.strip()
            results.append(record)
            continue
        try:
            internal_files, content_digest = zip_inventory(destination)
        except Exception as exc:
            record["freeze_status"] = "INVALID_ZIP_AT_D0"
            record["zip_error"] = str(exc)
            results.append(record)
            hard_failures.append(f"{artifact_id}: invalid downloaded ZIP: {exc}")
            continue
        record.update({
            "freeze_status": "STAGED_FOR_IMMUTABLE_RELEASE",
            "release_asset_name": asset,
            "preservation_container_size": destination.stat().st_size,
            "preservation_container_sha256": sha256_file(destination),
            "canonical_internal_content_sha256": content_digest,
            "internal_file_count": len(internal_files),
            "internal_files": internal_files,
        })
        results.append(record)

    frozen = sum(r["freeze_status"] == "STAGED_FOR_IMMUTABLE_RELEASE" for r in results)
    expired = sum(r["freeze_status"] == "EXPIRED_UNRECOVERED_AT_D0" for r in results)
    unavailable = sum(r["freeze_status"] in ("UNAVAILABLE_AT_FREEZE", "DOWNLOAD_FAILED_AT_D0") for r in results)
    manifest = {
        "schema": "NEXUS_D0_IMMUTABLE_ARTIFACT_FREEZE_MANIFEST_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": args.repo,
        "release_tag": args.release_tag,
        "inventory_schema": inventory_schema,
        "status": "READY_FOR_RELEASE" if not hard_failures else "BLOCKED_FAIL_CLOSED",
        "governance": {
            **policy,
            "models_modified": False,
            "features_derived": False,
            "normalization_performed": False,
            "f0_scientific_promotion_granted": False,
            "note": "GitHub Actions digest is provenance metadata. The downloaded ZIP is a preservation container; scientific byte authority is the SHA-256 of each internal file plus the canonical internal-content digest."
        },
        "summary": {
            "artifact_records": len(results),
            "staged_for_freeze": frozen,
            "expired_unrecovered": expired,
            "unavailable_or_download_failed": unavailable,
            "hard_failure_count": len(hard_failures),
            "already_permanent_records": len(already_permanent)
        },
        "already_permanent": already_permanent,
        "artifacts": results,
        "hard_failures": hard_failures
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest["summary"], indent=2))
    if hard_failures:
        for failure in hard_failures:
            print("HARD FAILURE:", failure, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
