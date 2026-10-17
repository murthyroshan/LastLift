# Possible issues in MBTA's GTFS station data (step-free routing)

*Prepared with LastLift (an unofficial prototype) for MBTA's developer contact (developer@mbta.com, the address in `feed_info.feed_contact_email`). Drafted by an AI coding assistant from the checks in `scripts/gtfs_audit.py`; reviewed and sent, if at all, by the author.*

Thank you for publishing pathways, levels and elevator facilities: they make step-free reasoning possible. While building on them we found the items below. We may be misreading some of them; each one lists the evidence rows so it is quick to check.

MobilityData's gtfs-validator 8.0.1 was run first on the same feed; it raises 14 notice types (big_gap_in_service, expired_calendar, fast_travel_between_consecutive_stops, fast_travel_between_far_stops, platform_without_parent_station, route_short_name_too_long, same_name_and_description_for_stop, service_has_no_active_day_of_the_week, stop_too_far_from_shape, stop_without_stop_time, trip_headsign_matches_intermediate_stop, unknown_column, unknown_file, unusable_trip), none of which concerns the items below.

## 1. Elevator pathways named after a different elevator than their facility_id

**Why it matters for step-free routing:** A closure of the named elevator is linked to the wrong pathway, so its effect is modelled wrongly (LastLift corrects Quincy Adams with an override; the others are reported as published).

**Suggested fix:** Set facility_id to the elevator the pathway names (or correct the name).

Evidence:

| pathway_id | facility_id | named |
|---|---|---|
| qamnl-060 | 736 | ['805'] |
| qamnl-061 | 736 | ['805'] |
| sstat-1851 | 753 | ['754'] |
| sstat-1852 | 754 | ['753'] |

## 2. Entrances marked not wheelchair accessible that lead directly to an elevator

**Why it matters for step-free routing:** A step-free route through the elevator starts at this door, but the flag tells routers it cannot be used; LastLift overrides it for Copley.

**Suggested fix:** Check wheelchair_boarding on these entrances.

Evidence:

| entrance | name | via_pathway | to_elevator |
|---|---|---|---|
| door-asmnl-rdexits | Buses | asmnl-015 | ['970'] |
| door-coecl-bpl | Boylston St | coecl-017 | ['976'] |

## 3. Elevator pathways with no facility_id

**Why it matters for step-free routing:** A closure of this elevator cannot be linked to the pathway, so its effect cannot be assessed.

**Suggested fix:** Add the facility_id.

Evidence:

| pathway_id | from | to |
|---|---|---|
| sstat-1856 | node-sstat-busgroundelev-bottom | node-sstat-busgroundelev-top |
| sstat-1857 | node-sstat-busgroundelev-top | node-sstat-busgroundelev-bottom |
| sstat-1862 | node-sstat-busrotundanorthelev-bottom | node-sstat-busrotundanorthelev-top |
| sstat-1863 | node-sstat-busrotundanorthelev-top | node-sstat-busrotundanorthelev-bottom |
| sstat-1866 | node-sstat-busrotundasouthelev-bottom | node-sstat-busrotundasouthelev-top |
| sstat-1867 | node-sstat-busrotundasouthelev-top | node-sstat-busrotundasouthelev-bottom |

## 4. Elevators listed in facilities.txt but used by no pathway, at stations that publish pathways

**Why it matters for step-free routing:** Their closures cannot be assessed against the station layout.

**Suggested fix:** Add the elevator's pathways, or confirm it is not on a public route.

Evidence:

| facility_id | stop_id | name |
|---|---|---|
| 729 | place-brntn | Braintree Elevator 729 (Busway to Commuter Rail platform, parking garage) |
| 730 | place-brntn | Braintree Elevator 730 (Busway to Commuter Rail platform, parking garage) |
| 805 | place-qamnl | Quincy Adams Elevator 805 (Lobby to platform) |

## 5. Platforms marked wheelchair accessible with no step-free route in the published pathways

**Why it matters for step-free routing:** Either the platform is not accessible or a step-free pathway is missing from the data.

**Suggested fix:** Check wheelchair_boarding, or add the missing pathways.

Evidence:

