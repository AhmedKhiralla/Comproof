"""End-to-end checks for tenancy isolation, authentication controls and the audit trail."""
import psycopg
import pytest

from conftest import Client, sign_in_first_time


def test_csrf_header_required(client):
    status, body, _ = client.post("/api/auth/login", {"email": "x@y.z", "password": "x"}, csrf=False)
    assert status == 403 and body["error"]["code"] == "csrf"


def test_first_password_change_is_enforced(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "FORCE", "name": "Force Co", "admin": {"email": "first@force.test", "full_name": "First"}})
    assert status == 200
    c = Client(server)
    assert c.login("first@force.test", body["temporary_password"])[0] == 200
    status, body2, _ = c.get("/api/users")
    assert status == 403 and body2["error"]["code"] == "password_change_required"
    status, me, _ = c.get("/api/auth/me")
    assert status == 200 and me["user"]["must_change_password"] is True


def test_password_policy_and_history(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "POLICY", "name": "Policy Co", "admin": {"email": "p@policy.test", "full_name": "P"}})
    temp = body["temporary_password"]
    c = Client(server)
    c.login("p@policy.test", temp)
    status, err, _ = c.post("/api/auth/change-password", {"current_password": temp, "new_password": "short"})
    assert status == 422 and err["error"]["code"] == "weak_password"
    status, err, _ = c.post("/api/auth/change-password", {"current_password": temp, "new_password": temp})
    assert status == 422 and err["error"]["code"] == "reused_password"
    assert c.post("/api/auth/change-password", {"current_password": temp, "new_password": "Second#Pass2026"})[0] == 200
    status, err, _ = c.post("/api/auth/change-password",
                            {"current_password": "Second#Pass2026", "new_password": temp})
    assert status == 422 and err["error"]["code"] == "reused_password"


def test_tenant_isolation(two_companies):
    acme, nile = two_companies["ACME"], two_companies["NILE"]
    _, acme_sites, _ = acme["admin"].get("/api/sites")
    _, nile_sites, _ = nile["admin"].get("/api/sites")
    assert [s["name"] for s in acme_sites["items"]] == ["ACME Cairo plant"]
    assert [s["name"] for s in nile_sites["items"]] == ["NILE Cairo plant"]
    # Same site code is allowed in different companies.
    assert acme_sites["items"][0]["code"] == nile_sites["items"][0]["code"] == "CAI"
    # A company admin cannot touch another company's site even with its id.
    status, _, _ = acme["admin"].patch(f"/api/sites/{nile['site']['id']}", {"name": "Hijacked"})
    assert status == 404
    _, users, _ = acme["admin"].get("/api/users")
    assert {u["email"] for u in users["items"]} == {"admin@acme.test"}
    # Audit trail is scoped too.
    _, audit, _ = acme["admin"].get("/api/audit?page_size=200")
    assert audit["total"] > 0
    assert all(e["tenant_id"] == acme["tenant"]["id"] for e in audit["items"])


def test_rls_enforced_in_database(db_url, two_companies):
    """Even raw SQL as the application role sees only the tenant in context."""
    acme_id = two_companies["ACME"]["tenant"]["id"]
    conn = psycopg.connect(db_url)
    conn.execute("SET LOCAL ROLE comproof_app")
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (acme_id,))
    names = [r[0] for r in conn.execute("SELECT name FROM sites ORDER BY name").fetchall()]
    assert names == ["ACME Cairo plant"]
    conn.rollback()
    conn.execute("SET LOCAL ROLE comproof_app")
    assert conn.execute("SELECT count(*) FROM tenants").fetchone()[0] == 0  # no context, no rows
    conn.rollback()
    conn.close()


def test_audit_trail_is_append_only(db_url, two_companies):
    conn = psycopg.connect(db_url)
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE audit_log SET user_name = 'tampered'")
    conn.rollback()
    with pytest.raises(psycopg.Error):
        conn.execute("DELETE FROM audit_log")
    conn.rollback()
    conn.execute("SET LOCAL ROLE comproof_app")
    conn.execute("SELECT set_config('app.is_system', 'true', true)")
    with pytest.raises(psycopg.Error):
        conn.execute("INSERT INTO audit_log (action, entity) VALUES ('INSERT', 'fake')")
    conn.rollback()
    conn.close()


