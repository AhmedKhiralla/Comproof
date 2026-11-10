-- Comproof 1.2.1: audit chain order under concurrent writers.
--
-- The entry id used to be taken from the sequence (column default) before the chain lock, so when the engine and
-- a user wrote at the same moment, entry N+1 could be linked before entry N. Every hash was correct, but the chain
-- order differed from the id order and "Verify integrity" reported a break that was not tampering.
--
-- 1. New entries take their id inside the chain lock, so id order and chain order are the same.
-- 2. Verification follows the chain by its links (prev_hash -> row_hash), so entries written before this fix
--    verify correctly. It still finds every edited entry (hash mismatch), every removed entry inside the chain
--    (a link to a missing entry), and any fork (two entries claiming the same predecessor).

CREATE OR REPLACE FUNCTION cp_audit_chain() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  k uuid := coalesce(NEW.tenant_id, '00000000-0000-0000-0000-000000000000'::uuid);
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(k::text, 727012));
  NEW.id := nextval('audit_log_id_seq');
  SELECT row_hash INTO NEW.prev_hash FROM audit_log
   WHERE coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid) = k
   ORDER BY id DESC LIMIT 1;
  NEW.row_hash := cp_audit_hash(NEW.prev_hash, cp_audit_payload(NEW));
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION cp_audit_verify(p_tenant uuid) RETURNS TABLE (checked bigint, first_bad_id bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  k uuid := coalesce(p_tenant, '00000000-0000-0000-0000-000000000000'::uuid);
BEGIN
  IF NOT cp_can_access(p_tenant) AND p_tenant IS NOT NULL THEN
    RAISE EXCEPTION 'No access' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN QUERY
  WITH c AS (
    SELECT a.id, a.prev_hash, a.row_hash,
           a.row_hash IS NOT DISTINCT FROM cp_audit_hash(a.prev_hash, cp_audit_payload(a)) AS ok,
           count(*) OVER (PARTITION BY coalesce(a.prev_hash, 'GENESIS')) AS siblings
      FROM audit_log a
     WHERE coalesce(a.tenant_id, '00000000-0000-0000-0000-000000000000'::uuid) = k
  )
  SELECT count(*)::bigint,
         min(c.id) FILTER (WHERE NOT c.ok
                              -- two entries on the same predecessor, or more than one start (fork)
                              OR c.siblings > 1
                              -- a link to an entry that is not there (removed)
                              OR (c.prev_hash IS NOT NULL AND NOT EXISTS (SELECT 1 FROM c p WHERE p.row_hash = c.prev_hash)))
    FROM c;
END $$;
