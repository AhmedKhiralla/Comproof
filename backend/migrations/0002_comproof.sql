-- Comproof Phase 1: products, packaging components, the controlled file store, approved artwork
-- versions, comparisons, reviewer decisions and electronic signatures.
--
-- Records rules (21 CFR Part 11 §11.10)
--   * Files are content-addressed by SHA-256 and can only be inserted, never changed or removed.
--   * Reviewer decisions and signatures are append-only: a new decision supersedes the previous one,
--     and both stay in the record.
--   * Status changes of comparisons and artwork versions are checked by the database: an approval
--     or rejection is only possible together with the matching electronic signature, and an
--     approved comparison can no longer change.

-- Engine settings per company (AI provider, extra administrative phrases to ignore...).
ALTER TABLE tenants ADD COLUMN engine jsonb NOT NULL DEFAULT '{}'::jsonb;

-- ---------------------------------------------------------------- products and components
CREATE TABLE products (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id),
  code            text NOT NULL CHECK (code ~ '^[A-Z0-9][A-Z0-9._/-]{0,39}$'),
  name            text NOT NULL CHECK (length(trim(name)) > 0),
  name_ar         text,
  generic_name    text,
  strengths       text,
  dosage_form     text,
  registration_no text,
  markets         text[] NOT NULL DEFAULT '{}',
  active          boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  created_by      uuid,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  updated_by      uuid,
  UNIQUE (tenant_id, code)
);

CREATE TABLE components (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  product_id  uuid NOT NULL REFERENCES products(id),
  code        text NOT NULL CHECK (code ~ '^[A-Z0-9][A-Z0-9._/-]{0,39}$'),
  kind        text NOT NULL CHECK (kind IN ('leaflet', 'carton', 'label', 'sachet', 'blister_foil', 'tube', 'other')),
  name        text NOT NULL CHECK (length(trim(name)) > 0),
  languages   text[] NOT NULL DEFAULT '{en,ar}',
  market      char(2),
  notes       text,
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  created_by  uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  updated_by  uuid,
  UNIQUE (tenant_id, code)
);
CREATE INDEX components_product_idx ON components (product_id);

-- ---------------------------------------------------------------- controlled file store
CREATE TABLE files (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id),
  sha256       text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  filename     text NOT NULL,
  mime         text NOT NULL,
  size_bytes   bigint NOT NULL CHECK (size_bytes > 0),
  page_count   integer,
  doc_kind     text CHECK (doc_kind IN ('pdf-vector', 'pdf-scan', 'image', 'docx')),
  purpose      text NOT NULL DEFAULT 'input' CHECK (purpose IN ('input', 'result', 'export')),
  storage_key  text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  created_by   uuid,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  updated_by   uuid
);
CREATE INDEX files_sha_idx ON files (tenant_id, sha256);

-- ---------------------------------------------------------------- approved artwork versions
CREATE TABLE artwork_versions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id),
  component_id    uuid NOT NULL REFERENCES components(id),
  version         text NOT NULL CHECK (version ~ '^[A-Za-z0-9._-]{1,20}$'),
  file_id         uuid NOT NULL REFERENCES files(id),
  status          text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'effective', 'superseded', 'withdrawn')),
  effective_from  date,
  change_control  text,
  authority_ref   text,                 -- e.g. EDA approval reference
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  created_by      uuid,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  updated_by      uuid,
  UNIQUE (component_id, version)
);
CREATE UNIQUE INDEX artwork_one_effective ON artwork_versions (component_id) WHERE status = 'effective';

-- ---------------------------------------------------------------- comparisons
CREATE TABLE comparison_counters (
  tenant_id  uuid NOT NULL REFERENCES tenants(id),
  year       integer NOT NULL,
  last_no    integer NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, year)
);

CREATE TABLE comparisons (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id),
  site_id            uuid NOT NULL REFERENCES sites(id),
  number             text NOT NULL,
  title              text NOT NULL CHECK (length(trim(title)) > 0),
  purpose            text NOT NULL DEFAULT 'proof' CHECK (purpose IN ('proof', 'printed_sample', 'supplier_proof')),
  component_id       uuid REFERENCES components(id),
  artwork_version_id uuid REFERENCES artwork_versions(id),
  reference_file_id  uuid NOT NULL REFERENCES files(id),
  test_file_id       uuid NOT NULL REFERENCES files(id),
  supplier           text,
  reference_no       text,
  settings           jsonb NOT NULL DEFAULT '{}'::jsonb,
  status             text NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued', 'running', 'review', 'approved', 'rejected', 'failed', 'cancelled')),
  progress           text,
  engine_version     text,
  ai_models          jsonb,
  result_sha256      text,
  result_summary     jsonb,
  error              text,
  started_at         timestamptz,
  finished_at        timestamptz,
  closed_at          timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  created_by         uuid,
  updated_at         timestamptz NOT NULL DEFAULT now(),
  updated_by         uuid,
  UNIQUE (tenant_id, number)
);
CREATE INDEX comparisons_tenant_time_idx ON comparisons (tenant_id, created_at DESC);
CREATE INDEX comparisons_queue_idx ON comparisons (created_at) WHERE status = 'queued';