def test_audit_records_old_and_new_values(two_companies):
    admin = two_companies["ACME"]["admin"]
    site = two_companies["ACME"]["site"]
    assert admin.patch(f"/api/sites/{site['id']}", {"name": "ACME 6th of October plant"})[0] == 200
    _, audit, _ = admin.get(f"/api/audit?entity=sites&record_id={site['id']}")
    update = next(e for e in audit["items"] if e["action"] == "UPDATE")
    assert update["old_values"] == {"name": "ACME Cairo plant"}
    assert update["new_values"] == {"name": "ACME 6th of October plant"}
    assert update["user_name"] == "ACME Admin"
    # Password hashes never enter the audit trail.
    _, users_audit, _ = admin.get("/api/audit?entity=users&page_size=200")
    for e in users_audit["items"]:
        for side in (e["old_values"] or {}, e["new_values"] or {}):
            assert side.get("password_hash") in (None, "[set]", "[changed]", "[redacted]")


def test_user_roles_and_reset(server, two_companies):
    admin = two_companies["ACME"]["admin"]
    site = two_companies["ACME"]["site"]
    status, body, _ = admin.post("/api/users", {
        "email": "planner@acme.test", "full_name": "Mona Planner",
        "roles": [{"site_id": site["id"], "role": "reviewer"}]})
    assert status == 200, body
    planner = sign_in_first_time(server, "planner@acme.test", body["temporary_password"], "Planner#2026xy")
    _, me, _ = planner.get("/api/auth/me")
    assert me["sites"][0]["roles"] == ["reviewer"]
    status, _, _ = planner.get("/api/users")
    assert status == 403  # planners cannot manage users
    # Duplicate email across companies is rejected without revealing the other company.
    status, err, _ = two_companies["NILE"]["admin"].post("/api/users", {
        "email": "planner@acme.test", "full_name": "Copy"})
    assert status == 409


def test_lockout_after_failed_attempts(server, two_companies):
    admin = two_companies["NILE"]["admin"]
    status, body, _ = admin.post("/api/users", {"email": "lock@nile.test", "full_name": "Locked User"})
    temp = body["temporary_password"]
    c = Client(server)
    codes = [c.login("lock@nile.test", "wrong-password")[0] for _ in range(5)]
    assert codes[:4] == [401] * 4 and codes[4] == 423
    # Correct password is refused while locked.
    assert c.login("lock@nile.test", temp)[0] == 423
    uid = body["user"]["id"]
    assert admin.post(f"/api/users/{uid}/unlock")[0] == 200
    assert c.login("lock@nile.test", temp)[0] == 200
    _, audit, _ = admin.get("/api/audit?action=LOCKED")
    assert audit["total"] == 1


def test_disabled_user_session_revoked(server, two_companies):
    admin = two_companies["NILE"]["admin"]
    status, body, _ = admin.post("/api/users", {"email": "gone@nile.test", "full_name": "Leaving User"})
    user = sign_in_first_time(server, "gone@nile.test", body["temporary_password"], "Leaving#2026xy")
    assert user.get("/api/auth/me")[0] == 200
    assert admin.patch(f"/api/users/{body['user']['id']}", {"status": "disabled"})[0] == 200
    assert user.get("/api/auth/me")[0] == 401


def test_last_admin_protected(two_companies):
    admin = two_companies["NILE"]["admin"]
    _, me, _ = admin.get("/api/auth/me")
    status, err, _ = admin.patch(f"/api/users/{me['user']['id']}", {"status": "disabled"})
    assert status == 422


def test_audit_export_logs_event(two_companies):
    admin = two_companies["ACME"]["admin"]
    status, data, headers = admin.get("/api/audit/export?format=csv", raw=True)
    assert status == 200
    text = data.decode("utf-8-sig")
    assert "Exported by,ACME Admin <admin@acme.test>" in text
    status, data, headers = admin.get("/api/audit/export?format=xlsx", raw=True)
    assert status == 200 and data[:2] == b"PK"
    _, audit, _ = admin.get("/api/audit?action=EXPORT")
    assert audit["total"] == 2


