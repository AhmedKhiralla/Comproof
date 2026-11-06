import { useMemo, useState } from "react";
import { LuFactory, LuPlus } from "react-icons/lu";
import {
  Badge, Button, Empty, LoadError, LoadingRows, Notice, PageHead, SelectField, Sheet, Switch, TextField,
  errorText, fieldErrors, useLoad, useToast,
} from "../components/ui";
import { get, patch, post } from "../lib/api";
import { COUNTRIES, timeZones } from "../lib/geo";
import { useI18n } from "../lib/i18n";
import { useSession } from "../lib/session";

export interface SiteRow {
  id: string; code: string; name: string; country: string; timezone: string; address: string | null;
  active: boolean; user_count: number; updated_at: string;
}

function SiteSheet({ site, onClose, onSaved }: { site: SiteRow | null; onClose: () => void; onSaved: () => void }) {
  const { t, countryName } = useI18n();
  const { me } = useSession();
  const toast = useToast();
  const countries = useMemo(() => COUNTRIES.map((c) => ({ value: c, label: countryName(c) })).sort((a, b) => a.label.localeCompare(b.label)), [countryName]);
  const zones = useMemo(() => timeZones().map((z) => ({ value: z, label: z.replace(/_/g, " ") })), []);
  const [f, setF] = useState({
    code: site?.code ?? "", name: site?.name ?? "", country: site?.country ?? me?.tenant?.country ?? "EG",
    timezone: site?.timezone ?? me?.tenant?.timezone ?? "Africa/Cairo", address: site?.address ?? "", active: site?.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (v: string) => setF((s) => ({ ...s, [k]: v }));

  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      if (site) await patch(`/api/sites/${site.id}`, { name: f.name, country: f.country, timezone: f.timezone, address: f.address, active: f.active });
      else await post("/api/sites", { code: f.code, name: f.name, country: f.country, timezone: f.timezone, address: f.address || null });
      toast(t("sites.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };

  return (
    <Sheet title={site ? t("sites.form.edit") : t("sites.form.new")} lead={site ? site.code : undefined} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{site ? t("common.save") : t("common.create")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <TextField label={t("common.name")} value={f.name} onChange={set("name")} error={errs.name} required />
      {!site && <TextField label={t("common.code")} hint={t("sites.form.codeHint")} value={f.code} dir="ltr" maxLength={20}
        onChange={(v) => set("code")(v.toUpperCase())} error={errs.code} required />}
      <div className="grid-2">
        <SelectField label={t("common.country")} value={f.country} onChange={set("country")} options={countries} />
        <SelectField label={t("common.timezone")} value={f.timezone} onChange={set("timezone")} options={zones} />
      </div>
      <div className="field">
        <label htmlFor="site-address">{t("sites.address")} <span className="subtle small">({t("common.optional")})</span></label>
        <textarea id="site-address" className="textarea" value={f.address} onChange={(e) => set("address")(e.target.value)} maxLength={400} />
      </div>
      {site && (
        <div className="feature" style={{ padding: "4px 0", border: 0 }}>
          <div className="text"><strong>{f.active ? t("sites.deactivate") : t("sites.activate")}</strong><span>{t("sites.deactivateHint")}</span></div>
          <Switch label={t("common.active")} checked={f.active} onChange={(v) => setF((s) => ({ ...s, active: v }))} />
        </div>
      )}
    </Sheet>
  );
}

export function Sites() {
  const { t, countryName, number } = useI18n();
  const { refresh } = useSession();
  const { data, error, loading, reload } = useLoad(() => get<{ items: SiteRow[] }>("/api/sites"));
  const [editing, setEditing] = useState<SiteRow | "new" | null>(null);
  const items = data?.items ?? [];
  const saved = () => { reload(); refresh(); };

  return (
    <>
      <PageHead title={t("sites.title")} lead={t("sites.lead")}
        actions={<Button variant="primary" icon={<LuPlus />} onClick={() => setEditing("new")}>{t("sites.new")}</Button>} />
      <div className="panel">
        {error ? <LoadError error={error} onRetry={reload} /> : !loading && items.length === 0 ? (
          <Empty icon={<LuFactory />} title={t("sites.empty")} body={t("sites.emptyBody")}
            action={<Button variant="primary" icon={<LuPlus />} onClick={() => setEditing("new")}>{t("sites.new")}</Button>} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th>{t("common.name")}</th><th>{t("common.country")}</th><th>{t("common.timezone")}</th>
                <th className="num">{t("sites.users")}</th><th>{t("common.status")}</th>
              </tr></thead>
              {loading && !data ? <LoadingRows cols={5} /> : (
                <tbody>
                  {items.map((s) => (
                    <tr key={s.id} className={`clickable ${s.active ? "" : "inactive"}`} onClick={() => setEditing(s)}
                      tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") setEditing(s); }}>
                      <td><div className="cell-main">{s.name}</div><div className="cell-sub mono-id">{s.code}</div></td>
                      <td>{countryName(s.country)}</td>
                      <td className="muted" dir="ltr" style={{ textAlign: "start" }}>{s.timezone.replace(/_/g, " ")}</td>
                      <td className="num">{number(s.user_count)}</td>
                      <td>{s.active ? <Badge tone="ok" dot>{t("common.active")}</Badge> : <Badge>{t("common.inactive")}</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}
      </div>
      {editing && <SiteSheet site={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={saved} />}
    </>
  );
}
