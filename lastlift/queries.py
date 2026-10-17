"""Every Cypher statement LastLift runs, as named constants. The agent never writes Cypher;
tools call these fixed, parameterised queries and report the query id as evidence."""

# --- redundancy (max-flow over the single step-free relationship type SF) --------------------
Q_MAXFLOW = (
    "MATCH (s:Node) WHERE s.uid IN $src WITH collect(s) AS S "
    "MATCH (t:Node) WHERE t.uid IN $dst WITH S, collect(t) AS T "
    "CALL algo.maxFlow({sourceNodes:S, targetNodes:T, relationshipTypes:['SF'], capacityProperty:'cap'}) "
    "YIELD edges, edgeFlows, maxFlow RETURN [e IN edges | e.eid], edgeFlows, maxFlow"
)
Q_COMPLEX_FLOW_EDGES = (
    "MATCH (a:Node {cx:$cx})-[e:SF]->(b:Node) RETURN e.eid, a.uid, b.uid, e.cap, e.kind, e.facility_id"
)
Q_COMPLEX_PLATFORMS = (
    "MATCH (p:Node:Platform {cx:$cx}) RETURN p.stop_id, collect(p.uid), head(collect(p.name)), "
    "head(collect(p.wheelchair_boarding)), head(collect(p.platform_name))"
)
Q_COMPLEX_STREETS = "MATCH (s:Street {cx:$cx}) RETURN collect(s.uid)"

# --- closures: relationship-type swap SF <-> SF_CLOSED on lift edges ------------------------
Q_CLOSE_LIFTS = (
    "UNWIND $fids AS fid MATCH (i:Lift {facility_id:fid})-[r:SF {kind:'lift'}]->(o) "
    "CREATE (i)-[c:SF_CLOSED]->(o) SET c = properties(r), i.closed = true DELETE r RETURN count(c)"
)
Q_REOPEN_LIFTS = (
    "MATCH (i:Lift)-[r:SF_CLOSED]->(o) WHERE NOT i.facility_id IN $fids "
    "CREATE (i)-[c:SF]->(o) SET c = properties(r), i.closed = false DELETE r RETURN count(c)"
)
Q_CLOSED_FACILITIES = "MATCH (i:Lift)-[:SF_CLOSED]->() RETURN collect(DISTINCT i.facility_id)"
Q_LIFT_COMPLEXES = "MATCH (l:Node:Lift) WHERE l.facility_id IN $fids RETURN collect(DISTINCT l.cx)"
Q_LIFT_INCIDENT_COUNT = (
    "MATCH (l:Lift {facility_id:$fid}) OPTIONAL MATCH (l)-[:CLOSED_IN]->(i:Incident) RETURN count(DISTINCT i)"
)
Q_LIFT_INFO = (
    "MATCH (l:Lift {facility_id:$fid}) RETURN l.facility_id, l.name, l.short_name, l.station_id, l.cx, "
    "l.modelled, coalesce(l.closed, false) LIMIT 1"
)

# --- writing recomputed state ---------------------------------------------------------------
Q_SET_PLATFORM_NOW = (
    "MATCH (p:Node:Platform) WHERE p.stop_id = $stop SET p.k_board = $kb, p.k_exit = $ke, "
    "p.at_grade_board_now = $ab, p.at_grade_exit_now = $ae, p.cut_board_now = $cb, p.cut_exit_now = $ce"
)
Q_CLEAR_DEPENDS_NOW = "MATCH (p:Node:Platform {cx:$cx})-[d:DEPENDS_NOW]->() DELETE d"
Q_CREATE_DEPENDS = (
    "UNWIND $rows AS r MATCH (p:Node:Platform) WHERE p.stop_id = r.stop "
    "MATCH (l:Node:Lift {{facility_id:r.fid, cx:p.cx}}) MERGE (p)-[d:{rel} {{dir:r.dir}}]->(l)"
)

