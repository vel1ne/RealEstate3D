SET search_path TO logistics, public;

-- Catalog of explicit observations, never a list of guaranteed truck access.
SELECT osm_way_id, name, ref, highway, hgv, maxweight_t, maxheight_m,
       tags->>'hgv:conditional' AS hgv_conditional
FROM road_segment WHERE is_current
ORDER BY ref NULLS LAST, name NULLS LAST;

-- Source completeness. NULL means unknown, not unrestricted.
SELECT count(*) AS ways,
 count(*) FILTER(WHERE hgv IS NOT NULL) AS with_hgv_tag,
 count(*) FILTER(WHERE maxweight_t IS NOT NULL) AS with_mass_limit,
 count(*) FILTER(WHERE maxheight_m IS NOT NULL) AS with_height_limit
FROM road_segment WHERE is_current;

-- Nearest roads to a REAL property entrance (replace ID=1).
-- Distance is in metres and does not prove road-to-entrance connectivity.
SELECT r.osm_way_id, r.name, r.ref,
 round(ST_Distance(r.geom::geography,e.geom::geography)::numeric,1) AS straight_line_m
FROM property_entrance e JOIN road_segment r
 ON r.is_current AND ST_DWithin(r.geom::geography,e.geom::geography,1000)
WHERE e.entrance_id=1
ORDER BY straight_line_m LIMIT 10;

-- Evidence that could apply NOW, still requiring condition/exception evaluation.
SELECT * FROM restriction
WHERE verification_status='verified'
 AND (valid_from IS NULL OR valid_from<=now())
 AND (valid_to IS NULL OR valid_to>now())
 AND (needs_review_after IS NULL OR needs_review_after>now());

-- Direct hgv=no observations without conditional tags.
-- This is a review queue, not an implementation of all traffic rules.
SELECT osm_way_id,name,tags
FROM road_segment
WHERE is_current AND hgv='no'
 AND NOT EXISTS (SELECT 1 FROM jsonb_object_keys(tags) AS k(key)
                 WHERE k.key LIKE '%:conditional%');
