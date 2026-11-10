-- Comproof 1.2.1: entries written by the pre-1.2.1 race sit on a one-entry side branch (linked to a
-- later-numbered entry). Verification accepts exactly that pattern; any other fork, edit or removal is still found.

CREATE OR REPLACE FUNCTION cp_audit_verify(p_tenant uuid) RETURNS TABLE (checked bigint, first_bad_id bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  k uuid := coalesce(p_tenant, '00000000-0000-0000-0000-000000000000'::uuid);
BEGIN
  IF NOT cp_can_access(p_tenant) AND p_tenant IS NOT NULL THEN
    RAISE EXCEPTION 'No access' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN QUERY
  WITH a AS (
    SELECT x.id, x.prev_hash, x.row_hash,
           x.row_hash IS NOT DISTINCT FROM cp_audit_hash(x.prev_hash, cp_audit_payload(x)) AS ok
      FROM audit_log x
     WHERE coalesce(x.tenant_id, '00000000-0000-0000-0000-000000000000'::uuid) = k
  ), c AS (
    -- An entry linked to a later-numbered entry was written by the pre-1.2.1 race: it holds its own correct hash
    -- but sits on a side branch of one entry. Nothing can link after it (writers link to the highest id).
    SELECT a.*, p.id AS parent_id, (p.id IS NOT NULL AND p.id > a.id) AS race_leaf
      FROM a LEFT JOIN a p ON p.row_hash = a.prev_hash
  ), s AS (
    SELECT c.*, count(*) FILTER (WHERE NOT c.race_leaf) OVER (PARTITION BY coalesce(c.prev_hash, 'GENESIS')) AS siblings
      FROM c
  )
  SELECT count(*)::bigint,
         min(s.id) FILTER (WHERE NOT s.ok
                              -- a link to an entry that is not there (removed)
                              OR (s.prev_hash IS NOT NULL AND s.parent_id IS NULL)
                              -- two entries on the same predecessor, or more than one start (fork)
                              OR (NOT s.race_leaf AND s.siblings > 1)
                              -- a side-branch entry that something links to
                              OR (s.race_leaf AND EXISTS (SELECT 1 FROM c ch WHERE ch.prev_hash = s.row_hash)))
    FROM s;
END $$;
