-- Open data/processed/saratov_roads.sqlite with a SQLite client.
SELECT name,ref,highway,hgv,maxweight_t,maxheight_m,osm_way_id
FROM road_segment ORDER BY ref,name;

SELECT COUNT(*) AS ways,
 SUM(hgv IS NOT NULL) AS with_hgv_tag,
 SUM(maxweight_t IS NOT NULL) AS with_mass_limit
FROM road_segment;

SELECT name,ref,COUNT(*) AS ways
FROM road_segment WHERE highway IN ('motorway','trunk','primary')
GROUP BY name,ref ORDER BY ways DESC;

SELECT osm_way_id,name,json_extract(tags_json,'$."hgv:conditional"') AS condition
FROM road_segment WHERE tags_json LIKE '%:conditional%';
