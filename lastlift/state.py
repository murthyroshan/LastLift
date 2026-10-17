"""Graph state: scopes (base / demo / live), closure sync, recompute, and what-if copies.

* base  - the pinned GTFS model with no closures and baseline redundancy (seeded from the snapshot)
* demo  - base + the frozen 15 Oct alert snapshot (the judged default; deterministic)
* live  - base + current alerts (collector or MBTA API)
* wi_*  - what-if copies of a scope with extra simulated closures; never mutate their parent

Closures are relationship-type swaps (SF <-> SF_CLOSED) on lift edges, applied as an idempotent
desired state. After a sync, only complexes whose closed set changed are recomputed.
"""
import atexit
import hashlib
import os
import threading
from collections import OrderedDict

from . import db, redundancy
from .config import settings
from .queries import (Q_CLEAR_DEPENDS_NOW, Q_CLOSE_LIFTS, Q_CLOSED_FACILITIES, Q_COMPLEX_PLATFORMS,
                      Q_COMPLEX_STREETS, Q_CREATE_DEPENDS, Q_LIFT_COMPLEXES, Q_REOPEN_LIFTS, Q_SET_PLATFORM_NOW)

WHAT_IF_LRU = 2
_lock = threading.Lock()
_what_ifs: "OrderedDict[str, str]" = OrderedDict()
_what_if_sync: dict[str, dict] = {}      # copy name -> the sync result when it was made (a reuse reports the same)


def graph_name(scope: str) -> str:
    return settings.graph(scope)


def exists(scope_graph: str) -> bool:
    return scope_graph in db.client().list_graphs()


def ensure_scope(scope: str, closed_fids=None):
    """Create a scope graph as a copy of base if missing, then sync it to the closed set."""
    name = graph_name(scope)
    if not exists(name):
        db.client().connection.execute_command("GRAPH.COPY", graph_name("base"), name)
    if closed_fids is not None:
        return sync(name, closed_fids)
    return {"graph": name, "closed": closed(name)}


def closed(name: str) -> list[str]:
    rs = db.client().select_graph(name).ro_query(Q_CLOSED_FACILITIES).result_set
    return sorted(rs[0][0]) if rs else []


def recompute(name: str, complexes) -> dict:
    """Recompute live k, cuts and DEPENDS_NOW for the given complexes."""
    g = db.client().select_graph(name)
    results = {}
    for cx in sorted(complexes):
        edges, lift_facility = redundancy.complex_edges(g, cx)
        streets = g.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
        depends = []
        for stop_id, uids, pname, wb, plat_name in g.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set:
            r = redundancy.platform(g, cx, uids, streets, edges, lift_facility)
            if r is None:
                continue
            b, e = r["board"], r["exit"]
            g.query(Q_SET_PLATFORM_NOW, {"stop": stop_id, "kb": b.k, "ke": e.k, "ab": b.at_grade, "ae": e.at_grade,
                                         "cb": b.cut_facilities, "ce": e.cut_facilities})
            for dname, d in (("board", b), ("exit", e)):
                depends += [{"stop": stop_id, "fid": f, "dir": dname} for f in d.spof_facilities]
            results[stop_id] = {"name": pname, "platform_name": plat_name, "board": b, "exit": e}
        g.query(Q_CLEAR_DEPENDS_NOW, {"cx": cx})
        if depends:
            g.query(Q_CREATE_DEPENDS.format(rel="DEPENDS_NOW"), {"rows": depends})
    return results


def sync(name: str, closed_fids) -> dict:
    """Make the graph's closed lifts exactly `closed_fids`; recompute only what changed."""
    want = sorted(set(closed_fids))
    with _lock:
        g = db.client().select_graph(name)
        before = set(closed(name))
        g.query(Q_REOPEN_LIFTS, {"fids": want})
        if want:
            g.query(Q_CLOSE_LIFTS, {"fids": want})
        changed = sorted(before ^ set(want))
        cxs = g.ro_query(Q_LIFT_COMPLEXES, {"fids": changed}).result_set[0][0] if changed else []
        results = recompute(name, cxs) if cxs else {}
    return {"graph": name, "closed": want, "changed": changed, "complexes": sorted(cxs), "recomputed": results}


def what_if(scope: str, extra_fids) -> dict:
    """Copy a scope, close extra lifts on the copy, recompute, and return (copy name, sync result).
    The parent scope is never modified. At most WHAT_IF_LRU copies are kept."""
    parent = graph_name(scope)
    base_closed = closed(parent)
    want = sorted(set(base_closed) | set(extra_fids))
    # The process id is part of the name: two processes (the API and a script, say) never share a copy,
    # so one process's LRU eviction can never delete a copy the other is still reading.
    key = hashlib.sha1(f"{os.getpid()}|{parent}|{','.join(want)}".encode()).hexdigest()[:12]
    name = graph_name(f"wi_{key}")
    fresh = False
    with _lock:
        if name in _what_ifs and exists(name) and name in _what_if_sync:
            _what_ifs.move_to_end(name)
        else:
            fresh = True
            _what_ifs.pop(name, None)       # cached but gone (e.g. swept at boot): make it again
            if exists(name):
                db.client().select_graph(name).delete()
            db.client().connection.execute_command("GRAPH.COPY", parent, name)
            _what_ifs[name] = parent
            while len(_what_ifs) > WHAT_IF_LRU:
                old, _ = _what_ifs.popitem(last=False)
                _what_if_sync.pop(old, None)
                if exists(old):
                    db.client().select_graph(old).delete()
    if fresh:
        _what_if_sync[name] = sync(name, want)
    return {"copy": name, "parent": parent, "parent_closed": base_closed, **_what_if_sync[name]}


@atexit.register
def drop_own_what_ifs():
    """At exit, delete the what-if copies this process made (scripts and tests too, not just the API): copies are
    full graphs, and the shared development instance has a small memory limit."""
    mine = f"_{os.getpid()}"
    try:
        names = list(_what_ifs) + [g for g in db.client().list_graphs()
                                   if g.startswith(graph_name("wi_")) and g.endswith(mine)]
        for name in names:
            if exists(name):
                db.client().select_graph(name).delete()
    except Exception:                       # the graph server may already be gone at exit
        pass


def sweep_stale_what_ifs():
    """Delete what-if copies left by a previous process (called at boot)."""
    prefix = graph_name("wi_")
    with _lock:
        _what_ifs.clear()
        _what_if_sync.clear()
        for g in db.client().list_graphs():
            if g.startswith(prefix):
                db.client().select_graph(g).delete()
