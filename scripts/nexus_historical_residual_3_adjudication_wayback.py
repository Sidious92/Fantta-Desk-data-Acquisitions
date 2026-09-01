from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup


OUT = Path(
    os.environ.get(
        "NEXUS_RESIDUAL_3_OUT",
        ".nexus-historical-residual-3-adjudication",
    )
)
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "90"))
USER_AGENT = "FantaNexus-Historical-Residual-3-Adjudication/1.0"

TARGETS = [
    {
        "candidate": "Koray Gunter",
        "subjectId": "historical:2018-19:2758",
        "targetClubCode": "GEN",
        "boundedIssue": "OFFICIAL_LEGA_ROW_GIVEN_NAME_MISMATCH_KARAY_VS_KORAY",
    },
    {
        "candidate": "Sebastiano Luperto",
        "subjectId": "historical:2018-19:393",
        "targetClubCode": "NAP",
        "boundedIssue": "OFFICIAL_ADJACENT_STINT_EVIDENCE_WITHOUT_EXPLICIT_RETURN_EVENT",
    },
    {
        "candidate": "Luca Valzania",
        "subjectId": "historical:2018-19:2742",
        "targetClubCode": "ATA",
        "boundedIssue": "OFFICIAL_ADJACENT_STINT_EVIDENCE_WITHOUT_EXPLICIT_RETURN_EVENT",
    },
]