def test_settings_roundtrip(two_companies):
    admin = two_companies["ACME"]["admin"]
    _, s, _ = admin.get("/api/settings")
    assert s["features"]["four_eyes"] is True
    status, s2, _ = admin.put("/api/settings/features", {"features": {"ai_reading": True}})
    assert status == 200 and s2["features"]["ai_reading"] is True
    status, s3, _ = admin.put("/api/settings/terminology",
                              {"terminology": {"supplier": {"en": "Printer", "ar": "المطبعة"}}})
    assert status == 200 and s3["terminology"]["supplier"] == {"en": "Printer", "ar": "المطبعة"}
    assert [p["name"] for p in s3["ai_providers"]] == ["qwen"]
    status, s4, _ = admin.put("/api/settings/engine", {"provider": "groq", "exclude_phrases": []})
    assert status == 422  # not configured on this server
    status, s4, _ = admin.put("/api/settings/engine", {"provider": "qwen", "exclude_phrases": [" EDA stamp ", ""]})
    assert status == 200 and s4["engine"]["exclude_phrases"] == ["EDA stamp"]
    bad = dict(s3["security"], session_timeout_minutes=1)
    status, err, _ = admin.put("/api/settings/security", bad)
    assert status == 422 and "session_timeout_minutes" in err["error"]["fields"]


def test_platform_admin_cannot_use_company_endpoints(platform):
    status, body, _ = platform.get("/api/users")
    assert status == 403


def test_logout_revokes_session(server, two_companies):
    admin = two_companies["ACME"]["admin"]
    status, body, _ = admin.post("/api/users", {"email": "out@acme.test", "full_name": "Out User"})
    c = sign_in_first_time(server, "out@acme.test", body["temporary_password"], "Outgoing#2026x")
    assert c.post("/api/auth/logout")[0] == 200
    assert c.get("/api/auth/me")[0] == 401


def test_audit_trail_hash_chain(two_companies):
    admin = two_companies["ACME"]["admin"]
    status, body, _ = admin.post("/api/audit/verify")
    assert status == 200 and body["intact"] is True and body["checked"] > 3


def test_audit_chain_with_concurrent_writers(db_url, two_companies):
    """Entries written at the same moment by the engine and by users are chained in id order."""
    import threading, uuid as _uuid
    tenant = str(_uuid.uuid4())

    def write(n):
        conn = psycopg.connect(db_url, autocommit=True)
        for i in range(n):
            conn.execute("SELECT cp_audit_event('RUN_STARTED', 'comparisons', %s, 'x', '{}'::jsonb, %s, NULL, 'w')",
                         (str(i), tenant))
        conn.close()
    threads = [threading.Thread(target=write, args=(40,)) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    conn = psycopg.connect(db_url, autocommit=True)
    rows = conn.execute("SELECT prev_hash, row_hash FROM audit_log WHERE tenant_id = %s ORDER BY id", (tenant,)).fetchall()
    assert len(rows) == 160 and rows[0][0] is None
    assert all(rows[i][0] == rows[i - 1][1] for i in range(1, len(rows)))
    conn.execute("SELECT set_config('app.is_system', 'true', false)")
    assert conn.execute("SELECT checked, first_bad_id FROM cp_audit_verify(%s)", (tenant,)).fetchone() == (160, None)
    # a superuser who removes an entry in the middle of the chain is found
    conn.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update")
    victim = conn.execute("SELECT id FROM audit_log WHERE tenant_id = %s ORDER BY id OFFSET 80 LIMIT 1", (tenant,)).fetchone()[0]
    conn.execute("DELETE FROM audit_log WHERE id = %s", (victim,))
    conn.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update")
    checked, bad = conn.execute("SELECT checked, first_bad_id FROM cp_audit_verify(%s)", (tenant,)).fetchone()
    assert checked == 159 and bad is not None and bad > victim
    conn.close()
