"""Load a committed snapshot (data/snapshots/<date>/) into FalkorDB and verify it.

    python -m lastlift.seed                  # load the base graph (replaces it if present)
    python -m lastlift.seed --if-missing     # boot path: load only if Meta.seed_sha256 differs
    python -m lastlift.seed --all --verify   # image bake: load + verify

The base graph holds the pinned GTFS model with no closures. Indexes are created on the empty
graph first; rows are loaded in batches with UNWIND; the Meta node is written last, so its
presence means the load completed.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from . import db
from .config import REPO_ROOT, settings

BATCH = 1000
SNAPSHOT_ROOT = REPO_ROOT / "data" / "snapshots"

INDEXES = [
    "CREATE INDEX FOR (n:Node) ON (n.uid)",
    "CREATE INDEX FOR (n:Node) ON (n.cx)",
    "CREATE INDEX FOR (s:Station) ON (s.uid)",
    "CREATE INDEX FOR (p:Platform) ON (p.uid)",
    "CREATE INDEX FOR (p:Platform) ON (p.stop_id)",
    "CREATE INDEX FOR (l:Lift) ON (l.uid)",
    "CREATE INDEX FOR (l:Lift) ON (l.facility_id)",
    "CALL db.idx.fulltext.createNodeIndex('Station', 'name')",
    "CALL db.idx.fulltext.createNodeIndex('Lift', 'name', 'short_name')",
]
# Endpoint labels used to MATCH each relationship type's ends (all indexed on uid).
ENDPOINTS = {
    "SF": ("Node", "Node"), "STEP": ("Node", "Node"), "RIDE": ("Platform", "Platform"),
    "HAS_ENTRANCE": ("Station", "Entrance"), "HAS_PLATFORM": ("Station", "Platform"), "HAS_LIFT": ("Station", "Lift"),
}


def latest_snapshot() -> Path:
    dirs = sorted(p for p in SNAPSHOT_ROOT.iterdir() if (p / "MANIFEST.json").is_file())
    if not dirs:
        raise SystemExit(f"no snapshot found under {SNAPSHOT_ROOT}")
    return dirs[-1]


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def batches(rows, size=BATCH):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def current_seed(graph_name: str) -> str | None:
    if graph_name not in db.client().list_graphs():
        return None
    rs = db.client().select_graph(graph_name).ro_query("MATCH (m:Meta) RETURN m.seed_sha256 LIMIT 1").result_set
    return rs[0][0] if rs else None


def load(snapshot: Path, graph_name: str) -> dict:
    manifest = json.loads((snapshot / "MANIFEST.json").read_text(encoding="utf-8"))
    client = db.client()
    if graph_name in client.list_graphs():
        client.select_graph(graph_name).delete()
    g = client.select_graph(graph_name)
    for q in INDEXES:
        g.query(q)

    by_labels = defaultdict(list)
    for n in read_jsonl(snapshot / "nodes.jsonl"):
        labels = n.pop("labels")
        by_labels[":".join(labels)].append({k: v for k, v in n.items() if v is not None})
    for labels, rows in sorted(by_labels.items()):
        for chunk in batches(rows):
            g.query(f"UNWIND $rows AS r CREATE (n:{labels}) SET n = r", {"rows": chunk})

    by_type = defaultdict(list)
    for e in read_jsonl(snapshot / "edges.jsonl"):
        t, a, b = e.pop("type"), e.pop("a"), e.pop("b")
        by_type[t].append({"a": a, "b": b, "p": {k: v for k, v in e.items() if v is not None}})
    for t, rows in sorted(by_type.items()):
        la, lb = ENDPOINTS[t]
        for chunk in batches(rows):
            g.query(f"UNWIND $rows AS r MATCH (a:{la} {{uid:r.a}}), (b:{lb} {{uid:r.b}}) "
                    f"CREATE (a)-[e:{t}]->(b) SET e = r.p", {"rows": chunk})

    g.query("CREATE (m:Meta) SET m = $p", {"p": {
        "snapshot_id": snapshot.name, "seed_sha256": manifest["seed_sha256"], "feed_version": manifest["feed_version"],
        "rules_version": manifest["rules_version"], "big": manifest["big"],
        "nodes": manifest["counts"]["nodes"], "edges": manifest["counts"]["edges"]}})
    return manifest


def apply_precomputed(graph_name: str, snapshot: Path) -> int:
    """Write the certified baseline sweep (precomputed.jsonl) onto the graph: baseline and current
    k per platform, cuts, and DEPENDS_ON / DEPENDS_NOW edges to every single-point-of-failure lift."""
    path = snapshot / "precomputed.jsonl"
    if not path.is_file():
        return 0
    g = db.client().select_graph(graph_name)
    props, depends = [], []
    for row in read_jsonl(path):
        if row.get("status") == "no_accessible_entrance":
            props.append({"stop": row["stop_id"], "p": {"no_accessible_entrance": True}})
            continue
        p = {}
        for d in ("board", "exit"):
            p[f"k_{d}_base"] = row.get(f"k_{d}")
            p[f"k_{d}"] = row.get(f"k_{d}")
            p[f"at_grade_{d}"] = bool(row.get(f"at_grade_{d}"))
            p[f"at_grade_{d}_now"] = bool(row.get(f"at_grade_{d}"))
            p[f"cut_{d}"] = row.get(f"cut_{d}", [])
            p[f"cut_{d}_now"] = row.get(f"cut_{d}", [])
            depends += [{"stop": row["stop_id"], "fid": f, "dir": d} for f in row.get(f"spof_{d}", [])]
        props.append({"stop": row["stop_id"], "p": {k: v for k, v in p.items() if v is not None}})
    for chunk in batches(props):
        g.query("UNWIND $rows AS r MATCH (p:Node:Platform) WHERE p.stop_id = r.stop SET p += r.p", {"rows": chunk})
    g.query("MATCH ()-[d:DEPENDS_ON|DEPENDS_NOW]->() DELETE d")
    for rel in ("DEPENDS_ON", "DEPENDS_NOW"):
        for chunk in batches(depends):
            g.query("UNWIND $rows AS r MATCH (p:Node:Platform) WHERE p.stop_id = r.stop "
                    f"MATCH (l:Node:Lift {{facility_id:r.fid, cx:p.cx}}) MERGE (p)-[d:{rel} {{dir:r.dir}}]->(l)",
                    {"rows": chunk})
    return len(depends)


def apply_network(graph_name: str, snapshot: Path) -> dict:
    """Write the network sweep (network.json, scripts/network_sweep.py) onto the graph, so Cypher can read it:
    (:Station)-[:REACHES {base_s}]->(:Station), lift blast radius properties, (:Lift)-[:DOMINATES_FOR]->(:Station),
    (:Lift)-[:CRITICAL_PAIR {scope}]->(:Lift), and per-platform minimum cuts and reliability counts."""
    path = snapshot / "network.json"
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    g = db.client().select_graph(graph_name)
    g.query("MATCH ()-[r:REACHES|DOMINATES_FOR|CRITICAL_PAIR]->() DELETE r")
    reaches = [{"a": a, "b": b, "s": s} for a, row in doc["od_base_s"].items() for b, s in row.items()]
    for chunk in batches(reaches):
        g.query("UNWIND $rows AS r MATCH (x:Station {uid:r.a}) MATCH (y:Station {uid:r.b}) "
                "CREATE (x)-[:REACHES {base_s:r.s}]->(y)", {"rows": chunk})
    lifts = [{"f": f, "p": {"od_cut_base": x["od_cut"], "od_cut_off": x["cut_off"], "od_slow_base": x["od_slow"],
                            "detour_max_s": x["detour_max_s"], "detour_mean_s": x["detour_mean_s"]}}
             for f, x in doc["lifts"].items()]
    g.query("UNWIND $rows AS r MATCH (l:Node:Lift {facility_id:r.f}) SET l += r.p", {"rows": lifts})
    dom = [{"f": f, "s": s} for f, x in doc["lifts"].items() for s in x["dominates_for"]]
    for chunk in batches(dom):
        g.query("UNWIND $rows AS r MATCH (l:Node:Lift {facility_id:r.f}) MATCH (s:Station {uid:r.s}) "
                "CREATE (l)-[:DOMINATES_FOR]->(s)", {"rows": chunk})
    pairs = [{"a": p["a"], "b": p["b"], "n": p["n"], "dirs": [f"{d['stop_id']}:{d['dir']}" for d in p["dirs"]]}
             for p in doc["pairs"]]
    # one edge per facility pair, between each facility's first unit (lowest uid)
    g.query("UNWIND $rows AS r MATCH (a:Node:Lift {facility_id:r.a}) WITH r, min(a.uid) AS au "
            "MATCH (b:Node:Lift {facility_id:r.b}) WITH r, au, min(b.uid) AS bu "
            "MATCH (a:Node:Lift {uid:au}) MATCH (b:Node:Lift {uid:bu}) "
            "CREATE (a)-[:CRITICAL_PAIR {scope:'platform', n:r.n, dirs:r.dirs}]->(b)", {"rows": pairs})
    cond = [{"a": c["closed"], "b": c["lift"], "n": c["journeys"], "same": c["same_station"]} for c in doc["conditional"]]
    g.query("UNWIND $rows AS r MATCH (a:Node:Lift {facility_id:r.a}) WITH r, min(a.uid) AS au "
            "MATCH (b:Node:Lift {facility_id:r.b}) WITH r, au, min(b.uid) AS bu "
            "MATCH (a:Node:Lift {uid:au}) MATCH (b:Node:Lift {uid:bu}) "
            "CREATE (a)-[:CRITICAL_PAIR {scope:'network', journeys:r.n, same_station:r.same}]->(b)", {"rows": cond})
    plats = []
    for stop, p in doc["platform"].items():
        props = {}
        for d in ("board", "exit"):
            x = p.get(d) or {}
            if x.get("mincuts") is not None:
                props.update({f"n_mincuts_{d}": len(x["mincuts"]), f"mincuts_{d}": json.dumps(x["mincuts"]),
                              f"rel_counts_{d}": x["rel_counts"], f"rel_relevant_{d}": x["relevant"]})
        if props:
            plats.append({"stop": stop, "p": props})
    for chunk in batches(plats):
        g.query("UNWIND $rows AS r MATCH (p:Node:Platform) WHERE p.stop_id = r.stop SET p += r.p", {"rows": chunk})
    return {"reaches": len(reaches), "dominates_for": len(dom), "critical_pairs": len(pairs) + len(cond),
            "platforms": len(plats)}


def verify(graph_name: str, manifest: dict) -> list[str]:
    """Returns a list of problems (empty = verified)."""
    g = db.client().select_graph(graph_name)
    problems = []
    want_nodes = manifest["counts"]["nodes"]
    got_nodes = g.ro_query("MATCH (n) WHERE NOT n:Meta RETURN count(n)").result_set[0][0]
    if got_nodes != want_nodes:
        problems.append(f"nodes: graph {got_nodes} != manifest {want_nodes}")
    for t, want in manifest["counts"]["edges_by_type"].items():
        got = g.ro_query(f"MATCH ()-[e:{t}]->() RETURN count(e)").result_set[0][0]
        if got != want:
            problems.append(f"{t} edges: graph {got} != manifest {want}")
    multi = g.ro_query("MATCH (a)-[e:SF]->(b) WITH a, b, count(e) AS c WHERE c > 1 RETURN count(*)").result_set[0][0]
    if multi:
        problems.append(f"{multi} node pairs have parallel SF edges (algo.maxFlow rejects multi-edges)")
    # Step-free components must never span two complexes (cx) unless the model says so.
    rows = g.ro_query("CALL algo.WCC({nodeLabels:['Node'], relationshipTypes:['SF']}) YIELD node, componentId "
                      "RETURN componentId, collect(DISTINCT node.cx)").result_set
    mixed = [cxs for _, cxs in rows if len(cxs) > 1]
    if mixed:
        problems.append(f"{len(mixed)} step-free components span several complexes, e.g. {mixed[0][:4]}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None, help="snapshot directory (default: latest)")
    ap.add_argument("--graph", default=settings.graph("base"))
    ap.add_argument("--if-missing", action="store_true")
    ap.add_argument("--all", action="store_true", help="load every graph the app needs (base for now)")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)
    snapshot = Path(args.snapshot) if args.snapshot else latest_snapshot()
    manifest = json.loads((snapshot / "MANIFEST.json").read_text(encoding="utf-8"))

    if args.if_missing and current_seed(args.graph) == manifest["seed_sha256"]:
        print(f"{args.graph}: seed {manifest['seed_sha256'][:12]} already loaded")
        return 0
    load(snapshot, args.graph)
    deps = apply_precomputed(args.graph, snapshot)
    net = apply_network(args.graph, snapshot)
    if net:
        print(f"{args.graph}: network sweep applied {net}")
    print(f"{args.graph}: loaded snapshot {snapshot.name} (seed {manifest['seed_sha256'][:12]}, "
          f"{deps} single-lift dependencies)")
    if args.verify:
        problems = verify(args.graph, manifest)
        for p in problems:
            print(f"VERIFY FAILED: {p}", file=sys.stderr)
        if problems:
            return 1
        print(f"{args.graph}: verified (counts = MANIFEST, 0 multi-edges, components within complexes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
