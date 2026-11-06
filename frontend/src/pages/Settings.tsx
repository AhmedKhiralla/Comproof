import { useEffect, useMemo, useState } from "react";
import {
  Button, LoadError, Notice, PageHead, SelectField, Switch, TextField, errorText, fieldErrors, useLoad, useToast,
} from "../components/ui";
import { get, patch, post, put } from "../lib/api";
import { COUNTRIES, timeZones } from "../lib/geo";
import { useI18n } from "../lib/i18n";
import { navigate } from "../lib/router";
import { useSession, type Policy } from "../lib/session";
import type { StringKey } from "../lib/strings";

interface SettingsData {
  company: { id: string; code: string; name: string; country: string; timezone: string; default_language: "en" | "ar" };
  features: Record<string, boolean>;
  feature_groups: Record<string, string>;
  engine: { provider: string | null; reading_provider: string | null; exclude_phrases: string[]; rotated_text: "auto" | "ignore" | "read";
    colour_tolerance: number; flat_tolerance: number; min_font_pt: Record<string, number>; braille_required: string[]; cut_margin_mm: number };
  ai_providers: { name: string; label: string; vision_model: string; text_model: string }[];
  terminology: Record<string, { en: string; ar: string }>;
  terminology_defaults: Record<string, { en: string; ar: string }>;
  security: Policy;
  security_limits: Record<string, [number, number]>;
}

const TABS = ["company", "features", "engine", "terms", "security"] as const;
type Tab = (typeof TABS)[number];

function useSaver(onSaved: (d: SettingsData) => void) {
  const { t } = useI18n();
  const toast = useToast();
  const { refresh } = useSession();
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const run = async (fn: () => Promise<SettingsData>) => {
    setBusy(true); setErrs({}); setGeneral(null);
    try { const d = await fn(); onSaved(d); toast(t("settings.savedToast")); refresh(); }
    catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); }
    finally { setBusy(false); }
  };
  return { busy, errs, general, run };
}

function CompanyTab({ data, onSaved }: { data: SettingsData; onSaved: (d: SettingsData) => void }) {
  const { t, countryName } = useI18n();
  const [f, setF] = useState({ ...data.company });
  const s = useSaver(onSaved);
  const countries = useMemo(() => COUNTRIES.map((c) => ({ value: c, label: countryName(c) })).sort((a, b) => a.label.localeCompare(b.label)), [countryName]);
  const zones = useMemo(() => timeZones().map((z) => ({ value: z, label: z.replace(/_/g, " ") })), []);
  return (
    <form className="panel" onSubmit={(e) => { e.preventDefault(); s.run(() => patch("/api/settings/company", { name: f.name, country: f.country, timezone: f.timezone, default_language: f.default_language })); }}>
      <div className="panel-head"><p className="muted">{t("settings.companyLead")}</p></div>
      <div className="panel-body stack" style={{ maxWidth: 640 }}>
        {s.general && <Notice tone="danger">{s.general}</Notice>}
        <div className="grid-2">
          <TextField label={t("companies.form.name")} value={f.name} onChange={(v) => setF({ ...f, name: v })} error={s.errs.name} />
          <TextField label={t("companies.form.code")} value={f.code} onChange={() => {}} disabled dir="ltr" />
        </div>
        <div className="grid-2">
          <SelectField label={t("common.country")} value={f.country} onChange={(v) => setF({ ...f, country: v })} options={countries} />
          <SelectField label={t("common.timezone")} value={f.timezone} onChange={(v) => setF({ ...f, timezone: v })} options={zones} />
        </div>
        <div className="grid-2">
          <SelectField label={t("settings.defaultLanguage")} value={f.default_language} onChange={(v) => setF({ ...f, default_language: v as "en" | "ar" })}
            options={[{ value: "en", label: "English" }, { value: "ar", label: "العربية" }]} />
        </div>
        <div><Button type="submit" variant="primary" busy={s.busy}>{t("common.save")}</Button></div>
      </div>
    </form>
  );
}

