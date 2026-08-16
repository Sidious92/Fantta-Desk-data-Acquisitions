# Fantta-Desk Data Acquisitions

Public, isolated acquisition layer for reproducible external datasets used by the private FantaDesk / FantaNexus repository.

This repository contains **data acquisition and audit code only**. It does not contain the private predictive engine, replay logic, feature engineering, routing, or Decision Layer.

## UEFA club coefficients v0

Source snapshots: Kassiesa public UEFA coefficient tables for 2021–2026.

The acquisition keeps distinct:

- club five-year points;
- 20% association floor;
- official sporting coefficient = `max(club_points_5y, association_floor_20pct)`;
- whether the association floor was used;
- five annual component values.

Run locally with Node 22+:

```bash
npm run acquire:uefa-club-coefficients
```

Generated files are written to:

```text
.nexus-uefa-club-coefficients-v0/acquisition/
```

The GitHub Actions workflow runs the acquisition, requires the audit to PASS, and uploads the generated JSON, CSV, audit and manifest as a workflow artifact.

## Scope boundary

This repository is intentionally public because it contains only reproducible source-acquisition infrastructure and public-source provenance. Any model, private dataset, frozen production artifact or application logic remains outside this repository.
