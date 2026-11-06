-- PostgreSQL + PostGIS. Execute in an empty project database.
BEGIN;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS logistics;
SET search_path TO logistics, public;

CREATE TABLE IF NOT EXISTS data_source (
 source_key text PRIMARY KEY, title text NOT NULL, url text NOT NULL,
 license text, description text
);
CREATE TABLE IF NOT EXISTS dataset (
 dataset_key text PRIMARY KEY, source_key text NOT NULL REFERENCES data_source,
 retrieved_at timestamptz NOT NULL, source_base_at timestamptz,
 bbox jsonb NOT NULL, query_text text NOT NULL, sha256 text NOT NULL
);
-- One OSM way per row, NOT a topology-ready routing edge.
CREATE TABLE IF NOT EXISTS road_segment (
 osm_way_id bigint PRIMARY KEY,
 dataset_key text NOT NULL REFERENCES dataset,
 name text, ref text, highway text NOT NULL,
 access text, vehicle text, motor_vehicle text, hgv text, goods text,
 hgv_articulated text, oneway text, surface text,
 maxweight_t numeric CHECK(maxweight_t > 0),
 maxweightrating_t numeric CHECK(maxweightrating_t > 0),
 maxaxleload_t numeric CHECK(maxaxleload_t > 0),
 maxheight_m numeric CHECK(maxheight_m > 0),
 maxwidth_m numeric CHECK(maxwidth_m > 0),
 maxlength_m numeric CHECK(maxlength_m > 0),
 osm_version integer, osm_modified_at timestamptz,
 tags jsonb NOT NULL, node_ids jsonb NOT NULL,
 geom geometry(LineString,4326) NOT NULL,
 is_current boolean NOT NULL DEFAULT true,
 CHECK(ST_NPoints(geom) >= 2)
);
CREATE INDEX IF NOT EXISTS road_geom_gix ON road_segment USING gist(geom);
CREATE INDEX IF NOT EXISTS road_geog_gix ON road_segment USING gist((geom::geography));
CREATE INDEX IF NOT EXISTS road_tags_gin ON road_segment USING gin(tags);
CREATE INDEX IF NOT EXISTS road_ref_idx ON road_segment(ref);
CREATE TABLE IF NOT EXISTS point_constraint (
 osm_node_id bigint PRIMARY KEY, dataset_key text NOT NULL REFERENCES dataset,
 tags jsonb NOT NULL, geom geometry(Point,4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS point_geom_gix ON point_constraint USING gist(geom);
CREATE TABLE IF NOT EXISTS turn_restriction_raw (
 osm_relation_id bigint PRIMARY KEY, dataset_key text NOT NULL REFERENCES dataset,
 tags jsonb NOT NULL, members jsonb NOT NULL
);
-- Official/polled/surveyed restrictions are separate from OSM observations.
CREATE TABLE IF NOT EXISTS restriction (
 restriction_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_key text NOT NULL REFERENCES data_source,
 source_url text NOT NULL, document_reference text,
 road_osm_way_id bigint REFERENCES road_segment,
 geom geometry(Geometry,4326),
 restriction_kind text NOT NULL CHECK(restriction_kind IN
 ('access','actual_mass','rated_mass','axle_load','height','width','length','turn','closure','other')),
 vehicle_class text NOT NULL DEFAULT 'hgv',
 direction text NOT NULL DEFAULT 'both' CHECK(direction IN ('both','forward','backward')),
 effect text NOT NULL CHECK(effect IN ('deny','limit','permit','conditional')),
 limit_value numeric CHECK(limit_value > 0), unit text,
 valid_from timestamptz, valid_to timestamptz,
 condition_raw text, exceptions_raw text,
 verification_status text NOT NULL DEFAULT 'unverified'
 CHECK(verification_status IN ('unverified','verified','superseded')),
 checked_at timestamptz, needs_review_after timestamptz,
 CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
 CHECK(effect <> 'limit' OR (limit_value IS NOT NULL AND unit IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS restriction_geom_gix ON restriction USING gist(geom);
CREATE TABLE IF NOT EXISTS property (
 property_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 title text NOT NULL, address text, geom geometry(Point,4326)
);
CREATE TABLE IF NOT EXISTS property_entrance (
 entrance_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 property_id bigint NOT NULL REFERENCES property,
 geom geometry(Point,4326) NOT NULL,
 gate_width_m numeric CHECK(gate_width_m > 0),
 gate_height_m numeric CHECK(gate_height_m > 0),
 turn_area_note text, loading_note text, access_note text,
 source_url text, checked_at timestamptz
);
CREATE TABLE IF NOT EXISTS vehicle_profile (
 profile_key text PRIMARY KEY, title text NOT NULL,
 actual_mass_t numeric NOT NULL CHECK(actual_mass_t > 0),
 rated_mass_t numeric NOT NULL CHECK(rated_mass_t > 0),
 axle_load_t numeric NOT NULL CHECK(axle_load_t > 0),
 height_m numeric NOT NULL CHECK(height_m > 0),
 width_m numeric NOT NULL CHECK(width_m > 0),
 length_m numeric NOT NULL CHECK(length_m > 0),
 articulated boolean NOT NULL,
 CHECK(actual_mass_t <= rated_mass_t)
);
-- Illustrative inputs. Replace with real vehicle/loaded axle measurements.
INSERT INTO vehicle_profile VALUES
 ('van','Пример: малотоннажный',3.5,3.5,2,3,2.2,7,false),
 ('rigid','Пример: средний грузовик',12,12,6,3.6,2.55,10,false),
 ('semi','Пример: автопоезд',40,40,10,4,2.55,16.5,true)
ON CONFLICT(profile_key) DO NOTHING;
CREATE TABLE IF NOT EXISTS accessibility_assessment (
 assessment_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 entrance_id bigint NOT NULL REFERENCES property_entrance,
 profile_key text NOT NULL REFERENCES vehicle_profile,
 departure_at timestamptz NOT NULL, assessed_at timestamptz NOT NULL DEFAULT now(),
 status text NOT NULL CHECK(status IN ('verified_access','restricted','unknown')),
 road_dataset_key text NOT NULL REFERENCES dataset,
 route geometry(LineString,4326), reasons jsonb NOT NULL,
 engine_version text NOT NULL, reviewed_at timestamptz
);
COMMENT ON TABLE road_segment IS 'OSM ways: requires split at intersections, direction handling and turn restrictions before routing.';
COMMENT ON TABLE accessibility_assessment IS 'Nearby road alone is insufficient. Verify continuous vehicle-specific route to the entrance.';
COMMIT;