# --- impact, priority, history ----------------------------------------------------------------
Q_LOST_NOW = (
    "MATCH (p:Node:Platform) WHERE (p.k_board = 0 AND (p.k_board_base > 0 OR p.at_grade_board)) "
    "OR (p.k_exit = 0 AND (p.k_exit_base > 0 OR p.at_grade_exit)) "
    "RETURN p.stop_id, p.name, p.platform_name, p.station_id, p.k_board, p.k_exit, p.deps_day"
)
Q_NEWLY_LAST = (
    "MATCH (p:Node:Platform)-[n:DEPENDS_NOW]->(l:Lift) WHERE NOT (p)-[:DEPENDS_ON {dir:n.dir}]->(l) "
    "RETURN l.facility_id, l.name, l.station_id, collect(DISTINCT p.stop_id + ' ' + n.dir)"
)
Q_PRIORITY = (
    # "newly" = platform-directions for which this lift became the last lift because of current closures.
    # (A pattern predicate with {dir:d.dir} inside CASE never matched on 4.22, so use OPTIONAL MATCH.)
    "MATCH (p:Node:Platform)-[d:DEPENDS_NOW]->(l:Lift) "
    "OPTIONAL MATCH (p)-[o:DEPENDS_ON]->(l) WHERE o.dir = d.dir "
    "WITH l, p, d, count(o) AS before "
    "WITH l, count(DISTINCT p.stop_id + d.dir) AS deps, sum(p.deps_day) AS departures, "
    "toInteger(sum(CASE WHEN before = 0 THEN 1 ELSE 0 END)) AS newly "
    "OPTIONAL MATCH (l)-[:CLOSED_IN]->(i:Incident) WITH l, deps, departures, newly, count(DISTINCT i) AS incidents "
    "RETURN l.facility_id, l.name, l.station_id, coalesce(l.closed, false), deps, newly, departures, incidents"
)

# --- names --------------------------------------------------------------------------------
Q_STATION_SEARCH = (
    "CALL db.idx.fulltext.queryNodes('Station', $q) YIELD node, score "
    "RETURN node.uid, node.name, node.has_pathways, node.has_street, score ORDER BY score DESC, node.uid LIMIT 5"
)
Q_STATION = "MATCH (s:Station {uid:$sid}) RETURN s.uid, s.name, s.cx, s.has_pathways, s.has_street"

# --- reroute (routing.py: Dijkstra over these edges, then an edge-by-edge certificate) -----------
Q_ROUTE_NODES = (
    "MATCH (n) WHERE n:Node OR n:Platform "
    "RETURN n.uid, labels(n), n.name, n.station_id, n.platform_name, n.short_name"
)
Q_ROUTE_EDGES = (
    "MATCH (a)-[e:SF|RIDE]->(b) RETURN a.uid, b.uid, e.eid, type(e), e.kind, e.wt, e.facility_id, e.routes"
)
# Route certificate: every edge of a Dijkstra route exists, is open, and has the weight used.
# (No SPpaths in any request path: on 4.22 it can run for hours and ignores the query timeout.)
Q_ROUTE_CHECK_SF = (
    "UNWIND $pairs AS p MATCH (a:Node {uid:p[0]})-[e:SF]->(b:Node {uid:p[1]}) RETURN a.uid, b.uid, e.wt"
)
Q_ROUTE_CHECK_RIDE = (
    "UNWIND $pairs AS p MATCH (a:Platform {uid:p[0]})-[e:RIDE]->(b:Platform {uid:p[1]}) RETURN a.uid, b.uid, e.wt"
)

# --- station view ---------------------------------------------------------------------------
Q_STATION_NODES = (
    "MATCH (n:Node {cx:$cx}) RETURN n.uid, labels(n), n.name, n.platform_name, n.facility_id, n.unit, "
    "coalesce(n.closed, false), n.stop_id, n.wheelchair_boarding"
)
Q_STATION_EDGES = (
    "MATCH (a:Node {cx:$cx})-[e]->(b:Node) WHERE type(e) IN ['SF','SF_CLOSED','STEP'] "
    "RETURN e.eid, a.uid, b.uid, type(e), e.kind, e.facility_id, e.pathway_ids"
)
Q_STATION_PLATFORMS = (
    "MATCH (p:Node:Platform {cx:$cx}) RETURN p.stop_id AS stop, collect(p.uid), head(collect(p.name)), "
    "head(collect(p.platform_name)), min(p.k_board), min(p.k_exit), min(p.k_board_base), min(p.k_exit_base), "
    "head(collect(p.at_grade_board)), head(collect(p.at_grade_exit)), head(collect(p.at_grade_board_now)), "
    "head(collect(p.at_grade_exit_now)), head(collect(p.cut_board_now)), head(collect(p.cut_exit_now)), "
    "coalesce(head(collect(p.no_accessible_entrance)), false) ORDER BY stop"
)
Q_STATION_UNMODELLED_LIFTS = (
    "MATCH (l:Lift) WHERE l.station_id = $sid AND NOT l:Node RETURN l.facility_id, l.name ORDER BY l.facility_id"
)
Q_META = "MATCH (m:Meta) RETURN m.snapshot_id, m.seed_sha256 LIMIT 1"
Q_MODELLED_LIFTS = "MATCH (l:Node:Lift) WHERE l.facility_id IN $fids RETURN collect(DISTINCT l.facility_id)"

