# Atlas licence check

The Atlas runs the same step-free rules on every feed in the Mobility Database catalogue that publishes
GTFS-Pathways with open access. Every feed counts towards the aggregate figures; an agency is **named** on the site
only when its licence clearly allows reuse with attribution. The gate is [`data/atlas_licences.json`](../data/atlas_licences.json),
applied by `scripts/atlas_sweep.py` and checked by `tests/test_atlas.py`. Checked 18 October 2026, from each
licence link the catalogue gives (or its absence).

| Feed | Agency | Licence found | Decision |
|---|---|---|---|
| mdb-437 | MBTA | MassDOT developer licence agreement | include (our own source) |
| mdb-782 | Verkehrsverbund Berlin-Brandenburg (VBB) | CC BY 4.0, credit VBB | include |
| tdg-67595 | SNCF | ODbL 1.0 (published counts are a produced work; attribution) | include |
| tdg-80921 | Île-de-France Mobilités | Licence Mobilités, built on ODbL; attribution | include |
| mdb-502 | SEPTA | Click-through agreement, revocable, not accepted for this use | exclude |
| mdb-714 | Edmonton Transit System | Catalogue links to another municipality's portal; not verifiable | exclude |
| mdb-2141 | Consorcio de Transportes de Mallorca | Licence page unreachable | exclude |
| mdb-2848 | Sofia Traffic | Data page states no licence | exclude |
| mdb-3357 | DTPM Santiago | Data page states no licence | exclude |
| mdb-3360 | Chennai Transport Corporation | Terms page unreachable | exclude |
| mdb-205 | Metro Transit | No licence in the catalogue | exclude |
| mdb-470 | Maryland Transit Administration | No licence in the catalogue | exclude |
| mdb-1985 | Aeroexpreso | No licence in the catalogue | exclude |
| mdb-2098 | TPBI București–Ilfov | No licence in the catalogue | exclude |

No licence means no permission, so an excluded agency stays unnamed until its terms are confirmed. Excluded feeds
are still counted, without their names, in the 2,884 FalkorDB-versus-exact checks and the aggregate shares.