PAGES = [
    {
        "subjectId": "historical:2018-19:2758",
        "role": "OFFICIAL_LEGA_EVENT_ROW_WITH_IDENTITY_MISMATCH",
        "capture_timestamp": "20190220002802",
        "original_url": (
            "http://www.legaseriea.it/it/serie-a/calcio-mercato?periodo=estate"
        ),
        "expected_sha256": (
            "50e40c3b43ea3724bfb5714f47de8193403575d5f5b2e281dc06c357ef13601a"
        ),
        "required_normalized_terms": ["gunter karay", "galatasaray", "genoa"],
        "required_table_row": [
            "20/07/2018",
            "Gunter Karay",
            "Galatasaray",
            ">",
            "GENOA",
            "Svincolato",
        ],
        "excerpt_needle": "Gunter Karay",
    },
    {
        "subjectId": "historical:2018-19:393",
        "role": "OFFICIAL_ORIGIN_CLUB_TEMPORARY_ACQUISITION_2017_18",
        "capture_timestamp": "20170803171348",
        "original_url": (
            "http://www.empolicalcio.net/Sebastiano-Luperto-e-dell-Empoli.htm"
        ),
        "expected_sha256": (
            "64d6713e7257a7f963f7310db954bc76ac0548e2f32a1f4d074f5f32d4f3ce92"
        ),
        "required_normalized_terms": [
            "sebastiano luperto",
            "acquisito a titolo temporaneo",
            "ssc napoli",
        ],
        "excerpt_needle": "Sebastiano Luperto",
    },
    {
        "subjectId": "historical:2018-19:393",
        "role": "OFFICIAL_TARGET_CLUB_2018_19_ROSTER_PROFILE",
        "capture_timestamp": "20180917005523",
        "original_url": "http://www.sscnapoli.it/Squadra/Sebastiano-Luperto",
        "expected_sha256": (
            "b591cb5183751d3ab4759bf8e8cda0cd35d151438f52ac68819e3815be1c51a6"
        ),
        "required_normalized_terms": [
            "sebastiano luperto",
            "2018 2019 napoli italia a",
            "2017 18 empoli italia b",
        ],
        "excerpt_needle": "Sebastiano Luperto",
    },
    {
        "subjectId": "historical:2018-19:2742",
        "role": "OFFICIAL_ORIGIN_CLUB_TEMPORARY_ACQUISITION_2017_18",
        "capture_timestamp": "20171023063210",
        "original_url": (
            "https://www.pescaracalcio.com/"
            "luca-valzania-e-un-nuovo-giocatore-biancazzurro/"
        ),
        "expected_sha256": (
            "7abcc3a64a1a3e9bc7b9edaab311bbcabc5fa4b1adc3544af6cbeb50892734b1"
        ),
        "required_normalized_terms": [
            "luca valzania",
            "acquisito a titolo temporaneo",
            "atalanta bergamasca calcio",
            "prestito con diritto di riscatto e controriscatto",
        ],
        "excerpt_needle": "Luca Valzania",
    },
    {
        "subjectId": "historical:2018-19:2742",
        "role": "OFFICIAL_TARGET_CLUB_CONTRACT_EXTENSION",
        "capture_timestamp": "20180629125021",
        "original_url": (
            "http://www.atalanta.it/site/paginalive/comunicati-dal-club/"
            "Stagione-2017-2018/2018-06/"
            "26-06-Calciomercato-prolungato-contratto-Valzania.html"
        ),
        "expected_sha256": (
            "20b902e5031b8593c753be34ff6418958f0783e1146e92437b631d79ac260fe3"
        ),
        "required_normalized_terms": [
            "luca valzania",
            "prolungamento del contratto sino al 2023",
        ],
        "excerpt_needle": "Luca Valzania",
    },
    {
        "subjectId": "historical:2018-19:2742",
        "role": "OFFICIAL_TARGET_CLUB_2018_19_ROSTER_PROFILE",
        "capture_timestamp": "20180828093048",
        "original_url": (
            "http://www.atalanta.it/site/Team-e-Staff/Team/Valzania-Luca.html"
        ),
        "expected_sha256": (
            "735dc00c7d9fb59d26e8d90cae119143b792cde89550332c4713ef173c3481d0"
        ),
        "required_normalized_terms": [
            "luca valzania",
            "2017 2018 pescara b 33 5",
        ],
        "excerpt_needle": "Luca Valzania",
    },
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def bounded_excerpt(text: str, needle: str, radius: int = 1200) -> str:
    compact = " ".join(text.split())
    pos = normalize(compact).find(normalize(needle))
    if pos < 0:
        return compact[: 2 * radius]
    return compact[max(0, pos - radius) : min(len(compact), pos + radius)]


def raw_snapshot_url(page: dict) -> str:
    return (
        f"https://web.archive.org/web/{page['capture_timestamp']}id_/"
        f"{page['original_url']}"
    )


def fetch_page(index_and_page: tuple[int, dict]) -> dict:
    index, page = index_and_page
    raw_url = raw_snapshot_url(page)
    rec = {
        "index": index,
        "subjectId": page["subjectId"],
        "role": page["role"],
        "capture_timestamp": page["capture_timestamp"],
        "original_url": page["original_url"],
        "raw_snapshot_url": raw_url,
        "expected_sha256": page["expected_sha256"],
    }
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.get(
                raw_url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()
            data = response.content
            if len(data) < 500:
                raise RuntimeError(f"payload too small: {len(data)} bytes")
            actual_sha = sha256(data)
            if actual_sha != page["expected_sha256"]:
                raise RuntimeError(
                    "raw SHA-256 mismatch: "
                    f"expected {page['expected_sha256']}, got {actual_sha}"
                )

            soup = BeautifulSoup(data, "html.parser")
            title = " ".join(soup.title.stripped_strings) if soup.title else ""
            text = " ".join(soup.stripped_strings)
            normalized_text = normalize(text)
            missing = [
                term
                for term in page["required_normalized_terms"]
                if normalize(term) not in normalized_text
            ]
            if missing:
                raise RuntimeError(f"required semantic terms missing: {missing}")

            matched_table_row = None
            required_row = page.get("required_table_row")
            if required_row:
                normalized_required = [normalize(value) for value in required_row]
                for row in soup.find_all("tr"):
                    cells = [
                        " ".join(cell.stripped_strings)
                        for cell in row.find_all(["td", "th"])
                    ]
                    normalized_cells = [normalize(value) for value in cells]
                    if normalized_cells == normalized_required:
                        matched_table_row = cells
                        break
                if matched_table_row is None:
                    raise RuntimeError(
                        f"required exact table row missing: {required_row}"
                    )

            filename = (
                f"{index:02d}__{page['subjectId'].replace(':', '_')}__"
                f"{page['capture_timestamp']}.html"
            )
            raw_dir = OUT / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / filename).write_bytes(data)
            rec.update(
                {
                    "status": "PASS",
                    "attempt": attempt,
                    "final_url": response.url,
                    "redirect_chain": [
                        {
                            "status": item.status_code,
                            "url": item.url,
                            "location": item.headers.get("location"),
                        }
                        for item in response.history
                    ],
                    "content_type": response.headers.get("content-type"),
                    "byte_length": len(data),
                    "sha256": actual_sha,
                    "page_title": title,
                    "required_semantic_terms": page["required_normalized_terms"],
                    "matched_table_row": matched_table_row,
                    "bounded_text_excerpt": bounded_excerpt(
                        text, page["excerpt_needle"]
                    ),
                    "raw_file": f"raw/{filename}",
                }
            )
            return rec
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 * attempt)
    rec.update(
        {
            "status": "FAIL",
            "error": f"{type(last_error).__name__}: {last_error}",
        }
    )
    return rec


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "raw").mkdir(parents=True, exist_ok=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        records = list(executor.map(fetch_page, enumerate(PAGES, start=1)))
    records.sort(key=lambda record: record["index"])
    failures = [record for record in records if record["status"] != "PASS"]

    manifest = {
        "schema": "NEXUS_HISTORICAL_RESIDUAL_3_ADJUDICATION_WAYBACK_V1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority": "ARCHIVED_FIRST_PARTY_CLUB_AND_LEGA_PAGES",
        "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
        "targets": TARGETS,
        "records": records,
        "status": "PASS" if not failures else "FAIL_CLOSED",
        "failures": [
            {
                "subjectId": record["subjectId"],
                "role": record["role"],
                "error": record["error"],
            }
            for record in failures
        ],
        "scientific_boundary": {
            "semantic_event_acceptance_performed": False,
            "new_identity_alias_created": False,
            "adjacent_stints_promoted_to_event": False,
            "absence_interpreted_as_no_transfer": False,
            "knownAt_created": False,
            "effectiveAt_created": False,
            "replay_admissibility_created": False,
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