function FeaturesTab({ data, onSaved }: { data: SettingsData; onSaved: (d: SettingsData) => void }) {
  const { t, tx } = useI18n();
  const [f, setF] = useState({ ...data.features });
  const s = useSaver(onSaved);
  const dirty = Object.keys(f).some((k) => f[k] !== data.features[k]);
  const groups = ["levels", "checks", "review", "ai"];
  return (
    <div className="stack">
      <div className="row wrap">
        <p className="muted" style={{ flex: "1 1 320px" }}>{t("settings.features.lead")}</p>
      </div>
      {s.general && <Notice tone="danger">{s.general}</Notice>}
      {groups.map((g) => (
        <section className="panel" key={g} aria-labelledby={`fg-${g}`}>
          <div className="panel-head"><h3 id={`fg-${g}`}>{tx(`settings.group.${g}`, g)}</h3></div>
          {Object.keys(f).filter((k) => data.feature_groups[k] === g).map((k) => (
            <div className="feature" key={k}>
              <div className="text"><strong>{tx(`feature.${k}`, k)}</strong><span>{tx(`feature.${k}.d`, "")}</span></div>
              <Switch label={tx(`feature.${k}`, k)} checked={f[k]} onChange={(v) => setF({ ...f, [k]: v })} />
            </div>
          ))}
        </section>
      ))}
      <div className="row">
        <Button variant="primary" busy={s.busy} disabled={!dirty} onClick={() => s.run(() => put("/api/settings/features", { features: f }))}>{t("common.save")}</Button>
        {dirty && <Button variant="ghost" onClick={() => setF({ ...data.features })}>{t("common.cancel")}</Button>}
      </div>
    </div>
  );
}

function TermsTab({ data, onSaved }: { data: SettingsData; onSaved: (d: SettingsData) => void }) {
  const { t, tx } = useI18n();
  const keys = Object.keys(data.terminology_defaults);
  const initial = () => Object.fromEntries(keys.map((k) => [k, {
    en: data.terminology[k].en === data.terminology_defaults[k].en ? "" : data.terminology[k].en,
    ar: data.terminology[k].ar === data.terminology_defaults[k].ar ? "" : data.terminology[k].ar,
  }]));
  const [f, setF] = useState<Record<string, { en: string; ar: string }>>(initial);
  useEffect(() => { setF(initial()); }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const s = useSaver(onSaved);
  return (
    <div className="stack">
      <p className="muted">{t("settings.terms.lead")}</p>
      {s.general && <Notice tone="danger">{s.general}</Notice>}
      <div className="panel table-wrap">
        <table className="table">
          <thead><tr><th>{t("settings.terms.term")}</th><th>English</th><th>العربية</th></tr></thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k}>
                <td className="cell-main">{tx(`term.${k}`, k)}</td>
                <td><input className="input" dir="ltr" lang="en" placeholder={data.terminology_defaults[k].en} value={f[k].en} maxLength={60}
                  aria-label={`${tx(`term.${k}`, k)} — English`} onChange={(e) => setF({ ...f, [k]: { ...f[k], en: e.target.value } })} /></td>
                <td><input className="input" dir="rtl" lang="ar" placeholder={data.terminology_defaults[k].ar} value={f[k].ar} maxLength={60}
                  aria-label={`${tx(`term.${k}`, k)} — العربية`} onChange={(e) => setF({ ...f, [k]: { ...f[k], ar: e.target.value } })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div><Button variant="primary" busy={s.busy} onClick={() => s.run(() => put("/api/settings/terminology", { terminology: f }))}>{t("common.save")}</Button></div>
    </div>
  );
}

function SecurityTab({ data, onSaved }: { data: SettingsData; onSaved: (d: SettingsData) => void }) {
  const { t } = useI18n();
  const [f, setF] = useState<Policy>({ ...data.security });
  const s = useSaver(onSaved);
  const num = (k: keyof Policy, hint?: StringKey) => {
    const [lo, hi] = data.security_limits[k];
    return (
      <TextField key={k} label={t(`sec.${k}` as StringKey)} type="number" inputMode="numeric" min={lo} max={hi}
        value={String(f[k])} onChange={(v) => setF({ ...f, [k]: v === "" ? 0 : Number(v) })}
        hint={(hint ? t(hint) + " " : "") + t("sec.range", { lo, hi })} error={s.errs[k]} />
    );
  };
  const flag = (k: keyof Policy) => (
    <div className="feature" key={k} style={{ padding: "10px 0" }}>
      <div className="text"><strong style={{ fontWeight: 500 }}>{t(`sec.${k}` as StringKey)}</strong></div>
      <Switch label={t(`sec.${k}` as StringKey)} checked={f[k] as boolean} onChange={(v) => setF({ ...f, [k]: v })} />
    </div>
  );
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); s.run(() => put("/api/settings/security", f)); }}>
      <p className="muted">{t("settings.security.lead")}</p>
      {s.general && <Notice tone="danger">{s.general}</Notice>}
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="panel" aria-labelledby="sec-pw">
          <div className="panel-head"><h3 id="sec-pw">{t("settings.security.passwords")}</h3></div>
          <div className="panel-body stack">
            {num("min_length")}
            <div>{flag("require_upper")}{flag("require_lower")}{flag("require_digit")}{flag("require_symbol")}</div>
            {num("expiry_days", "sec.expiry_days.h")}
            {num("history")}
          </div>
        </section>
        <section className="panel" aria-labelledby="sec-si">
          <div className="panel-head"><h3 id="sec-si">{t("settings.security.signin")}</h3></div>
          <div className="panel-body stack">
            {num("max_failed_attempts")}
            {num("lockout_minutes")}
            {num("session_timeout_minutes")}
          </div>
        </section>
      </div>
      <div><Button type="submit" variant="primary" busy={s.busy}>{t("common.save")}</Button></div>
    </form>
  );
}

