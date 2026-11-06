import { useEffect, useMemo, useState } from "react";
import { LuBan, LuBuilding2, LuEllipsis, LuKeyRound, LuPencil, LuPlus, LuPower, LuUserPlus } from "react-icons/lu";
import {
  Badge, Button, Confirm, Empty, LoadError, LoadingRows, Menu, MenuItem, Notice, PageHead, SecretReveal, SelectField,
  Sheet, TextField, errorText, fieldErrors, useLoad, useToast,
} from "../components/ui";
import { get, patch, post } from "../lib/api";
import { COUNTRIES, timeZones } from "../lib/geo";
import { useI18n } from "../lib/i18n";

interface Tenant {
  id: string; code: string; name: string; country: string; timezone: string; default_language: "en" | "ar";
  status: "active" | "suspended"; created_at: string; site_count: number; user_count: number;
}
interface Admin { id: string; email: string; full_name: string; status: string; must_change_password: boolean; last_login_at: string | null; }
type Secret = { name: string; email: string; secret: string };

function useRegionOptions() {
  const { countryName } = useI18n();
  const countries = useMemo(() => COUNTRIES.map((c) => ({ value: c, label: countryName(c) }))
    .sort((a, b) => a.label.localeCompare(b.label)), [countryName]);
  const zones = useMemo(() => timeZones().map((z) => ({ value: z, label: z.replace(/_/g, " ") })), []);
  return { countries, zones };
}

function CreateSheet({ onClose, onCreated }: { onClose: () => void; onCreated: (s: Secret) => void }) {
  const { t } = useI18n();
  const { countries, zones } = useRegionOptions();
  const [f, setF] = useState({ code: "", name: "", country: "EG", timezone: "Africa/Cairo", default_language: "en", preset: "pharma", adminName: "", adminEmail: "" });
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (v: string) => setF((s) => ({ ...s, [k]: v }));
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      const res = await post("/api/platform/tenants", {
        code: f.code, name: f.name, country: f.country, timezone: f.timezone, default_language: f.default_language,
        preset: f.preset, admin: { full_name: f.adminName, email: f.adminEmail },
      });
      onCreated({ name: res.admin.full_name, email: res.admin.email, secret: res.temporary_password });
    } catch (e) {
      setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false);
    }
  };
  return (
    <Sheet title={t("companies.form.title")} lead={t("companies.form.lead")} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{t("companies.form.submit")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <TextField label={t("companies.form.name")} value={f.name} onChange={set("name")} error={errs.name} required />
      <TextField label={t("companies.form.code")} hint={t("companies.form.codeHint")} value={f.code} dir="ltr"
        onChange={(v) => set("code")(v.toUpperCase())} error={errs.code} maxLength={20} required />
      <div className="grid-2">
        <SelectField label={t("common.country")} value={f.country} onChange={set("country")} options={countries} />
        <SelectField label={t("settings.defaultLanguage")} value={f.default_language} onChange={set("default_language")}
          options={[{ value: "en", label: "English" }, { value: "ar", label: "العربية" }]} />
      </div>
      <SelectField label={t("common.timezone")} value={f.timezone} onChange={set("timezone")} options={zones} />
      <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="field-label" style={{ marginBottom: 6 }}>{t("companies.form.preset")}</legend>
        {(["pharma", "general"] as const).map((p) => (
          <label key={p} className="check" style={{ alignItems: "flex-start", padding: "6px 0" }}>
            <input type="radio" name="preset" checked={f.preset === p} onChange={() => set("preset")(p)} style={{ marginTop: 3 }} />
            <span><strong style={{ fontWeight: 500 }}>{t(p === "pharma" ? "companies.form.pharma" : "companies.form.general")}</strong><br />
              <span className="small muted">{t(p === "pharma" ? "companies.form.pharmaHint" : "companies.form.generalHint")}</span></span>
          </label>
        ))}
      </fieldset>
      <h3 style={{ marginTop: 4 }}>{t("companies.form.admin")}</h3>
      <TextField label={t("companies.form.adminName")} value={f.adminName} onChange={set("adminName")} error={errs["admin.full_name"]} required />
      <TextField label={t("companies.form.adminEmail")} type="email" dir="ltr" value={f.adminEmail} onChange={set("adminEmail")} error={errs["admin.email"]} required />
    </Sheet>
  );
}

