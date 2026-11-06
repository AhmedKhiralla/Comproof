-- Comproof: foundation schema (shared design with Complanning, by Comp11 Labs)
-- Tenancy, users, roles, sessions, and the database-enforced audit trail.
--
-- Security model
--   * The application connects as the database owner but runs every request
--     inside "SET LOCAL ROLE comproof_app". comproof_app has no BYPASSRLS, so row-level
--     security policies always apply to application queries.
--   * Context is passed per transaction with set_config(..., true):
--       app.tenant_id    tenant of the signed-in user
--       app.user_id      signed-in user (used by the audit trail)
--       app.user_name    display name stored with each audit entry
--       app.is_platform  'true' for platform administrators
--       app.is_system    'true' only inside authentication code paths
--   * The audit trail is written by triggers (SECURITY DEFINER). comproof_app can
--     only SELECT it, and a guard trigger rejects any UPDATE, DELETE or TRUNCATE.

-- ---------------------------------------------------------------- roles
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'comproof_app') THEN
    CREATE ROLE comproof_app NOLOGIN NOBYPASSRLS;
  END IF;
END $$;

DO $$
BEGIN
  EXECUTE format('GRANT comproof_app TO %I', current_user);
EXCEPTION WHEN OTHERS THEN
  -- Superusers can SET ROLE without membership; ignore if the grant is not needed.
  NULL;
END $$;

-- ---------------------------------------------------------------- helpers
CREATE OR REPLACE FUNCTION cp_setting(name text) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting(name, true), '')
$$;

CREATE OR REPLACE FUNCTION cp_current_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT cp_setting('app.user_id')::uuid
$$;

