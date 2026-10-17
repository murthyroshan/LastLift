"""Build the static mirror the website falls back to when the API is asleep or blocked.

    python scripts/build_mirror.py            # writes web/public/m/ and web/public/claims.json

Everything comes from the same tools the API serves, on the frozen demo scope:
  m/state.json            current closures, repair priority, eval summary, snapshot ids
  m/stations.json         every station with pathway data: platforms, single-lift and lost counts
  m/station/<id>.json     platform_redundancy + the station graph contract (board and exit)
  m/whatif/<fid>.json     what_if_close for the story lifts + the station graph under that simulation
  m/queries.json          the Cypher of every Q_* constant (for the query drawer)
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import db, queries, state, station_view, tools  # noqa: E402

OUT = ROOT / "web" / "public" / "m"
STORY_WHATIFS = [("place-alfcl", "813"), ("place-dwnxg", "891"), ("place-knncl", "866"),
                 ("place-rbmnl", "884"), ("place-chncl", "922")]


def write(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    return len(text)


def main():
    started = time.time()
    tools.prepare_scope("demo")
    claims = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))
    (ROOT / "web" / "public" / "claims.json").write_bytes((ROOT / "claims.json").read_bytes())
    g = db.client().select_graph(state.graph_name("demo"))
    meta = g.ro_query(queries.Q_META).result_set[0]
    write(OUT / "state.json", {
        "scope": "demo", "snapshot": {"id": meta[0], "seed_sha256": meta[1]},
        "closures": tools.current_closures("demo"), "priority": tools.repair_priority("demo", limit=200),
        "eval": {k: v for k, v in claims.items() if k.startswith(("live_", "static_"))},
    })
    write(OUT / "queries.json", {n: getattr(queries, n) for n in sorted(dir(queries)) if n.startswith("Q_")})
    rows = g.ro_query("MATCH (s:Station) WHERE s.has_pathways RETURN s.uid, s.name ORDER BY s.name").result_set
    stations, total = [], 0
    for sid, name in rows:
        red = tools.platform_redundancy(sid, "demo")
        graphs = {d: station_view.view(sid, d, "demo") for d in ("board", "exit")}
        total += write(OUT / "station" / f"{sid}.json", {"redundancy": red, "graph": graphs})
        plats = (red.get("data") or {}).get("platforms", [])
        k = lambda p, d: (p.get(d) or {}).get("k")
        stations.append({
            "id": sid, "name": name, "platforms": len(plats),
            "lost": sum(1 for p in plats if 0 in (k(p, "board"), k(p, "exit"))),
            "single": sum(1 for p in plats if 1 in (k(p, "board"), k(p, "exit")) and 0 not in (k(p, "board"), k(p, "exit"))),
            "closed": (red.get("data") or {}).get("closed_here", []),
        })
        print(f"{sid}: {len(plats)} platforms", flush=True)
    write(OUT / "stations.json", stations)
    for sid, fid in STORY_WHATIFS:
        wi = tools.what_if_close([fid], "demo")
        copy = (wi.get("data") or {}).get("copy")
        graphs = {d: station_view.view(sid, d, "demo", scenario=copy) for d in ("board", "exit")} if copy else {}
        total += write(OUT / "whatif" / f"{fid}.json", {"station": sid, "whatif": wi, "graph": graphs})
    # repairs page: ticket drafts for lifts that need action now (tiers 1-2), reroutes for every lost platform
    ranked = (tools.repair_priority("demo", limit=200).get("data") or {}).get("ranked", [])
    for r in [r for r in ranked if r["tier"] in (1, 2)]:
        total += write(OUT / "ticket" / f"{r['facility_id']}.json", tools.draft_action(r["facility_id"], "demo"))
    for lp in (tools.current_closures("demo").get("data") or {}).get("platforms_lost", []):
        routes = {"exit": tools.step_free_route(lp["station_id"], from_platform=lp["stop_id"], scope="demo"),
                  "board": tools.step_free_route(lp["station_id"], to_platform=lp["stop_id"], scope="demo")}
        total += write(OUT / "reroute" / f"{lp['stop_id']}.json", {"platform": lp, **routes})
    import csv
    rows = list(csv.DictReader((ROOT / "validation" / "eval_live.csv").open(encoding="utf-8")))
    keep = ("gold_id", "facility_ids", "stations", "mbta_board_class", "mbta_exit_class", "exp_verdict",
            "labeller_notes", "model_verdict", "model_entrances_cut", "model_alt_lifts", "match")
    write(OUT / "eval.json", [{k: r[k] for k in keep} for r in rows])
    from lastlift.wording import DISCLAIMERS
    write(OUT / "disclaimers.json", DISCLAIMERS)
    print(f"mirror: {len(stations)} stations, {len(STORY_WHATIFS)} what-ifs, {total // 1024} KB, "
          f"{time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