function ManageSheet({ tenant, onClose, onSaved, onSecret }: { tenant: Tenant; onClose: () => void; onSaved: () => void; onSecret: (s: Secret) => void }) {
  const { t, dateTime } = useI18n();
  const toast = useToast();
  const { countries, zones } = useRegionOptions();
  const [f, setF] = useState({ name: tenant.name, country: tenant.country, timezone: tenant.timezone, default_language: tenant.default_language as string });
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const admins = useLoad(() => get<{ items: Admin[] }>(`/api/platform/tenants/${tenant.id}/admins`), [tenant.id]);
  const [adding, setAdding] = useState(false);
  const [na, setNa] = useState({ full_name: "", email: "" });
  const [naErr, setNaErr] = useState<Record<string, string>>({});
  const [resetFor, setResetFor] = useState<Admin | null>(null);
  const set = (k: keyof typeof f) => (v: string) => setF((s) => ({ ...s, [k]: v }));

  const save = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      await patch(`/api/platform/tenants/${tenant.id}`, f);
      toast(t("companies.updatedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  const addAdmin = async () => {
    setNaErr({});
    try {
      const res = await post(`/api/platform/tenants/${tenant.id}/admins`, na);
      setAdding(false); setNa({ full_name: "", email: "" }); admins.reload(); onSaved();
      onSecret({ name: res.admin.full_name, email: res.admin.email, secret: res.temporary_password });
    } catch (e) { setNaErr({ ...fieldErrors(e), _: errorText(e, t) }); }
  };

  return (
    <Sheet title={t("companies.edit")} lead={`${tenant.code}`} onClose={onClose} onSubmit={save}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{t("common.save")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <TextField label={t("companies.form.name")} value={f.name} onChange={set("name")} error={errs.name} />
      <div className="grid-2">
        <SelectField label={t("common.country")} value={f.country} onChange={set("country")} options={countries} />
        <SelectField label={t("settings.defaultLanguage")} value={f.default_language} onChange={set("default_language")}
          options={[{ value: "en", label: "English" }, { value: "ar", label: "العربية" }]} />
      </div>
      <SelectField label={t("common.timezone")} value={f.timezone} onChange={set("timezone")} options={zones} />

      <div className="row"><h3>{t("companies.admins")}</h3><span className="spacer" />
        {!adding && <Button size="sm" icon={<LuUserPlus />} onClick={() => setAdding(true)}>{t("companies.addAdmin")}</Button>}</div>
      {admins.error ? <LoadError error={admins.error} onRetry={admins.reload} /> : (
        <div className="panel">
          <table className="table">
            <tbody>
              {(admins.data?.items ?? []).map((a) => (
                <tr key={a.id}>
                  <td><div className="cell-main">{a.full_name}</div><div className="cell-sub" dir="ltr" style={{ textAlign: "start" }}>{a.email}</div></td>
                  <td className="small muted">{a.must_change_password ? t("users.mustChange") : a.last_login_at ? dateTime(a.last_login_at) : t("common.never")}</td>
                  <td className="actions"><Button size="sm" variant="ghost" icon={<LuKeyRound />} onClick={() => setResetFor(a)}>{t("companies.resetAdmin")}</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {adding && (
        <div className="panel"><div className="panel-body stack">
          {naErr._ && <Notice tone="danger">{naErr._}</Notice>}
          <TextField label={t("companies.form.adminName")} value={na.full_name} onChange={(v) => setNa((s) => ({ ...s, full_name: v }))} error={naErr.full_name} />
          <TextField label={t("companies.form.adminEmail")} type="email" dir="ltr" value={na.email} onChange={(v) => setNa((s) => ({ ...s, email: v }))} error={naErr.email} />
          <div className="row"><Button variant="primary" size="sm" onClick={addAdmin}>{t("companies.addAdmin")}</Button>
            <Button size="sm" onClick={() => setAdding(false)}>{t("common.cancel")}</Button></div>
        </div></div>
      )}
      {resetFor && (
        <Confirm title={t("users.resetConfirm", { name: resetFor.full_name })} body={t("users.resetBody")} confirmLabel={t("users.resetPassword")}
          onClose={() => setResetFor(null)}
          onConfirm={async () => {
            const res = await post(`/api/platform/users/${resetFor.id}/reset-password`);
            onSecret({ name: resetFor.full_name, email: resetFor.email, secret: res.temporary_password });
          }} />
      )}
    </Sheet>
  );
}

export function Companies() {
  const { t, date, countryName, number } = useI18n();
  const toast = useToast();
  const { data, error, loading, reload } = useLoad(() => get<{ items: Tenant[] }>("/api/platform/tenants"));
  const [creating, setCreating] = useState(false);
  const [managing, setManaging] = useState<Tenant | null>(null);
  const [suspending, setSuspending] = useState<Tenant | null>(null);
  const [secret, setSecret] = useState<Secret | null>(null);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("new") === "1") {
      setCreating(true);
      window.history.replaceState(null, "", "/companies");
    }
  }, []);
  const items = data?.items ?? [];

  return (
    <>
      <PageHead title={t("companies.title")} lead={t("companies.lead")}
        actions={<Button variant="primary" icon={<LuPlus />} onClick={() => setCreating(true)}>{t("companies.new")}</Button>} />
      <div className="panel">
        {error ? <LoadError error={error} onRetry={reload} /> : !loading && items.length === 0 ? (
          <Empty icon={<LuBuilding2 />} title={t("companies.empty")} body={t("companies.emptyBody")}
            action={<Button variant="primary" icon={<LuPlus />} onClick={() => setCreating(true)}>{t("companies.new")}</Button>} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th>{t("common.name")}</th><th>{t("common.country")}</th><th className="num">{t("companies.sites")}</th>
                <th className="num">{t("companies.users")}</th><th>{t("common.status")}</th><th>{t("companies.created")}</th><th><span className="visually-hidden">{t("common.actions")}</span></th>
              </tr></thead>
              {loading && !data ? <LoadingRows cols={7} /> : (
                <tbody>
                  {items.map((x) => (
                    <tr key={x.id} className={`clickable ${x.status !== "active" ? "inactive" : ""}`} onClick={() => setManaging(x)}>
                      <td><div className="cell-main">{x.name}</div><div className="cell-sub mono-id">{x.code}</div></td>
                      <td>{countryName(x.country)}</td>
                      <td className="num">{number(x.site_count)}</td>
                      <td className="num">{number(x.user_count)}</td>
                      <td>{x.status === "active" ? <Badge tone="ok" dot>{t("common.active")}</Badge> : <Badge tone="warn" dot>{t("companies.suspended")}</Badge>}</td>
                      <td className="small muted">{date(x.created_at)}</td>
                      <td className="actions" onClick={(e) => e.stopPropagation()}>
                        <Menu trigger={(p) => <Button variant="ghost" iconOnly size="sm" aria-label={t("common.actions")} icon={<LuEllipsis />} {...p} />}>
                          {(close) => <>
                            <MenuItem icon={<LuPencil />} onClick={() => { close(); setManaging(x); }}>{t("companies.manage")}</MenuItem>
                            {x.status === "active"
                              ? <MenuItem danger icon={<LuBan />} onClick={() => { close(); setSuspending(x); }}>{t("companies.suspend")}</MenuItem>
                              : <MenuItem icon={<LuPower />} onClick={async () => { close(); await patch(`/api/platform/tenants/${x.id}`, { status: "active" }); toast(t("companies.updatedToast")); reload(); }}>{t("companies.activate")}</MenuItem>}
                          </>}
                        </Menu>
                      </td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}
      </div>
      {creating && <CreateSheet onClose={() => setCreating(false)} onCreated={(s) => { setCreating(false); toast(t("companies.createdToast")); reload(); setSecret(s); }} />}
      {managing && <ManageSheet tenant={managing} onClose={() => setManaging(null)} onSaved={reload} onSecret={setSecret} />}
      {suspending && <Confirm danger title={t("companies.suspendConfirm", { name: suspending.name })} body={t("companies.suspendBody")}
        confirmLabel={t("companies.suspend")} onClose={() => setSuspending(null)}
        onConfirm={async () => { await patch(`/api/platform/tenants/${suspending.id}`, { status: "suspended" }); toast(t("companies.updatedToast")); reload(); }} />}
      {secret && <SecretReveal name={secret.name} email={secret.email} secret={secret.secret} onClose={() => setSecret(null)} />}
    </>
  );
}