-- ---------------------------------------------------------------- decisions and signatures
CREATE TABLE finding_decisions (
  id             bigserial PRIMARY KEY,
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  comparison_id  uuid NOT NULL REFERENCES comparisons(id),
  finding_id     text NOT NULL CHECK (finding_id ~ '^[A-Z][0-9]{1,6}$'),
  decision       text NOT NULL CHECK (decision IN ('confirmed', 'not_deviation')),
  comment        text,
  user_id        uuid NOT NULL,
  user_name      text NOT NULL,
  decided_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (decision = 'confirmed' OR length(trim(coalesce(comment, ''))) >= 3)
);
CREATE INDEX finding_decisions_idx ON finding_decisions (comparison_id, finding_id, id DESC);

CREATE TABLE signatures (
  id           bigserial PRIMARY KEY,
  tenant_id    uuid NOT NULL REFERENCES tenants(id),
  entity       text NOT NULL CHECK (entity IN ('comparison', 'artwork_version')),
  record_id    uuid NOT NULL,
  record_label text NOT NULL,
  meaning      text NOT NULL CHECK (meaning IN ('reviewed', 'approved', 'rejected', 'approved_master', 'withdrawn')),
  statement    text NOT NULL,
  reason       text,
  record_hash  text NOT NULL,           -- SHA-256 of the result or file that was signed
  user_id      uuid NOT NULL,
  user_name    text NOT NULL,
  user_email   text NOT NULL,
  signed_at    timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX signatures_record_idx ON signatures (entity, record_id, id);

-- ---------------------------------------------------------------- stamping
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['products', 'components', 'files', 'artwork_versions', 'comparisons'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION cp_stamp()', t || '_stamp', t);
  END LOOP;
END $$;

-- ---------------------------------------------------------------- record rules
CREATE OR REPLACE FUNCTION cp_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% records cannot be changed or removed', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER files_append_only BEFORE UPDATE OR DELETE ON files FOR EACH ROW EXECUTE FUNCTION cp_append_only();
CREATE TRIGGER decisions_append_only BEFORE UPDATE OR DELETE ON finding_decisions FOR EACH ROW EXECUTE FUNCTION cp_append_only();
CREATE TRIGGER signatures_append_only BEFORE UPDATE OR DELETE ON signatures FOR EACH ROW EXECUTE FUNCTION cp_append_only();
CREATE TRIGGER comparisons_no_delete BEFORE DELETE ON comparisons FOR EACH ROW EXECUTE FUNCTION cp_append_only();
CREATE TRIGGER artwork_no_delete BEFORE DELETE ON artwork_versions FOR EACH ROW EXECUTE FUNCTION cp_append_only();

-- A decision can only be recorded while the comparison is in review.
CREATE OR REPLACE FUNCTION cp_decision_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE st text;
BEGIN
  SELECT status INTO st FROM comparisons WHERE id = NEW.comparison_id;
  IF st IS DISTINCT FROM 'review' THEN
    RAISE EXCEPTION 'Decisions can only be recorded while the comparison is in review (it is %)', st
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER finding_decisions_guard BEFORE INSERT ON finding_decisions FOR EACH ROW EXECUTE FUNCTION cp_decision_guard();

-- Allowed status changes. Approval and rejection need the signature, written first in the same transaction.
CREATE OR REPLACE FUNCTION cp_comparison_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('approved', 'rejected', 'cancelled') THEN
    RAISE EXCEPTION 'Comparison % is closed and can no longer change', OLD.number USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    IF NOT ((OLD.status = 'queued'  AND NEW.status IN ('running', 'cancelled'))
         OR (OLD.status = 'running' AND NEW.status IN ('review', 'failed', 'queued'))
         OR (OLD.status = 'review'  AND NEW.status IN ('approved', 'rejected'))
         OR (OLD.status = 'failed'  AND NEW.status = 'queued')) THEN
      RAISE EXCEPTION 'A comparison cannot go from % to %', OLD.status, NEW.status USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IN ('approved', 'rejected') AND NOT EXISTS (
        SELECT 1 FROM signatures s WHERE s.entity = 'comparison' AND s.record_id = NEW.id
           AND s.meaning = NEW.status AND s.record_hash = NEW.result_sha256) THEN
      RAISE EXCEPTION 'An electronic signature is required to mark comparison % as %', OLD.number, NEW.status
        USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IN ('approved', 'rejected') THEN
      NEW.closed_at := now();
    END IF;
  END IF;
  -- The inputs and the result never change once recorded.
  IF NEW.reference_file_id IS DISTINCT FROM OLD.reference_file_id OR NEW.test_file_id IS DISTINCT FROM OLD.test_file_id
     OR (OLD.result_sha256 IS NOT NULL AND NEW.result_sha256 IS DISTINCT FROM OLD.result_sha256 AND OLD.status <> 'running')
     OR NEW.number IS DISTINCT FROM OLD.number THEN
    RAISE EXCEPTION 'The files and result of a comparison cannot be changed' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER comparisons_guard BEFORE UPDATE ON comparisons FOR EACH ROW EXECUTE FUNCTION cp_comparison_guard();

CREATE OR REPLACE FUNCTION cp_artwork_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE fsha text;
BEGIN
  IF OLD.status IN ('superseded', 'withdrawn') THEN
    RAISE EXCEPTION 'Artwork version % is closed', OLD.version USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status <> 'draft' AND (NEW.file_id IS DISTINCT FROM OLD.file_id OR NEW.version IS DISTINCT FROM OLD.version
                                OR NEW.component_id IS DISTINCT FROM OLD.component_id) THEN
    RAISE EXCEPTION 'An effective artwork cannot be changed; register a new version' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    IF NOT ((OLD.status = 'draft' AND NEW.status IN ('effective', 'withdrawn'))
         OR (OLD.status = 'effective' AND NEW.status IN ('superseded', 'withdrawn'))) THEN
      RAISE EXCEPTION 'An artwork version cannot go from % to %', OLD.status, NEW.status USING ERRCODE = 'check_violation';
    END IF;
    SELECT sha256 INTO fsha FROM files WHERE id = NEW.file_id;
    IF NEW.status = 'effective' AND NOT EXISTS (
        SELECT 1 FROM signatures s WHERE s.entity = 'artwork_version' AND s.record_id = NEW.id
           AND s.meaning = 'approved_master' AND s.record_hash = fsha) THEN
      RAISE EXCEPTION 'An electronic signature is required to make artwork version % effective', NEW.version
        USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'withdrawn' AND NOT EXISTS (
        SELECT 1 FROM signatures s WHERE s.entity = 'artwork_version' AND s.record_id = NEW.id AND s.meaning = 'withdrawn') THEN
      RAISE EXCEPTION 'An electronic signature is required to withdraw artwork version %', NEW.version
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER artwork_versions_guard BEFORE UPDATE ON artwork_versions FOR EACH ROW EXECUTE FUNCTION cp_artwork_guard();

-- Next comparison number for the caller's company: CP-2026-00001.
CREATE OR REPLACE FUNCTION cp_next_comparison_number(p_tenant uuid) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE y integer := extract(year FROM now() AT TIME ZONE 'UTC'); n integer;
BEGIN
  INSERT INTO comparison_counters (tenant_id, year, last_no) VALUES (p_tenant, y, 1)
  ON CONFLICT (tenant_id, year) DO UPDATE SET last_no = comparison_counters.last_no + 1
  RETURNING last_no INTO n;
  RETURN 'CP-' || y || '-' || lpad(n::text, 5, '0');
END $$;

-- The engine picks queued work for any company. Returns the comparison and its company only;
-- everything else is read afterwards under that company's own security context.
CREATE OR REPLACE FUNCTION cp_claim_comparison() RETURNS TABLE (id uuid, tenant_id uuid, created_by uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  RETURN QUERY
    SELECT c.id, c.tenant_id, c.created_by FROM comparisons c
     WHERE c.status = 'queued' ORDER BY c.created_at
     LIMIT 1 FOR UPDATE SKIP LOCKED;
END $$;

-- Work left "running" by a server that stopped is put back in the queue at start-up.
CREATE OR REPLACE FUNCTION cp_requeue_interrupted() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE n integer;
BEGIN
  PERFORM set_config('app.user_name', 'Comproof engine', true);
  UPDATE comparisons SET status = 'queued', progress = 'Restarted after a server restart'
   WHERE status = 'running';
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;

-- ---------------------------------------------------------------- audit
CREATE OR REPLACE FUNCTION cp_audit_label(tbl text, j jsonb) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT CASE tbl
    WHEN 'comparisons' THEN j ->> 'number'
    WHEN 'artwork_versions' THEN (SELECT c.code FROM components c WHERE c.id = (j ->> 'component_id')::uuid) || ' v' || (j ->> 'version')
    WHEN 'files' THEN j ->> 'filename'
    WHEN 'finding_decisions' THEN (SELECT c.number FROM comparisons c WHERE c.id = (j ->> 'comparison_id')::uuid) || ' ' || (j ->> 'finding_id')
    WHEN 'signatures' THEN (j ->> 'record_label') || ' · ' || (j ->> 'meaning')
    ELSE coalesce(j ->> 'code', j ->> 'email', j ->> 'name', j ->> 'role') END
$$;

-- Same as the foundation audit function, with readable labels for the Comproof tables.
CREATE OR REPLACE FUNCTION cp_audit_row() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  old_j  jsonb := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
  new_j  jsonb := CASE WHEN TG_OP IN ('UPDATE', 'INSERT') THEN to_jsonb(NEW) END;
  ref_j  jsonb := coalesce(new_j, old_j);
  o      jsonb := '{}'::jsonb;
  n      jsonb := '{}'::jsonb;
  k      text;
  v_tenant uuid;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    FOR k IN SELECT jsonb_object_keys(new_j) LOOP
      CONTINUE WHEN cp_audit_ignored(k);
      IF (old_j -> k) IS DISTINCT FROM (new_j -> k) THEN
        IF cp_audit_redacted(k) THEN
          o := o || jsonb_build_object(k, '[redacted]');
          n := n || jsonb_build_object(k, '[changed]');
        ELSE
          o := o || jsonb_build_object(k, old_j -> k);
          n := n || jsonb_build_object(k, new_j -> k);
        END IF;
      END IF;
    END LOOP;
    IF n = '{}'::jsonb THEN
      RETURN NEW;
    END IF;
  ELSE
    FOR k IN SELECT jsonb_object_keys(ref_j) LOOP
      CONTINUE WHEN cp_audit_ignored(k);
      IF cp_audit_redacted(k) THEN
        IF TG_OP = 'INSERT' THEN n := n || jsonb_build_object(k, '[set]'); END IF;
      ELSIF TG_OP = 'INSERT' THEN
        n := n || jsonb_build_object(k, ref_j -> k);
      ELSE
        o := o || jsonb_build_object(k, ref_j -> k);
      END IF;
    END LOOP;
  END IF;

  IF TG_TABLE_NAME = 'tenants' THEN
    v_tenant := (ref_j ->> 'id')::uuid;
  ELSE
    v_tenant := (ref_j ->> 'tenant_id')::uuid;
  END IF;

  INSERT INTO audit_log (tenant_id, site_id, user_id, user_name, action, entity,
                         record_id, record_label, old_values, new_values)
  VALUES (
    v_tenant,
    CASE WHEN TG_TABLE_NAME = 'sites' THEN (ref_j ->> 'id')::uuid
         ELSE (ref_j ->> 'site_id')::uuid END,
    cp_current_user_id(),
    coalesce(cp_setting('app.user_name'), 'system'),
    TG_OP,
    TG_TABLE_NAME,
    ref_j ->> 'id',
    cp_audit_label(TG_TABLE_NAME, ref_j),
    CASE WHEN o = '{}'::jsonb THEN NULL ELSE o END,
    CASE WHEN n = '{}'::jsonb THEN NULL ELSE n END
  );
  RETURN coalesce(NEW, OLD);
END $$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['products', 'components', 'files', 'artwork_versions', 'comparisons',
                           'finding_decisions', 'signatures'] LOOP
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION cp_audit_row()', t || '_audit', t);
  END LOOP;
END $$;

-- ---------------------------------------------------------------- row-level security and privileges
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['products', 'components', 'files', 'artwork_versions', 'comparison_counters',
                           'comparisons', 'finding_decisions', 'signatures'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON %I USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id))', t || '_tenant', t);
    EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', t);
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE ON products, components, artwork_versions, comparisons TO comproof_app;
GRANT SELECT, INSERT, UPDATE ON comparison_counters TO comproof_app;
GRANT SELECT, INSERT ON files, finding_decisions, signatures TO comproof_app;
GRANT USAGE ON SEQUENCE finding_decisions_id_seq, signatures_id_seq TO comproof_app;
REVOKE ALL ON FUNCTION cp_claim_comparison() FROM PUBLIC;
REVOKE ALL ON FUNCTION cp_requeue_interrupted() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cp_claim_comparison() TO comproof_app;
GRANT EXECUTE ON FUNCTION cp_requeue_interrupted() TO comproof_app;
