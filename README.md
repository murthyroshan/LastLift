# LastLift

**Find the last lift before it fails.**

LastLift models every station's step-free routes as a flow network in FalkorDB and finds the lifts that a platform's step-free access depends on, before they fail. Built for Graph Hacks (Track 01: Agents That Act on Connected Data).

> Unofficial decision-support prototype. Not affiliated with or endorsed by the MBTA or MassDOT. Uses MBTA GTFS and V3 API data under the MassDOT Developers License Agreement. Data may be incomplete or out of date. Always check mbta.com/alerts/access before travelling. Elevator status line 617-222-2828; customer support 617-222-3200 (TTY 711).
>
> Results describe the open-data model and may differ from conditions on the ground.

## Status

Work in progress. This README grows with each milestone; every number it states will come from `claims.json`, generated in FalkorDB and independently verified.

## Run locally

Requirements: Python 3.14 (3.12+ works), Node 24, a FalkorDB 4.22 instance.

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows; use .venv/bin/python elsewhere
python dev.py doctor                                           # checks git setup, Python, FalkorDB, .env key names
.venv/Scripts/python -m uvicorn lastlift.main:app --port 8000
cd web && npm install && npm run dev
```

Configuration is read from environment variables, or from a `.env` file one level above the repo (see `.env.example` for the names). Secrets are never committed.

## Licence and data

Code: MIT. Data: MBTA GTFS and V3 API (Massachusetts Department of Transportation open data), attributed in full in the data section as it lands.

## AI assistance

This project was built with the help of an AI coding assistant. Design decisions and the final review are the author's own. The validation key (`validation/gold_live_author.csv`) was labelled by the author, blind, from MBTA's alert text only; a second label set made by the AI assistant (`validation/gold_live.csv`) is kept only to report labeller agreement. Details will be listed in a "Decisions I made" section.

## Feedback

Found a problem with a route or a station? [Report an accessibility problem with LastLift](../../issues/new?template=accessibility-problem.yml) (every field is optional). Prefer not to post publicly? Email mrslvt.dev@gmail.com. How LastLift handles people's experiences is set out in [docs/ETHICS.md](docs/ETHICS.md).
