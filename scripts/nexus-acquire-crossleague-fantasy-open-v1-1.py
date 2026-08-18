from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

BASE = Path(__file__).with_name("nexus-acquire-crossleague-fantasy-open-v1.py")
spec = importlib.util.spec_from_file_location("nexus_crossleague_fantasy_open_v1", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {BASE}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def championship_ids_only(obj: Any) -> set[int]:
    """Collect only values explicitly labelled as championship ids.

    The MPG club metadata also contains generic `id` fields. Treating those as
    championship ids would cause thousands of meaningless pool probes. Generic
    ids are therefore intentionally ignored; the collector still probes the
    bounded public id range 1..30 in addition to explicit championship ids.
    """
    ids: set[int] = set()
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


mod.recursive_candidate_ids = championship_ids_only

if __name__ == "__main__":
    mod.main()
