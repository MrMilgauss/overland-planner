# Road-map fixtures (slice 12c)

Small, real inputs for the road-map scenarios. Nothing here is fetched at test time.

- `poly/*.poly` (10 files: italy, spain, switzerland, austria, rhone-alpes, provence-alpes-cote-d-azur,
  languedoc-roussillon, midi-pyrenees, portugal, andorra): region outlines downloaded from Geofabrik
  (https://download.geofabrik.de/) on 2026-11-26, unchanged. Data (c) OpenStreetMap contributors, licensed under the
  Open Database Licence (ODbL) 1.0, https://www.openstreetmap.org/copyright.
- `poly/utah.poly`: NOT Geofabrik data. A hand-made rectangle (lon -114.05 to -109.04, lat 37.0 to 42.0) standing in
  for Utah, so the scenarios have a region outside Europe. No licence issue; it is not an outline of anything real.
- `geofabrik-index-trimmed.json`: the Geofabrik index (`index-v1-nogeom.json`, 554 features on 2026-11-26) cut to the 19
  features the scenarios use (the ten regions above, Utah, United States of America, California, North America, Europe,
  France, Germany, and the two regions named "Georgia", one in Europe and one in the United States), each reduced to
  `id`, `name`, `parent`, `urls.poly` and `urls.pbf`. Same licence as above.

Region sizes are not in the index (the planner asks for them with one HEAD per result); the scenarios' fake file
server answers with the sizes named in `steps/road_map_steps.py`, chosen so that today's eight regions add up to 6.4 GB.
