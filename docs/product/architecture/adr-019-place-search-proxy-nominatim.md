# ADR-019: Place search by name through a server-side Nominatim proxy

## Status
Accepted (slice 12c DESIGN, D307, 2026-11-26). Owner named the service and its policy in the slice prompt (D298). Fills the `Geocoder` slot (Phase 2) of the brief, renamed `PlaceSearch`.

## Context
- Marco and Giulia add a stop by typing its name (US-29). The service must be free, keyless and fit a household planner; the screen must say that only the typed words leave the house (J-06).
- The public Nominatim service of OpenStreetMap is the service the owner named. Its usage policy (<https://operations.osmfoundation.org/policies/nominatim/>, read 2026-11-26) requires: at most 1 request a second; an identifying User-Agent or Referer; attribution (ODbL, "Search © OpenStreetMap contributors"); no autocomplete or search-as-you-type; no systematic or bulk queries; clients cache results; the operators may switch a client off, so the address must be changeable without a software update; do not submit personal data. It also has a section on LLM-suggested use: such use must point prominently to the policy. This ADR, `.env.example` beside the setting and the search form's fine print do that.
- A browser cannot set the User-Agent header, and several households' browsers would each need their own rate limit and cache.
- Earned Trust: the policy is an external contract that can change or switch us off; the design must say what happens when the service lies, is down or says no.

## Decision
1. **A server-side proxy** `GET /api/places/search?q=` (adapter `NominatimPlaceSearch`, package `adapters/geocoding`, port `PlaceSearch`). The browser calls only the planner.
2. **Configuration.** `PLACE_SEARCH=on|off`, default on (empty is the default, like every setting; in the Pi's `.env` off is the line `PLACE_SEARCH=off`): off means the Add menu shows three entries and the route answers 503. `PLACE_SEARCH_URL` default `https://nominatim.openstreetmap.org/search`; empty means the default, so it is never the off switch. No contact email is sent (D313). Changing either needs an `.env` edit and a restart, no new release.
3. **Request.** User-Agent `overland-planner/<version> (household trip planner; +https://github.com/MrMilgauss/overland-planner)`; `format=jsonv2`, `addressdetails=1`, `limit=5`; nothing but the typed words is sent (the service necessarily sees the home internet address, as the map tiles do; the fine print says "from your home connection"). Sent on "Search" or Enter only.
4. **Rate limit, back-off and cache.** One request a second across the process (one worker: one lock and the monotonic time of the last call; a waiting request is held for at most 3 s, then answers "busy"). After a 429 or a 503 the adapter makes no call for 60 seconds and answers "isn't answering". An in-memory cache of recent answers (200 entries, 24 h), never written to disk, never listed: it satisfies the policy's caching rule and is not a search history. This overrides the DISCUSS line "caching OUT" (whose intent was no history).
5. **Failure words.** Down, 429, 5xx, a timeout over 10 s, an unreadable body, busy, or switched off -> "The place search isn't answering. Try again in a minute, or add the place another way."; an empty answer -> "No place found for "<q>". Try another spelling, or add it by clicking on the map." The trip is never changed by a failed search.
6. **Probe.** No outbound call at start-up (a query at every start is systematic use). The probe checks the address and a rate-limiter, back-off and cache round trip with the fake clock. The live service is checked by hand with one query, never in CI.
7. **Contract tests recommended** for Nominatim: consumer-driven, recorded real `jsonv2` answers replayed with respx (found, empty, 429, 5xx, a result without `name`).

## Alternatives considered
- **Browser calls Nominatim directly.** Rejected: cannot set the User-Agent, no shared rate limit or cache, no switch without a release, and every browser's address and typing time reach the service. It also breaks the single place that states what leaves the house.
- **Photon (`photon.komoot.io`) as the default.** Rejected as default: not the service the owner named, its terms are looser but it is a single company's best-effort service, and its answers have another shape (a second parser). **There is no working fallback until a second parser exists** (D315): pointing `PLACE_SEARCH_URL` at Photon would fail on its answer shape; the parser is built only if the owner asks.
- **Paid or keyed geocoders (Mapbox, Google, LocationIQ and similar).** Rejected: the slice forbids a key, a hosted or paid service (OUT); a key would also live in the repository's deploy files.
- **Self-hosted Nominatim.** Rejected: tens of GB of import and a database on a Pi that already hosts Valhalla; absurd for a household.
- **Offline name list.** Rejected: OUT in the brief and a large data set to build and keep fresh.

## Consequences
- Positive: the policy is met in one place; the switch is a setting; the page can state the credit and what leaves the house.
- Negative: the planner container makes outbound HTTPS calls (the first non-engine ones, with ADR-020's catalogue); an operator's block of our User-Agent ends the feature until the setting changes; the 1-second spacing makes a second concurrent user wait.
- Enforced by: the adapter's own limiter test with a fake clock; import-linter keeps `httpx` out of `application` and `domain`; `adapters.geocoding` is in the adapter-independence contract.
