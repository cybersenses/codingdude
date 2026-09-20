# GIS & Spatial Computing Checklist

As of: 2026-09-20
Sources: msitarzewski/agency-agents — gis division (spatial-data-engineer, web-gis-developer, geoprocessing, cartography, analyst, BIM, GeoAI; 13 personas) + spatial-computing division (visionOS, XR immersive/interface, Metal; 6 personas)
https://github.com/msitarzewski/agency-agents/tree/main/gis
https://github.com/msitarzewski/agency-agents/tree/main/spatial-computing

Use when: building mapping/location features, geoprocessing pipelines, or XR/spatial interfaces.

## Geospatial data & pipelines

- [ ] Reproject explicitly, never assume source CRS — verify against spatial-reference metadata before any analysis or overlay.
- [ ] Preserve source data: pipeline is read → transform → write-to-new-location; originals are immutable.
- [ ] Config-driven pipelines: paths, CRS codes, and field mappings in config, never hardcoded.
- [ ] Test with real production data — unit tests on toy geometries miss real-world edge cases (self-intersections, antimeridian crossings, invalid topologies).
- [ ] Validate geometry before operations (topology checks); garbage-in geometry fails far from the cause.

## Web maps

- [ ] Never load all features at once: cluster, tile, or filter — 10k+ simultaneous features kills render performance.
- [ ] Touch is a first-class input: pinch-zoom, tap-to-identify must work on phones, not just mouse.
- [ ] Cartographic legibility beats completeness: generalize/simplify at low zooms; label collision handled, not ignored.
- [ ] Basemap/attribution/licensing obligations honored in the data model, not just the footer.

## XR / spatial interfaces

- [ ] Comfort before spectacle: locomotion options, no forced camera motion, session-length awareness (motion-sickness budget).
- [ ] Spatial UI anchored to world/space, not screen pixels; depth cues and reachability within arm's envelope.
- [ ] Pass-through/permission failures degrade gracefully — the app must be usable when tracking or scene understanding drops.
- [ ] Performance target is the frame budget at device refresh (e.g. 90fps) with headroom; dropped frames cause physical discomfort, not just jank.

## Failure modes (observed in source personas)

- CRS mismatches silently producing offsets measured in meters-to-kilometers, discovered after publication.
- GeoJSON with thousands of unclustered points shipped to mobile.
- XR demos optimized for the 2-minute pitch, unwatchable at 10 minutes.

## Rejected

- Per-tool tutorials (QGIS/PostGIS/ArcGIS recipes, RealityKit API walkthroughs) and the 13-persona split — one division, one checklist.
