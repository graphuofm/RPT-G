-- rptg_member(exec id, pattern vertex, vertex id): is the vertex id in the candidate bitmap of that
-- pattern vertex for that execution? Added to scans by the pg_rptg planner hook; true if nothing is published.
CREATE FUNCTION rptg_member(int, int, int) RETURNS boolean
  AS 'MODULE_PATHNAME', 'rptg_member' LANGUAGE C STRICT PARALLEL SAFE COST 1;