| stop_id | name | platform | board_routes | exit_routes | no_accessible_entrance |
|---|---|---|---|---|---|
| WML-0081-B2 | Newtonville - Washington St @ Walnut St | Outbound Shuttle | None | None | True |
| WML-0081-B3 | Newtonville - Washington St @ Walnut St | Boston Shuttle | None | None | True |
| WML-0091-B2 | West Newton - Washington St @ Cherry St | Outbound Shuttle | None | None | True |
| WML-0091-B3 | West Newton - Washington St @ Highland St | Boston Shuttle | None | None | True |
| WML-0102-B1 | Auburndale - 375 Auburn St | Outbound Shuttle | None | None | True |
| WML-0102-B2 | Auburndale - Auburn St opp Melrose St | Boston Shuttle | None | None | True |
| WR-0053-S | Oak Grove | Commuter Rail - Track 1 (All Trains) | 0 | 0 | False |

## 6. One stop_id covering two physical platforms

**Why it matters for step-free routing:** Riders on one side cannot reach the other side's lift step-free; the data implies they can.

**Suggested fix:** Model the two sides as boarding areas (location_type 4) or separate stops.

Evidence:

| stop_id | station | layout |
|---|---|---|
| 70031 | Sullivan Square | a centre platform and a side platform share this stop_id; trains open on both sides, so one side's riders reach the other side's elevator only by crossing through a train |
| 70033 | Wellington | a centre platform and a side platform share this stop_id; trains open on both sides, so one side's riders reach the other side's elevator only by crossing through a train |

## 7. excludes-stop naming a platform whose only step-free route uses that elevator (a question)

**Why it matters for step-free routing:** The property's meaning is undocumented (228 elevators carry it); read literally (the closure does not affect that stop), it contradicts the pathways for these pairs.

**Suggested fix:** Document what excludes-stop means.

Evidence:

| facility_id | excludes_stop | dir | model |
|---|---|---|---|
| 889 | 70050 | board | only step-free route uses this elevator |
| 951 | 70073 | exit | only step-free route uses this elevator |
| 831 | 70085 | exit | only step-free route uses this elevator |
| 831 | 70086 | exit | only step-free route uses this elevator |
| 954 | 70091 | exit | only step-free route uses this elevator |
| 953 | 70092 | exit | only step-free route uses this elevator |

## 8. Elevator closures published as ACCESS_ISSUE rather than ELEVATOR_CLOSURE

**Why it matters for step-free routing:** Tools that select elevator outages by effect miss these closures.

**Suggested fix:** Use ELEVATOR_CLOSURE for elevator outages, or say when ACCESS_ISSUE is intended.

Evidence:

| facility_id | alerts | name |
|---|---|---|
| 868 | 2 | Broadway Elevator 868 (Lobby to street) |
| 865 | 1 | Wellington Elevator 865 (Forest Hills platform to lobby) |
| 734 | 1 | Wollaston Elevator 734 (Newport Ave lobby to platform) |
| 849 | 1 | Ruggles Elevator 849 (Commuter Rail tracks 1 and 3 to lobby) |
| 901 | 1 | South Station Elevator 901 (Ashmont/Braintree platform to Silver Line drop-off platform and lobby) |
| 51 | 1 | Framingham Elevator 51 (Waverly Street to pedestrian bridge) |
| 983 | 1 | Porter Elevator 983 (Red Line platforms to lobby) |
| 987 | 1 | Porter Elevator 987 (Red Line platforms to lobby) |
| 859 | 1 | Tufts Medical Center Elevator 859 (Forest Hills platform to Washington Street lobby) |
| 860 | 1 | Central Elevator 860 (Alewife platform to Massachusetts Avenue) |
| 841 | 1 | Forest Hills Elevator 841 (Commuter Rail platform to lobby) |
| 905 | 1 | Haymarket Elevator 905 (Underpass to Forest Hills platform) |
| 906 | 1 | Haymarket Elevator 906 (Underpass to Green Line platforms, busway) |
| 908 | 1 | Haymarket Elevator 908 (Green Line lobby to busway, Sudbury Street, New Chardon Street) |
| 930 | 1 | Lynn Elevator 930 (Street to parking garage) |
| 929 | 1 | Lynn Elevator 929 (Street to parking garage) |
| 958 | 1 | Fields Corner Elevator 958 (Paid lobby to Ashmont platform) |

Feed: the GTFS version recorded in LastLift's `claims.json`. Questions or corrections are very welcome.
