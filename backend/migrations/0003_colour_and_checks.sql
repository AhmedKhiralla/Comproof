-- Comproof 1.1: shade standards (Standard / Light / Dark), colour, barcode, graphics and print checks.

ALTER TABLE products ADD COLUMN gtin text CHECK (gtin IS NULL OR gtin ~ '^[0-9]{8,14}$');

-- A shade set is the approved colour reference for one packaging component: three scans (or spectrophotometer
-- files) labelled Standard, Light and Dark, and the measurement Comproof made of them. It becomes the reference
-- only through an electronic signature on the measurement's SHA-256.
CREATE TABLE shade_sets (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id),
  component_id       uuid NOT NULL REFERENCES components(id),
  version            text NOT NULL CHECK (version ~ '^[A-Za-z0-9._-]{1,20}$'),
  source             text NOT NULL CHECK (source IN ('scan_target', 'scan', 'spectro', 'photo')),
  standard_file_id   uuid NOT NULL REFERENCES files(id),
  light_file_id      uuid NOT NULL REFERENCES files(id),
  dark_file_id       uuid NOT NULL REFERENCES files(id),
  measurement        jsonb NOT NULL,
  measurement_sha256 text NOT NULL CHECK (measurement_sha256 ~ '^[0-9a-f]{64}$'),
  verification       text NOT NULL CHECK (verification IN ('pass', 'warn', 'fail')),
  status             text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'effective', 'superseded', 'withdrawn')),
  supplier           text,
  reference_no       text,
  notes              text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  created_by         uuid,
  updated_at         timestamptz NOT NULL DEFAULT now(),
  updated_by         uuid,
  UNIQUE (component_id, version),
  CHECK (standard_file_id <> light_file_id AND standard_file_id <> dark_file_id AND light_file_id <> dark_file_id)
);
CREATE UNIQUE INDEX shade_one_effective ON shade_sets (component_id) WHERE status = 'effective';

ALTER TABLE comparisons ADD COLUMN shade_set_id uuid REFERENCES shade_sets(id);

ALTER TABLE signatures DROP CONSTRAINT signatures_entity_check;
ALTER TABLE signatures ADD CONSTRAINT signatures_entity_check
  CHECK (entity IN ('comparison', 'artwork_version', 'shade_set'));

CREATE TRIGGER shade_sets_stamp BEFORE INSERT OR UPDATE ON shade_sets FOR EACH ROW EXECUTE FUNCTION cp_stamp();
CREATE TRIGGER shade_sets_no_delete BEFORE DELETE ON shade_sets FOR EACH ROW EXECUTE FUNCTION cp_append_only();

CREATE OR REPLACE FUNCTION cp_shade_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('superseded', 'withdrawn') THEN
    RAISE EXCEPTION 'Shade set % is closed', OLD.version USING ERRCODE = 'check_violation';
  END IF;
  -- the measured reference never changes; a new measurement is a new version
  IF NEW.measurement IS DISTINCT FROM OLD.measurement OR NEW.measurement_sha256 IS DISTINCT FROM OLD.measurement_sha256
     OR NEW.standard_file_id IS DISTINCT FROM OLD.standard_file_id OR NEW.light_file_id IS DISTINCT FROM OLD.light_file_id
     OR NEW.dark_file_id IS DISTINCT FROM OLD.dark_file_id OR NEW.source IS DISTINCT FROM OLD.source
     OR NEW.verification IS DISTINCT FROM OLD.verification OR NEW.component_id IS DISTINCT FROM OLD.component_id
     OR NEW.version IS DISTINCT FROM OLD.version THEN
    RAISE EXCEPTION 'A shade set measurement cannot be changed; register a new version' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    IF NOT ((OLD.status = 'draft' AND NEW.status IN ('effective', 'withdrawn'))
         OR (OLD.status = 'effective' AND NEW.status IN ('superseded', 'withdrawn'))) THEN
      RAISE EXCEPTION 'A shade set cannot go from % to %', OLD.status, NEW.status USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'effective' AND NEW.verification = 'fail' THEN
      RAISE EXCEPTION 'Shade set % failed verification (Light / Standard / Dark order) and cannot be approved', NEW.version
        USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'effective' AND NOT EXISTS (
        SELECT 1 FROM signatures s WHERE s.entity = 'shade_set' AND s.record_id = NEW.id
           AND s.meaning = 'approved_master' AND s.record_hash = NEW.measurement_sha256) THEN
      RAISE EXCEPTION 'An electronic signature is required to make shade set % effective', NEW.version
        USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'withdrawn' AND NOT EXISTS (
        SELECT 1 FROM signatures s WHERE s.entity = 'shade_set' AND s.record_id = NEW.id AND s.meaning = 'withdrawn') THEN
      RAISE EXCEPTION 'An electronic signature is required to withdraw shade set %', NEW.version
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER shade_sets_guard BEFORE UPDATE ON shade_sets FOR EACH ROW EXECUTE FUNCTION cp_shade_guard();

-- comparisons: the shade set is fixed with the files once a run exists
CREATE OR REPLACE FUNCTION cp_comparison_shade_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.shade_set_id IS DISTINCT FROM OLD.shade_set_id THEN
    RAISE EXCEPTION 'The shade set of a comparison cannot be changed' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER comparisons_shade_guard BEFORE UPDATE ON comparisons FOR EACH ROW EXECUTE FUNCTION cp_comparison_shade_guard();

CREATE OR REPLACE FUNCTION cp_audit_label(tbl text, j jsonb) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT CASE tbl
    WHEN 'comparisons' THEN j ->> 'number'
    WHEN 'artwork_versions' THEN (SELECT c.code FROM components c WHERE c.id = (j ->> 'component_id')::uuid) || ' v' || (j ->> 'version')
    WHEN 'shade_sets' THEN (SELECT c.code FROM components c WHERE c.id = (j ->> 'component_id')::uuid) || ' shades ' || (j ->> 'version')
    WHEN 'files' THEN j ->> 'filename'
    WHEN 'finding_decisions' THEN (SELECT c.number FROM comparisons c WHERE c.id = (j ->> 'comparison_id')::uuid) || ' ' || (j ->> 'finding_id')
    WHEN 'signatures' THEN (j ->> 'record_label') || ' · ' || (j ->> 'meaning')
    ELSE coalesce(j ->> 'code', j ->> 'email', j ->> 'name', j ->> 'role') END
$$;

CREATE TRIGGER shade_sets_audit AFTER INSERT OR UPDATE OR DELETE ON shade_sets FOR EACH ROW EXECUTE FUNCTION cp_audit_row();

ALTER TABLE shade_sets ENABLE ROW LEVEL SECURITY;
CREATE POLICY shade_sets_tenant ON shade_sets USING (cp_tenant_only(tenant_id)) WITH CHECK (cp_tenant_only(tenant_id));
REVOKE ALL ON shade_sets FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON shade_sets TO comproof_app;

-- The measurement body (ink sample points, L*a*b* values) can be large; the audit trail records its SHA-256,
-- and the row itself can never change.
CREATE OR REPLACE FUNCTION cp_audit_ignored(col text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT col IN ('created_at', 'created_by', 'updated_at', 'updated_by',
                 'last_login_at', 'failed_attempts', 'locked_until', 'guide', 'progress', 'measurement')
$$;

-- spectrophotometer measurement files (CxF3 / CGATS) can be uploaded like any other file
ALTER TABLE files DROP CONSTRAINT files_doc_kind_check;
ALTER TABLE files ADD CONSTRAINT files_doc_kind_check
  CHECK (doc_kind IN ('pdf-vector', 'pdf-scan', 'image', 'docx', 'spectro'));