# --- incident memory (incidents.py) -----------------------------------------------------------
Q_CLEAR_INCIDENTS = "MATCH (i:Incident) DETACH DELETE i"
Q_WRITE_INCIDENTS = (
    "UNWIND $rows AS r CREATE (i:Incident) SET i = r.p WITH i, r "
    "UNWIND r.fids AS fid MATCH (l:Lift {facility_id:fid}) MERGE (l)-[:CLOSED_IN]->(i)"
)
Q_LIFT_HISTORY = (
    "MATCH (l:Lift {facility_id:$fid})-[:CLOSED_IN]->(i:Incident) RETURN DISTINCT i.alert_id, i.effect, i.header, "
    "i.started, i.first_seen, i.last_seen, i.ongoing, i.ended_by, i.versions ORDER BY i.first_seen"
)
Q_CLOSED_AT_COMPLEX = "MATCH (l:Lift {cx:$cx})-[:SF_CLOSED]->() RETURN collect(DISTINCT l.facility_id)"

# --- network and contingency (network.py, cuts.py, scripts/network_sweep.py) ------------------------
Q_LIFT_BLAST = (
    "MATCH (l:Node:Lift) WHERE l.facility_id IN $fids WITH l.facility_id AS fid, head(collect(l)) AS l "
    "RETURN fid, l.name, l.station_id, l.od_cut_base, l.od_cut_off, l.od_slow_base, l.detour_max_s, l.detour_mean_s "
    "ORDER BY fid"
)
Q_CRITICAL_PAIRS = (
    "MATCH (a:Node:Lift)-[c:CRITICAL_PAIR]->(b:Node:Lift) WHERE c.scope = 'platform' "
    "RETURN a.facility_id, b.facility_id, a.station_id, c.n, c.dirs ORDER BY c.n DESC, a.facility_id, b.facility_id"
)
Q_CONDITIONAL = (
    "MATCH (a:Node:Lift)-[c:CRITICAL_PAIR]->(b:Node:Lift) WHERE c.scope = 'network' "
    "RETURN a.facility_id, b.facility_id, b.station_id, c.journeys, c.same_station "
    "ORDER BY c.journeys DESC, a.facility_id, b.facility_id"
)
Q_NETWORK_SPOF = (
    "MATCH (l:Node:Lift) WHERE l.od_cut_base > 0 WITH l.facility_id AS fid, head(collect(l)) AS l "
    "RETURN fid, l.name, l.station_id, l.od_cut_base, l.od_cut_off ORDER BY l.od_cut_base DESC, fid"
)
Q_REACHES_FROM = (
    "MATCH (a:Station {uid:$sid})-[r:REACHES]->(b:Station) RETURN b.uid, b.name, r.base_s ORDER BY r.base_s, b.uid"
)
Q_DOMINATES_FOR = "MATCH (l:Node:Lift {facility_id:$fid})-[:DOMINATES_FOR]->(s:Station) RETURN collect(DISTINCT s.uid)"
Q_PLATFORM_CUTS = (
    "MATCH (p:Node:Platform {cx:$cx}) RETURN p.stop_id AS stop, head(collect(p.mincuts_board)), "
    "head(collect(p.mincuts_exit)), head(collect(p.rel_counts_board)), head(collect(p.rel_counts_exit)), "
    "head(collect(p.rel_relevant_board)), head(collect(p.rel_relevant_exit)) ORDER BY stop"
)

# --- lift ledger (data/history, scripts/history_replay.py) -----------------------------------------------------
Q_LIFT_RECORD = (
    "MATCH (l:Lift) WHERE l.facility_id = $fid WITH l ORDER BY l.uid LIMIT 1 "
    "OPTIONAL MATCH (o:Outage)-[:OF]->(l) "
    "RETURN l.avail_12m, l.closed_h_12m, l.outages_12m, l.mttr_h, l.single_svc_h, count(o), sum(o.hours), "
    "max(o.end), sum(CASE WHEN o.imputed THEN 1 ELSE 0 END)"
)
# Redundancy defeated: closures of two lifts that overlapped in time (a critical pair, or the two lifts of a k=2 cut).
Q_PAIR_OVERLAP = (
    "MATCH (x:Outage)-[:OF]->(a:Lift {facility_id:$a}) MATCH (y:Outage)-[:OF]->(b:Lift {facility_id:$b}) "
    "WHERE x.start < y.end AND y.start < x.end "
    "RETURN count(*), collect([CASE WHEN x.start > y.start THEN x.start ELSE y.start END, "
    "CASE WHEN x.end < y.end THEN x.end ELSE y.end END])[0..20]"
)
