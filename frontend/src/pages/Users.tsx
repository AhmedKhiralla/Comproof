import { useMemo, useState } from "react";
import { LuBan, LuEllipsis, LuKeyRound, LuLockOpen, LuPencil, LuPower, LuSearch, LuUserPlus, LuUsers } from "react-icons/lu";
import {
  Badge, Button, Confirm, Empty, LoadError, LoadingRows, Menu, MenuItem, Notice, PageHead, SecretReveal, Sheet,
  Switch, TextField, errorText, fieldErrors, useLoad, useToast,
} from "../components/ui";
import { get, patch, post, put } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSession } from "../lib/session";
import type { SiteRow } from "./Sites";

const ROLES = ["artwork_editor", "reviewer", "approver", "viewer"] as const;
type Role = (typeof ROLES)[number];

interface UserRow {
  id: string; email: string; full_name: string; is_tenant_admin: boolean; status: "active" | "disabled";
  must_change_password: boolean; last_login_at: string | null; is_locked: boolean;
  roles: { site_id: string; role: Role }[];
}
type Secret = { name: string; email: string; secret: string };

function UserSheet({ user, sites, onClose, onSaved, onSecret }: {
  user: UserRow | null; sites: SiteRow[]; onClose: () => void; onSaved: () => void; onSecret: (s: Secret) => void;
}) {
  const { t, tx } = useI18n();
  const { me } = useSession();
  const toast = useToast();
  const [name, setName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [admin, setAdmin] = useState(user?.is_tenant_admin ?? false);
  const [roles, setRoles] = useState<Set<string>>(new Set((user?.roles ?? []).map((r) => `${r.site_id}|${r.role}`)));
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const isSelf = user?.id === me?.user.id;
  const active = sites.filter((s) => s.active);
  const toggle = (key: string) => setRoles((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const roleList = () => Array.from(roles).map((k) => { const [site_id, role] = k.split("|"); return { site_id, role }; });

  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      if (user) {
        await patch(`/api/users/${user.id}`, { full_name: name, is_tenant_admin: admin });
        await put(`/api/users/${user.id}/roles`, { roles: roleList() });
        toast(t("users.savedToast")); onSaved(); onClose();
      } else {
        const res = await post("/api/users", { email, full_name: name, is_tenant_admin: admin, roles: roleList() });
        onSaved(); onClose();
        onSecret({ name: res.user.full_name, email: res.user.email, secret: res.temporary_password });
      }
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };

  return (
    <Sheet title={user ? t("users.form.edit") : t("users.form.new")} lead={user?.email} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{user ? t("common.save") : t("common.create")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <TextField label={t("users.form.fullName")} value={name} onChange={setName} error={errs.full_name} required />
      <TextField label={t("common.email")} type="email" dir="ltr" value={email} onChange={setEmail} error={errs.email}
        disabled={!!user} hint={user ? t("users.form.emailLocked") : undefined} required />
      <div className="feature" style={{ padding: "4px 0", border: 0 }}>
        <div className="text"><strong>{t("users.form.isAdmin")}</strong><span>{t("users.form.isAdminHint")}</span></div>
        <Switch label={t("users.form.isAdmin")} checked={admin} onChange={setAdmin} disabled={isSelf} />
      </div>
      <div className="field">
        <span className="field-label">{t("users.form.siteRoles")}</span>
        <span className="hint">{t("users.form.siteRolesHint")}</span>
        {active.length === 0 ? <Notice>{t("users.form.noSites")}</Notice> : (
          <div className="panel" style={{ overflowX: "auto" }}>
            <table className="matrix">
              <thead><tr><th>{t("shell.site")}</th>{ROLES.map((r) => <th key={r}>{tx(`role.${r}`, r)}</th>)}</tr></thead>
              <tbody>
                {active.map((s) => (
                  <tr key={s.id}>
                    <td><strong style={{ fontWeight: 500 }}>{s.name}</strong> <span className="subtle small mono-id">{s.code}</span></td>
                    {ROLES.map((r) => {
                      const key = `${s.id}|${r}`;
                      return <td key={r}><input type="checkbox" className="check" style={{ width: 16, height: 16, accentColor: "var(--brand-solid)" }}
                        aria-label={`${s.name}: ${tx(`role.${r}`, r)}`} checked={roles.has(key)} onChange={() => toggle(key)} /></td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {errs.roles && <div className="error">{errs.roles}</div>}
      </div>
    </Sheet>
  );
}

export function Users() {
  const { t, tx, dateTime, lang } = useI18n();
  const { me } = useSession();
  const toast = useToast();
  const list = (xs: string[]) => xs.join(lang === "ar" ? "، " : ", ");
  const users = useLoad(() => get<{ items: UserRow[] }>("/api/users"));
  const sites = useLoad(() => get<{ items: SiteRow[] }>("/api/sites"));
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<UserRow | "new" | null>(null);
  const [confirm, setConfirm] = useState<{ kind: "reset" | "disable"; user: UserRow } | null>(null);
  const [secret, setSecret] = useState<Secret | null>(null);
  const siteName = useMemo(() => new Map((sites.data?.items ?? []).map((s) => [s.id, s.code])), [sites.data]);
  const items = (users.data?.items ?? []).filter((u) => {
    const q = query.trim().toLowerCase();
    return !q || u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q);
  });

  const roleSummary = (u: UserRow) => {
    if (u.is_tenant_admin) return <Badge tone="brand">{t("user.companyAdmin")}</Badge>;
    if (!u.roles.length) return <span className="subtle small">{t("users.noRoles")}</span>;
    const bySite = new Map<string, string[]>();
    u.roles.forEach((r) => bySite.set(r.site_id, [...(bySite.get(r.site_id) ?? []), tx(`role.${r.role}`, r.role)]));
    return <div className="small">{Array.from(bySite).map(([sid, rs]) => (
      <div key={sid}><span className="mono-id muted">{siteName.get(sid) ?? "—"}</span> · {list(rs)}</div>
    ))}</div>;
  };

  const status = (u: UserRow) => {
    if (u.status === "disabled") return <Badge>{t("users.disabled")}</Badge>;
    if (u.is_locked) return <Badge tone="danger" dot>{t("users.locked")}</Badge>;
    if (u.must_change_password) return <Badge tone="warn" dot>{t("users.mustChange")}</Badge>;
    return <Badge tone="ok" dot>{t("common.active")}</Badge>;
  };

  return (
    <>
      <PageHead title={t("users.title")} lead={t("users.lead")}
        actions={<Button variant="primary" icon={<LuUserPlus />} onClick={() => setEditing("new")}>{t("users.new")}</Button>} />
      <div className="panel">
        <div className="toolbar">
          <div className="search"><LuSearch aria-hidden />
            <input className="input" type="search" placeholder={t("common.search")} aria-label={t("common.search")} value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
        {users.error ? <LoadError error={users.error} onRetry={users.reload} /> : !users.loading && (users.data?.items.length ?? 0) <= 1 && !query ? (
          <>
            {users.data && users.data.items.length === 1 && renderTable()}
            <Empty icon={<LuUsers />} title={t("users.empty")} body={t("users.emptyBody")}
              action={<Button variant="primary" icon={<LuUserPlus />} onClick={() => setEditing("new")}>{t("users.new")}</Button>} />
          </>
        ) : renderTable()}
      </div>
      {editing && <UserSheet user={editing === "new" ? null : editing} sites={sites.data?.items ?? []} onClose={() => setEditing(null)}
        onSaved={users.reload} onSecret={setSecret} />}
      {confirm?.kind === "reset" && <Confirm title={t("users.resetConfirm", { name: confirm.user.full_name })} body={t("users.resetBody")}
        confirmLabel={t("users.resetPassword")} onClose={() => setConfirm(null)}
        onConfirm={async () => {
          const res = await post(`/api/users/${confirm.user.id}/reset-password`);
          users.reload();
          setSecret({ name: confirm.user.full_name, email: confirm.user.email, secret: res.temporary_password });
        }} />}
      {confirm?.kind === "disable" && <Confirm danger title={t("users.disableConfirm", { name: confirm.user.full_name })} body={t("users.disableBody")}
        confirmLabel={t("users.disable")} onClose={() => setConfirm(null)}
        onConfirm={async () => { await patch(`/api/users/${confirm.user.id}`, { status: "disabled" }); toast(t("users.savedToast")); users.reload(); }} />}
      {secret && <SecretReveal name={secret.name} email={secret.email} secret={secret.secret} onClose={() => setSecret(null)} />}
    </>
  );

  function renderTable() {
    return (
      <div className="table-wrap">
        <table className="table">
          <thead><tr>
            <th>{t("common.name")}</th><th>{t("users.roles")}</th><th>{t("common.status")}</th><th>{t("users.lastSignIn")}</th>
            <th><span className="visually-hidden">{t("common.actions")}</span></th>
          </tr></thead>
          {users.loading && !users.data ? <LoadingRows cols={5} /> : (
            <tbody>
              {items.map((u) => (
                <tr key={u.id} className={`clickable ${u.status === "disabled" ? "inactive" : ""}`} onClick={() => setEditing(u)}>
                  <td><div className="cell-main">{u.full_name}</div>
                    <div className="cell-sub">{u.email}</div></td>
                  <td>{roleSummary(u)}</td>
                  <td>{status(u)}</td>
                  <td className="small muted">{u.last_login_at ? dateTime(u.last_login_at, me?.tenant?.timezone) : t("common.never")}</td>
                  <td className="actions" onClick={(e) => e.stopPropagation()}>
                    <Menu trigger={(p) => <Button variant="ghost" iconOnly size="sm" aria-label={t("common.actions")} icon={<LuEllipsis />} {...p} />}>
                      {(close) => <>
                        <MenuItem icon={<LuPencil />} onClick={() => { close(); setEditing(u); }}>{t("common.edit")}</MenuItem>
                        <MenuItem icon={<LuKeyRound />} onClick={() => { close(); setConfirm({ kind: "reset", user: u }); }}>{t("users.resetPassword")}</MenuItem>
                        {u.is_locked && <MenuItem icon={<LuLockOpen />} onClick={async () => { close(); await post(`/api/users/${u.id}/unlock`); toast(t("users.unlockedToast")); users.reload(); }}>{t("users.unlock")}</MenuItem>}
                        {u.id !== me?.user.id && (u.status === "active"
                          ? <MenuItem danger icon={<LuBan />} onClick={() => { close(); setConfirm({ kind: "disable", user: u }); }}>{t("users.disable")}</MenuItem>
                          : <MenuItem icon={<LuPower />} onClick={async () => { close(); await patch(`/api/users/${u.id}`, { status: "active" }); toast(t("users.savedToast")); users.reload(); }}>{t("users.enable")}</MenuItem>)}
                      </>}
                    </Menu>
                  </td>
                </tr>
              ))}
            </tbody>
          )}
        </table>
      </div>
    );
  }
}