function EngineTab({ data, onSaved }: { data: SettingsData; onSaved: (d: SettingsData) => void }) {
  const { t } = useI18n();
  const s = useSaver(onSaved);
  const [f, setF] = useState({ ...data.engine, phrases: data.engine.exclude_phrases.join("\n") });
  const providers = [{ value: "", label: t("engine.firstAvailable") }, ...data.ai_providers.map((p) => ({ value: p.name, label: p.label }))];
  type TestRow = { role: string; model: string; ok: boolean; ms?: number; error?: string };
  const [tests, setTests] = useState<Record<string, TestRow[]>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const runTest = async (name: string) => {
    setTesting(name);
    try { const r = await post<{ results: TestRow[] }>("/api/settings/engine/test", { provider: name }); setTests((x) => ({ ...x, [name]: r.results })); }
    catch (e) { setTests((x) => ({ ...x, [name]: [{ role: "text", model: "—", ok: false, error: errorText(e, t) }] })); }
    finally { setTesting(null); }
  };
  const save = () => s.run(() => put("/api/settings/engine", {
    provider: f.provider || null, reading_provider: f.reading_provider || null, rotated_text: f.rotated_text,
    exclude_phrases: f.phrases.split("\n").map((x) => x.trim()).filter(Boolean),
    colour_tolerance: Number(f.colour_tolerance), flat_tolerance: Number(f.flat_tolerance), min_font_pt: f.min_font_pt,
    braille_required: f.braille_required, cut_margin_mm: Number(f.cut_margin_mm),
  }));
  const KINDS_ = ["leaflet", "carton", "label", "sachet", "blister_foil", "tube", "other"];
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); save(); }}>
      <p className="muted">{t("engine.lead")}</p>
      {s.general && <Notice tone="danger">{s.general}</Notice>}
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="panel" aria-labelledby="eng-ai">
          <div className="panel-head"><h3 id="eng-ai">{t("engine.ai")}</h3></div>
          <div className="panel-body stack">
            {data.ai_providers.length === 0 ? <Notice tone="warn">{t("engine.noProviders")}</Notice> : (
              <>
                <SelectField label={t("engine.provider")} hint={t("engine.providerHint")} value={f.provider ?? ""} options={providers}
                  error={s.errs.provider} onChange={(v) => setF({ ...f, provider: v || null })} />
                <SelectField label={t("engine.readingProvider")} hint={t("engine.readingProviderHint")} value={f.reading_provider ?? ""}
                  options={[{ value: "", label: t("engine.sameProvider") }, ...providers.slice(1)]} error={s.errs.reading_provider}
                  onChange={(v) => setF({ ...f, reading_provider: v || null })} />
                <ul className="plain small muted">
                  {data.ai_providers.map((p) => (
                    <li key={p.name}>
                      <strong>{p.label}</strong>: {t("engine.models", { vision: p.vision_model, text: p.text_model })}{" "}
                      <button type="button" className="link-btn" disabled={testing === p.name} onClick={() => runTest(p.name)}>
                        {testing === p.name ? t("engine.testing") : t("engine.test")}
                      </button>
                      {tests[p.name] && (
                        <ul className="plain ai-test">
                          {tests[p.name].map((r) => (
                            <li key={r.role} className={r.ok ? "ok" : "bad"}>
                              {r.ok ? "✓" : "✕"} {t(r.role === "vision" ? "engine.testVision" : "engine.testText")} · <code>{r.model}</code>
                              {r.ok ? ` · ${r.ms} ms` : <div className="small">{r.error}</div>}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </section>
        <section className="panel" aria-labelledby="eng-text">
          <div className="panel-head"><h3 id="eng-text">{t("engine.text")}</h3></div>
          <div className="panel-body stack">
            <SelectField label={t("engine.rotated")} hint={t("engine.rotatedHint")} value={f.rotated_text}
              options={[{ value: "auto", label: t("engine.rotated.auto") }, { value: "ignore", label: t("engine.rotated.ignore") }, { value: "read", label: t("engine.rotated.read") }]}
              onChange={(v) => setF({ ...f, rotated_text: v as typeof f.rotated_text })} />
            <div className="field">
              <label htmlFor="eng-phrases">{t("engine.phrases")}</label>
              <textarea id="eng-phrases" className="textarea" rows={6} value={f.phrases} onChange={(e) => setF({ ...f, phrases: e.target.value })} />
              <div className="hint">{t("engine.phrasesHint")}</div>
            </div>
          </div>
        </section>
      </div>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="panel" aria-labelledby="eng-col">
          <div className="panel-head"><h3 id="eng-col">{t("engine.colour")}</h3></div>
          <div className="panel-body stack">
            <TextField label={t("engine.colourTol")} type="number" step="0.1" min={0.5} max={10} value={String(f.colour_tolerance)}
              onChange={(v) => setF({ ...f, colour_tolerance: Number(v) })} hint={t("engine.colourTolHint")} error={s.errs.colour_tolerance} />
            <TextField label={t("engine.flatTol")} type="number" step="0.1" min={0.5} max={10} value={String(f.flat_tolerance)}
              onChange={(v) => setF({ ...f, flat_tolerance: Number(v) })} hint={t("engine.flatTolHint")} error={s.errs.flat_tolerance} />
          </div>
        </section>
        <section className="panel" aria-labelledby="eng-print">
          <div className="panel-head"><h3 id="eng-print">{t("engine.print")}</h3></div>
          <div className="panel-body stack">
            <div className="field"><span className="label-like">{t("engine.minFont")}</span>
              <div className="font-grid">{KINDS_.map((k) => (
                <label key={k} className="small"><span>{t(`kind.${k}` as StringKey)}</span>
                  <input className="input" type="number" step="0.5" min={4} max={20} value={f.min_font_pt?.[k] ?? 7}
                    onChange={(e) => setF({ ...f, min_font_pt: { ...f.min_font_pt, [k]: Number(e.target.value) } })} /></label>))}</div>
              <div className="hint">{t("engine.minFontHint")}</div></div>
            <div className="field"><span className="label-like">{t("engine.braille")}</span>
              <div className="row wrap">{KINDS_.map((k) => (
                <label key={k} className="row small"><input type="checkbox" checked={f.braille_required.includes(k)}
                  onChange={(e) => setF({ ...f, braille_required: e.target.checked ? [...f.braille_required, k] : f.braille_required.filter((x) => x !== k) })} />
                  {t(`kind.${k}` as StringKey)}</label>))}</div>
              <div className="hint">{t("engine.brailleHint")}</div></div>
            <TextField label={t("engine.cutMargin")} type="number" step="0.5" min={0} max={10} value={String(f.cut_margin_mm)}
              onChange={(v) => setF({ ...f, cut_margin_mm: Number(v) })} />
          </div>
        </section>
      </div>
      <div><Button type="submit" variant="primary" busy={s.busy}>{t("common.save")}</Button></div>
    </form>
  );
}

export function Settings() {
  const { t, tx } = useI18n();
  const { me } = useSession();
  const { data, error, reload, setData } = useLoad(() => get<SettingsData>("/api/settings"));
  const initialTab = new URLSearchParams(window.location.search).get("tab") as Tab | null;
  const [tab, setTabState] = useState<Tab>(initialTab && TABS.includes(initialTab) ? initialTab : "company");
  const setTab = (x: Tab) => { setTabState(x); navigate(`/settings?tab=${x}`, true); };
  const labels: Record<Tab, StringKey> = { company: "settings.tab.company", features: "settings.tab.features", engine: "settings.tab.engine", terms: "settings.tab.terms", security: "settings.tab.security" };
  return (
    <>
      <PageHead title={t("settings.title")} lead={t("settings.lead", { company: me?.tenant?.name ?? "" })} />
      <div className="tabs" role="tablist">
        {TABS.map((x) => (
          <button key={x} type="button" role="tab" className="tab" aria-selected={tab === x} onClick={() => setTab(x)}>{tx(labels[x], x)}</button>
        ))}
      </div>
      {error ? <div className="panel"><LoadError error={error} onRetry={reload} /></div> : !data ? (
        <div className="panel"><div className="panel-body"><div className="skeleton" style={{ width: "40%" }} /></div></div>
      ) : (
        <div role="tabpanel">
          {tab === "company" && <CompanyTab data={data} onSaved={setData} />}
          {tab === "features" && <FeaturesTab key={JSON.stringify(data.features)} data={data} onSaved={setData} />}
          {tab === "terms" && <TermsTab data={data} onSaved={setData} />}
          {tab === "security" && <SecurityTab key={JSON.stringify(data.security)} data={data} onSaved={setData} />}
          {tab === "engine" && <EngineTab key={JSON.stringify(data.engine)} data={data} onSaved={setData} />}
        </div>
      )}
    </>
  );
}