-- True when the current transaction may see rows of the given tenant.
-- Platform-wide access (is_platform) applies only to foundation tables;
-- business tables added in later phases use cp_tenant_only().
CREATE OR REPLACE FUNCTION cp_can_access(row_tenant uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT coalesce(cp_setting('app.is_system') = 'true', false)
      OR coalesce(cp_setting('app.is_platform') = 'true', false)
      OR (row_tenant IS NOT NULL AND row_tenant = cp_setting('app.tenant_id')::uuid)
$$;

CREATE OR REPLACE FUNCTION cp_tenant_only(row_tenant uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT row_tenant IS NOT NULL AND row_tenant = cp_setting('app.tenant_id')::uuid
$$;

-- created_by / updated_by / updated_at stamping
CREATE OR REPLACE FUNCTION cp_stamp() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    NEW.created_at := now();
    NEW.created_by := cp_current_user_id();
  ELSE
    NEW.created_at := OLD.created_at;
    NEW.created_by := OLD.created_by;
  END IF;
  NEW.updated_at := now();
  NEW.updated_by := cp_current_user_id();
  RETURN NEW;
END $$;

-- ---------------------------------------------------------------- tables
CREATE TABLE tenants (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code             text NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9][A-Z0-9_-]{1,19}$'),
  name             text NOT NULL CHECK (length(trim(name)) > 0),
  country          char(2) NOT NULL DEFAULT 'EG',
  timezone         text NOT NULL DEFAULT 'Africa/Cairo',
  default_language text NOT NULL DEFAULT 'en' CHECK (default_language IN ('en', 'ar')),
  status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
  features         jsonb NOT NULL DEFAULT '{}'::jsonb,
  terminology      jsonb NOT NULL DEFAULT '{}'::jsonb,
  security         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  created_by       uuid,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  updated_by       uuid
);

CREATE TABLE sites (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  code        text NOT NULL CHECK (code ~ '^[A-Z0-9][A-Z0-9_-]{0,19}$'),
  name        text NOT NULL CHECK (length(trim(name)) > 0),
  country     char(2) NOT NULL DEFAULT 'EG',
  timezone    text NOT NULL DEFAULT 'Africa/Cairo',
  address     text,
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  created_by  uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  updated_by  uuid,
  UNIQUE (tenant_id, code)
);

CREATE TABLE users (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid REFERENCES tenants(id),
  email                text NOT NULL CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  full_name            text NOT NULL CHECK (length(trim(full_name)) > 0),
  password_hash        text NOT NULL,
  is_platform_admin    boolean NOT NULL DEFAULT false,
  is_tenant_admin      boolean NOT NULL DEFAULT false,
  status               text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  language             text CHECK (language IN ('en', 'ar')),
  theme                text NOT NULL DEFAULT 'system' CHECK (theme IN ('light', 'dark', 'system')),
  guide                jsonb NOT NULL DEFAULT '{}'::jsonb,
  failed_attempts      integer NOT NULL DEFAULT 0,
  locked_until         timestamptz,
  password_changed_at  timestamptz NOT NULL DEFAULT now(),
  must_change_password boolean NOT NULL DEFAULT true,
  last_login_at        timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  created_by           uuid,
  updated_at           timestamptz NOT NULL DEFAULT now(),
  updated_by           uuid,
  CHECK (is_platform_admin = (tenant_id IS NULL)),
  CHECK (NOT (is_platform_admin AND is_tenant_admin))
);
CREATE UNIQUE INDEX users_email_key ON users (lower(email));
CREATE INDEX users_tenant_idx ON users (tenant_id);

CREATE TABLE password_history (
  id            bigserial PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES users(id),
  tenant_id     uuid REFERENCES tenants(id),
  password_hash text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX password_history_user_idx ON password_history (user_id, created_at DESC);

CREATE TABLE user_site_roles (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id),
  user_id     uuid NOT NULL REFERENCES users(id),
  site_id     uuid NOT NULL REFERENCES sites(id),
  role        text NOT NULL CHECK (role IN ('artwork_editor', 'reviewer', 'approver', 'viewer')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  created_by  uuid,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  updated_by  uuid,
  UNIQUE (user_id, site_id, role)
);

CREATE TABLE sessions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash    text NOT NULL UNIQUE,
  user_id       uuid NOT NULL REFERENCES users(id),
  tenant_id     uuid REFERENCES tenants(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  revoke_reason text,
  ip            text,
  user_agent    text
);
CREATE INDEX sessions_user_idx ON sessions (user_id);

CREATE TABLE audit_log (
  id           bigserial PRIMARY KEY,
  occurred_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
  tenant_id    uuid,
  site_id      uuid,
  user_id      uuid,
  user_name    text,
  action       text NOT NULL,
  entity       text NOT NULL,
  record_id    text,
  record_label text,
  old_values   jsonb,
  new_values   jsonb,
  details      jsonb
);
CREATE INDEX audit_log_tenant_time_idx ON audit_log (tenant_id, occurred_at DESC);
ALTER TABLE audit_log ADD COLUMN prev_hash text, ADD COLUMN row_hash text;
CREATE INDEX audit_log_chain_idx ON audit_log (coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), id DESC);
CREATE INDEX audit_log_entity_idx ON audit_log (entity, record_id);

-- ---------------------------------------------------------------- stamping triggers
CREATE TRIGGER tenants_stamp BEFORE INSERT OR UPDATE ON tenants FOR EACH ROW EXECUTE FUNCTION cp_stamp();
CREATE TRIGGER sites_stamp BEFORE INSERT OR UPDATE ON sites FOR EACH ROW EXECUTE FUNCTION cp_stamp();
CREATE TRIGGER users_stamp BEFORE INSERT OR UPDATE ON users FOR EACH ROW EXECUTE FUNCTION cp_stamp();
CREATE TRIGGER user_site_roles_stamp BEFORE INSERT OR UPDATE ON user_site_roles FOR EACH ROW EXECUTE FUNCTION cp_stamp();

-- ---------------------------------------------------------------- audit trail
-- Columns that change on routine activity and are not business data.
CREATE OR REPLACE FUNCTION cp_audit_ignored(col text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT col IN ('created_at', 'created_by', 'updated_at', 'updated_by',
                 'last_login_at', 'failed_attempts', 'locked_until', 'guide', 'progress')
$$;

-- Columns whose values must never be copied into the audit trail.
CREATE OR REPLACE FUNCTION cp_audit_redacted(col text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT col IN ('password_hash')
$$;

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
      RETURN NEW;  -- nothing auditable changed
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
    coalesce(ref_j ->> 'code', ref_j ->> 'email', ref_j ->> 'name', ref_j ->> 'role'),
    CASE WHEN o = '{}'::jsonb THEN NULL ELSE o END,
    CASE WHEN n = '{}'::jsonb THEN NULL ELSE n END
  );
  RETURN coalesce(NEW, OLD);
END $$;

CREATE TRIGGER tenants_audit AFTER INSERT OR UPDATE OR DELETE ON tenants FOR EACH ROW EXECUTE FUNCTION cp_audit_row();
CREATE TRIGGER sites_audit AFTER INSERT OR UPDATE OR DELETE ON sites FOR EACH ROW EXECUTE FUNCTION cp_audit_row();
CREATE TRIGGER users_audit AFTER INSERT OR UPDATE OR DELETE ON users FOR EACH ROW EXECUTE FUNCTION cp_audit_row();
CREATE TRIGGER user_site_roles_audit AFTER INSERT OR UPDATE OR DELETE ON user_site_roles FOR EACH ROW EXECUTE FUNCTION cp_audit_row();

-- Events that are not row changes: sign-in, sign-out, lockout, exports...
CREATE OR REPLACE FUNCTION cp_audit_event(
  p_action text, p_entity text, p_record_id text, p_record_label text,
  p_details jsonb, p_tenant uuid, p_user uuid, p_user_name text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF p_action NOT IN ('LOGIN', 'LOGIN_FAILED', 'LOGOUT', 'LOCKED', 'UNLOCKED',
                      'SESSION_TIMEOUT', 'PASSWORD_CHANGED', 'PASSWORD_RESET',
                      'EXPORT', 'IMPORT', 'BOOTSTRAP', 'SIGNED', 'SIGNATURE_FAILED',
                      'FILE_UPLOADED', 'FILE_DOWNLOADED', 'RUN_STARTED', 'RUN_FINISHED', 'RUN_FAILED',
                      'INTEGRITY_CHECK') THEN
    RAISE EXCEPTION 'Unknown audit event: %', p_action;
  END IF;
  INSERT INTO audit_log (tenant_id, user_id, user_name, action, entity,
                         record_id, record_label, details)
  VALUES (p_tenant, p_user, coalesce(p_user_name, 'system'), p_action, p_entity,
          p_record_id, p_record_label, p_details);
END $$;

-- Emails are unique across all companies, but RLS hides other companies' users.
-- This answers only "is this email taken?" without exposing any row.
CREATE OR REPLACE FUNCTION cp_email_taken(p_email text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM users WHERE lower(email) = lower(p_email))
$$;

-- Append-only guard
CREATE OR REPLACE FUNCTION cp_audit_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'The audit trail is append-only; % is not allowed', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION cp_audit_immutable();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION cp_audit_immutable();


-- ---------------------------------------------------------------- tamper evidence
-- Every audit entry carries the SHA-256 of the previous entry of the same company and of its own content.
-- Even a database superuser who edits or deletes an entry breaks the chain, and cp_audit_verify() finds it.
CREATE OR REPLACE FUNCTION cp_audit_hash(prev text, j jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(sha256(convert_to(coalesce(prev, 'GENESIS') || '|' || j::text, 'UTF8')), 'hex')
$$;

CREATE OR REPLACE FUNCTION cp_audit_payload(r audit_log) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
  SELECT (to_jsonb(r) - 'prev_hash' - 'row_hash' - 'occurred_at')
         || jsonb_build_object('t', to_char(r.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'))
$$;

CREATE OR REPLACE FUNCTION cp_audit_chain() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  k uuid := coalesce(NEW.tenant_id, '00000000-0000-0000-0000-000000000000'::uuid);
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(k::text, 727012));
  SELECT row_hash INTO NEW.prev_hash FROM audit_log
   WHERE coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid) = k
   ORDER BY id DESC LIMIT 1;
  NEW.row_hash := cp_audit_hash(NEW.prev_hash, cp_audit_payload(NEW));
  RETURN NEW;
END $$;

CREATE TRIGGER audit_log_chain BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION cp_audit_chain();

-- Recomputes the chain of the caller's company (or of the platform). Returns the first broken entry, or NULL.
CREATE OR REPLACE FUNCTION cp_audit_verify(p_tenant uuid) RETURNS TABLE (checked bigint, first_bad_id bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  r audit_log;
  prev text := NULL;
  n bigint := 0;
BEGIN
  IF NOT cp_can_access(p_tenant) AND p_tenant IS NOT NULL THEN
    RAISE EXCEPTION 'No access' USING ERRCODE = 'insufficient_privilege';
  END IF;
  FOR r IN SELECT * FROM audit_log
            WHERE coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)
                = coalesce(p_tenant, '00000000-0000-0000-0000-000000000000'::uuid)
            ORDER BY id LOOP
    n := n + 1;
    IF r.prev_hash IS DISTINCT FROM prev OR r.row_hash IS DISTINCT FROM cp_audit_hash(prev, cp_audit_payload(r)) THEN
      checked := n; first_bad_id := r.id; RETURN NEXT; RETURN;
    END IF;
    prev := r.row_hash;
  END LOOP;
  checked := n; first_bad_id := NULL; RETURN NEXT;
END $$;

-- ---------------------------------------------------------------- row-level security
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_site_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenants_access ON tenants USING (cp_can_access(id)) WITH CHECK (cp_can_access(id));
CREATE POLICY sites_access ON sites USING (cp_can_access(tenant_id)) WITH CHECK (cp_can_access(tenant_id));
CREATE POLICY users_access ON users USING (cp_can_access(tenant_id)) WITH CHECK (cp_can_access(tenant_id));
CREATE POLICY password_history_access ON password_history USING (cp_can_access(tenant_id)) WITH CHECK (cp_can_access(tenant_id));
CREATE POLICY user_site_roles_access ON user_site_roles USING (cp_can_access(tenant_id)) WITH CHECK (cp_can_access(tenant_id));
CREATE POLICY sessions_access ON sessions USING (cp_can_access(tenant_id)) WITH CHECK (cp_can_access(tenant_id));
CREATE POLICY audit_log_read ON audit_log FOR SELECT USING (cp_can_access(tenant_id));

-- ---------------------------------------------------------------- privileges
REVOKE ALL ON tenants, sites, users, password_history, user_site_roles, sessions, audit_log FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON tenants, sites, users TO comproof_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_site_roles TO comproof_app;
GRANT SELECT, INSERT, DELETE ON password_history TO comproof_app;
GRANT SELECT, INSERT, UPDATE ON sessions TO comproof_app;
GRANT SELECT ON audit_log TO comproof_app;
GRANT USAGE ON SEQUENCE password_history_id_seq TO comproof_app;
REVOKE ALL ON FUNCTION cp_audit_event(text, text, text, text, jsonb, uuid, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION cp_email_taken(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION cp_audit_verify(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cp_audit_verify(uuid) TO comproof_app;
GRANT EXECUTE ON FUNCTION cp_audit_event(text, text, text, text, jsonb, uuid, uuid, text) TO comproof_app;
GRANT EXECUTE ON FUNCTION cp_email_taken(text) TO comproof_app;
