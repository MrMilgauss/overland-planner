# ADR-020: Road-map regions are chosen in the app; the served map is the truth

## Status
Accepted (slice 12c DESIGN, D299-D306, D311, D313-D315, 2026-11-26). Builds on ADR-013 (Valhalla, Amendment 3 refresh) and Amendment 5. Supersedes D295's setting `ROAD_MAP_AREA` and the idea of a tracked region list.

## Context
- The owner will go to Utah in three months and will not ask for a new set of maps or run a script (D299). He chooses which regions are loaded, sees the size and time first, and picks when the engine is rebuilt (about 40 of about 55 minutes without planning, D300).
- Today the regions live in `deploy/scripts/tiles-refresh.sh` and a copy of their names in `ROAD_MAP_AREA` (D295); the Pi had a gap that routed Milan to Spain by ferry (D296, D297).
- The page must warn when a trail or place is outside the loaded regions and when a trip's stops lie in areas not linked by land (US-28), and say what is loaded and how old it is.
- Constraints: Raspberry Pi 5 with 16 GB, about 25 GB free disk needed for 6.4 GB of extracts; no admin rights for the helper; free, keyless sources; the household's data stays home.

## Decision
1. **The served map is the truth.** The record of the regions (`road-map.json`, regions only, listing what the refresh actually downloaded and built; the refresh is its only writer) and their Geofabrik outlines (`outlines/*.poly`) travel inside `tilesets/<date>/` with the tiles. The planner reads the record of the directory that the engine serves (matched by the tar's modification time against an uncached `/status` epoch). Nothing is a setting; unknown is a state ("Map coverage unknown"). The page never shows a pending choice as loaded.
2. **Catalogue and outlines come from Geofabrik** (free, keyless): `index-v1-nogeom.json` cached 7 days, sizes by HEAD, `.poly` outlines cached. The region key is the index `id` (`italy`, `us/utah`; the real index's ids are unique, every feature has `urls.pbf` and `urls.poly`, every `parent` resolves) and the addresses are the index's own `urls.pbf` and `urls.poly`, written into the request by the planner; the helper only checks the download prefix and refuses `..`. The parent comes from the index's `parent` field and ancestors and descendants (which cannot both be chosen) are found by walking that chain. What leaves the house is exactly the index, the HEAD of the regions shown and the outline of a chosen one; no trip data.
3. **Outlines, not rectangles.** The domain tests containment with the real polygon (rings and holes). A trail is outside when its entry or exit is outside.
4. **Land links are information.** Two regions are linked when their outlines overlap or touch; groups are connected components. The screen names unlinked groups and a trip's stops in several groups get a warning; planning is never refused for it, and an item outside the map is kept and tagged.
5. **One pending change, one rebuild a UTC day, an 8 GB limit** (`ROAD_MAP_MAX_GB`). Estimates: pause 6 minutes a GB, total 8.2 minutes a GB plus 2.5. The UTC-day rule comes from the tileset names in the volume.
6. **A small helper on the Pi does the work** (ADR-013 Amendment 5): a user crontab line runs `road-map-runner.sh`, which validates a request file in a small volume and runs the existing refresh. The planner has no Docker access.

## Alternatives considered
- **A tracked list edited by the owner, then `make tiles-refresh`** (the slice prompt's first idea). Rejected by the owner (D299): "a nerdy script".
- **The docker socket in the planner**, so it runs the refresh itself. Rejected: root-equivalent control of the host for a web application that parses uploads and now makes outbound calls; one bug would reach every household stack on the Pi.
- **A long-lived helper container or a systemd unit.** Rejected: needs root to install or a socket; a user crontab line is removable by the same user with no privileges.
- **Bounding rectangles for "outside".** Rejected: Italy's rectangle holds Corsica, Tunisia's sea and half of Switzerland's neighbours; US-28 needs a trustworthy warning, and the real polygons are only about 6,000 points.
- **Keeping `ROAD_MAP_AREA` or a planner-side region table.** Rejected: a second copy that drifted once already (D295, D296); the record travels with the tiles so a rollback brings back the matching names.
- **Refusing planning across areas not linked by land.** Rejected (D299, DISCUSS): the screen informs; trips inside one area are fine and the owner may still want the item kept.

## Consequences
- Positive: the owner changes the map from the page; the page cannot disagree with the engine; rollback works unchanged.
- Negative: today's served tileset has no record until the first rebuild from the app; the helper adds a cron dependency and about one short container run a minute; the planner reaches Geofabrik; ferries and islands inside an outline are not modelled by the land groups.
- Enforced by: import-linter (`domain-roadmap`, `facade-roadmap`, adapter independence), probes for every adapter (ADR-011 pattern; queue, reader, catalogue, place search), the offline deploy tests for the helper and the refresh, and contract tests recommended for Geofabrik (consumer-driven recorded copies of the index, a `.poly` and a HEAD answer).

**As built (step 13-30, 2026-11-27).** Built as designed, keys being Geofabrik index ids (D315). Deviations: the preview does not refuse `too_big` (only the POST; the page compares sizes); a done `result.txt` names its tileset (`c1d3195`); `bad_request` shows the generic sentence; a leftover `.routing.env.orig` after an interrupted rebuild is logged only (DELIVER check, D314); the route card's "Plan the route" is not disabled while planning is paused. Open: the 8 GB memory risk (D314) is not covered by the gate rebuild, the Pi gate and the owner's cold-start check.
