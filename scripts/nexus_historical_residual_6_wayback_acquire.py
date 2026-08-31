from __future__ import annotations

import os
from pathlib import Path

import nexus_historical_residual_10_wayback_acquire as base

UNRESOLVED_AFTER_RUN1 = {
    "Bruno Alves",
    "Koray Gunter",
    "Sebastiano Luperto",
    "Mattia Sprocati",
    "Strahinja Tanasijevic",
    "Luca Valzania",
}

base.TARGETS = [
    target for target in base.TARGETS
    if target["candidate"] in UNRESOLVED_AFTER_RUN1
]
base.OUT = Path(
    os.environ.get(
        "NEXUS_HIST_RESIDUAL6_OUT",
        ".nexus-historical-residual-6-wayback",
    )
)

if len(base.TARGETS) != 6:
    raise RuntimeError(f"focused target count mismatch: {len(base.TARGETS)} != 6")

if __name__ == "__main__":
    base.main()
