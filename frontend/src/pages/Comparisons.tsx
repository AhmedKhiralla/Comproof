// Comparisons: list, and starting a new one.
import { useEffect, useMemo, useState } from "react";
import { LuFilePlus2, LuFileSearch, LuPlay } from "react-icons/lu";
import { FileDrop, SevCounts, StatusBadge, type CompStatus, type UploadedFile } from "../components/cp";
import {
  Button, Empty, LoadError, LoadingRows, Notice, PageHead, SelectField, Switch, TextField, errorText, fieldErrors, useLoad,
} from "../components/ui";
import { get, post, qs } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { navigate } from "../lib/router";
import { usePerms, useSession } from "../lib/session";
import type { StringKey } from "../lib/strings";
import { KINDS } from "./Products";

export interface ComparisonRow {
  id: string; number: string; title: string; purpose: string; status: CompStatus; progress: string | null; site_code: string;
  component_code: string | null; component_kind: string | null; product_code: string | null; product_name: string | null;
  supplier: string | null; reference_no: string | null; result_summary: { steps: Record<string, Record<string, number>>; total: number } | null;
  created_at: string; finished_at: string | null; closed_at: string | null; created_by_name: string | null;
  reference_filename: string; test_filename: string | null;
}

const STATUSES: CompStatus[] = ["queued", "running", "review", "approved", "rejected", "failed", "cancelled"];

export function ComparisonTable({ items, loading }: { items: ComparisonRow[]; loading?: boolean }) {
  const { t, dateTime } = useI18n();
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>{t("cmp.number")}</th><th>{t("cmp.subject")}</th><th>{t("common.status")}</th>
          <th>{t("cmp.findings")}</th><th>{t("cmp.started")}</th></tr></thead>
        {loading ? <LoadingRows cols={5} /> : (
          <tbody>
            {items.map((c) => (
              <tr key={c.id} className="clickable" tabIndex={0} onClick={() => navigate(`/comparisons/${c.id}`)}
                onKeyDown={(e) => { if (e.key === "Enter") navigate(`/comparisons/${c.id}`); }}>
                <td className="mono-id">{c.number}</td>
                <td><div className="cell-main">{c.title}</div>
                  <div className="cell-sub">{[c.product_code, c.component_kind && t(`kind.${c.component_kind}` as StringKey), t(`purpose.${c.purpose}` as StringKey), c.supplier].filter(Boolean).join(" · ")}</div></td>
                <td><StatusBadge status={c.status} />{(c.status === "running" || c.status === "queued") && c.progress && <div className="cell-sub">{c.progress}</div>}</td>
                <td><SevCounts summary={c.result_summary} /></td>
                <td><div>{dateTime(c.created_at)}</div><div className="cell-sub">{c.created_by_name} · {c.site_code}</div></td>
              </tr>
            ))}
          </tbody>
        )}
      </table>
    </div>
  );
}

export function Comparisons() {
  const { t } = useI18n();
  const { startAt, siteId } = usePerms();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useLoad(
    () => get<{ items: ComparisonRow[]; total: number }>("/api/comparisons" + qs({ q, status, page })), [q, status, page]);
  useEffect(() => {
    if (!data?.items.some((c) => c.status === "queued" || c.status === "running")) return;
    const id = setInterval(reload, 4000);
    return () => clearInterval(id);
  }, [data, reload]);
  const items = data?.items ?? [];
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / 50));
  return (
    <>
      <PageHead title={t("cmp.title")} lead={t("cmp.lead")}
        actions={startAt(siteId) && <Button variant="primary" icon={<LuFilePlus2 />} onClick={() => navigate("/comparisons/new")}>{t("nav.newComparison")}</Button>} />
      <div className="panel">
        <div className="panel-head wrap">
          <input className="input" style={{ maxWidth: 320 }} placeholder={t("cmp.search")} aria-label={t("cmp.search")} value={q}
            onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <select className="select" style={{ maxWidth: 220 }} value={status} aria-label={t("common.status")} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">{t("cmp.allStatuses")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}` as StringKey)}</option>)}
          </select>
        </div>
        {error ? <LoadError error={error} onRetry={reload} /> : !loading && items.length === 0 ? (
          <Empty icon={<LuFileSearch />} title={t("cmp.empty")} body={t("cmp.emptyBody")}
            action={startAt(siteId) && <Button variant="primary" icon={<LuFilePlus2 />} onClick={() => navigate("/comparisons/new")}>{t("nav.newComparison")}</Button>} />
        ) : <ComparisonTable items={items} loading={loading && !data} />}
        {pages > 1 && <div className="panel-foot row">
          <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("common.previous")}</Button>
          <span className="small muted">{t("common.pageOf", { page, pages })}</span>
          <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("common.next")}</Button>
        </div>}
      </div>
    </>
  );
}

interface ComponentPick {
  id: string; code: string; kind: string; name: string; languages: string[]; product_code: string; product_name: string;
  artwork_id: string | null; artwork_version: string | null; artwork_filename: string | null;
  shade_set_id: string | null; shade_version: string | null; shade_source: string | null;
}
const CHECKS = ["colour", "barcodes", "graphics", "text_size", "braille", "dieline"] as const;

export function NewComparison() {
  const { t } = useI18n();
  const { me, siteId } = useSession();
  const { startAt } = usePerms();
  const qp = new URLSearchParams(window.location.search);
  const preset = qp.get("component") ?? "";
  const comps = useLoad(() => get<{ items: ComponentPick[] }>("/api/components"));
  const sites = (me?.sites ?? []).filter((s) => startAt(s.id));
  const [f, setF] = useState({
    site_id: sites.find((s) => s.id === siteId)?.id ?? sites[0]?.id ?? "", component_id: preset, title: "",
    purpose: qp.get("review") ? "master_review" : "proof", kind: "leaflet", supplier: "", reference_no: "", eng: true, ara: true, step1: true, step3: true,
    mirror: false, rotated: "", aiRead: !!me?.tenant?.ai.read, text: true, sample_source: "scan",
  });
  const feat = me?.tenant?.features ?? {};
  const [checks, setChecks] = useState<Record<(typeof CHECKS)[number], boolean>>(
    () => Object.fromEntries(CHECKS.map((k) => [k, feat[`check_${k}`] !== false])) as Record<(typeof CHECKS)[number], boolean>);
  const [ref, setRef] = useState<UploadedFile | null>(null);
  const [customRef, setCustomRef] = useState(false);
  const [test, setTest] = useState<UploadedFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const comp = useMemo(() => comps.data?.items.find((c) => c.id === f.component_id) ?? null, [comps.data, f.component_id]);
  useEffect(() => {
    if (comp) setF((s) => ({ ...s, kind: comp.kind, eng: comp.languages.includes("en"), ara: comp.languages.includes("ar"),
      title: s.title || `${comp.product_name} · ${comp.name}`, mirror: comp.kind === "blister_foil" ? s.mirror : false }));
  }, [comp]);
  const useMaster = !!comp?.artwork_id && !customRef;
  const review = f.purpose === "master_review";
  const spectroTest = test?.doc_kind === "spectro";
  const textOn = (f.text && !spectroTest) || review;
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      const r = await post<{ id: string }>("/api/comparisons", {
        site_id: f.site_id, title: f.title, purpose: f.purpose, component_id: f.component_id || null,
        reference_file_id: useMaster ? null : ref?.id ?? null, test_file_id: review ? null : test?.id ?? "", supplier: f.supplier || null, reference_no: f.reference_no || null,
        kind: f.kind || null, languages: [f.eng && "eng", f.ara && "ara"].filter(Boolean), step1: f.step1, step3: f.step3,
        mirror_test: f.mirror, rotated_text: f.rotated || null, ai_read: f.aiRead, text: textOn,
        ...checks, sample_source: spectroTest ? "spectro" : f.sample_source,
      });
      navigate(`/comparisons/${r.id}`);
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  if (!sites.length) return <><PageHead title={t("nav.newComparison")} /><Notice tone="warn">{t("new.noAccess")}</Notice></>;
  return (
    <>
      <PageHead title={t("nav.newComparison")} lead={t("new.lead")} />
      <form className="new-cmp" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        {general && <Notice tone="danger">{general}</Notice>}
        <section className="panel">
          <div className="panel-head"><h2>{t("new.what")}</h2></div>
          <div className="panel-body stack">
            <SelectField label={t("new.component")} hint={t("new.componentHint")} value={f.component_id}
              onChange={(v) => setF({ ...f, component_id: v })}
              options={[{ value: "", label: t("new.noComponent") }, ...(comps.data?.items ?? []).map((c) => ({
                value: c.id, label: `${c.product_code} · ${c.code} · ${c.name}${c.artwork_version ? ` (v${c.artwork_version})` : ""}` }))]} />
            <TextField label={t("new.title")} value={f.title} onChange={(v) => setF({ ...f, title: v })} error={errs.title} required />
            <div className="grid-2">
              <SelectField label={t("new.purpose")} value={f.purpose} onChange={(v) => setF({ ...f, purpose: v })}
                options={["proof", "supplier_proof", "printed_sample", "master_review"].map((p) => ({ value: p, label: t(`purpose.${p}` as StringKey) }))} />
              <SelectField label={t("new.kind")} value={f.kind} onChange={(v) => setF({ ...f, kind: v })}
                options={KINDS.map((k) => ({ value: k, label: t(`kind.${k}` as StringKey) }))} />
            </div>
            <div className="grid-2">
              {!review && <TextField label={t("new.supplier")} value={f.supplier} onChange={(v) => setF({ ...f, supplier: v })} />}
              <TextField label={t("new.referenceNo")} value={f.reference_no} dir="ltr" onChange={(v) => setF({ ...f, reference_no: v })} />
            </div>
            {sites.length > 1 && <SelectField label={t("shell.site")} value={f.site_id} onChange={(v) => setF({ ...f, site_id: v })}
              options={sites.map((s) => ({ value: s.id, label: `${s.code} · ${s.name}` }))} />}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><h2>{t("new.files")}</h2></div>
          <div className="panel-body grid-2" style={{ alignItems: "start" }}>
            <div className="stack">
              {useMaster ? (
                <div className="field">
                  <span className="label-like">{t("new.reference")}</span>
                  <div className="file-chip master">
                    <span className="grow"><strong>{comp!.artwork_filename}</strong>
                      <span className="small muted">{t("new.masterUsed", { v: comp!.artwork_version ?? "" })}</span></span>
                  </div>
                  <div className="hint">{t("new.masterHint")}</div>
                </div>
              ) : null}
              {!useMaster && <FileDrop label={t("new.reference")} hint={t("new.referenceHint")} value={ref} onChange={setRef} error={errs.reference_file_id} />}
              {comp?.artwork_id && <button type="button" className="link-btn small" onClick={() => { setCustomRef(!customRef); setRef(null); }}>
                {customRef ? t("new.useMaster") : t("new.otherReference")}</button>}
            </div>
            {review ? <Notice>{t("review.noTestNeeded")}</Notice>
              : <FileDrop label={t("new.test")} hint={t(f.purpose === "printed_sample" ? "new.testHintSample" : "new.testHint")} value={test} onChange={setTest} error={errs.test_file_id} />}
          </div>
          {f.purpose === "printed_sample" && <div className="panel-body"><Notice tone="warn">{t("new.sampleNote")}</Notice></div>}
        </section>

        <section className="panel">
          <div className="panel-head"><h2>{t("new.how")}</h2></div>
          <div className="panel-body">
            <div className="feature"><div className="text"><strong>{t("new.languages")}</strong><span>{t("new.languagesHint")}</span></div>
              <div className="row">
                <label className="row small"><input type="checkbox" checked={f.eng} onChange={(e) => setF({ ...f, eng: e.target.checked })} />{t("common.english")}</label>
                <label className="row small"><input type="checkbox" checked={f.ara} onChange={(e) => setF({ ...f, ara: e.target.checked })} />{t("common.arabic")}</label>
              </div></div>
            {!review && <div className="feature"><div className="text"><strong>{t("new.text")}</strong><span>{t(spectroTest ? "new.textSpectro" : "new.textHint")}</span></div>
              <Switch label={t("new.text")} checked={textOn} disabled={spectroTest} onChange={(v) => setF({ ...f, text: v })} /></div>}
            {textOn && <>
            <div className="feature"><div className="text"><strong>{t("level.1")}</strong><span>{t("level.1.d")}</span></div>
              {review ? <span className="small muted">{t("new.always")}</span>
                : <Switch label={t("level.1")} checked={f.step1} onChange={(v) => setF({ ...f, step1: v })} />}</div>
            {!review && <>
            <div className="feature"><div className="text"><strong>{t("level.2")}</strong><span>{t("level.2.d")}</span></div>
              <span className="small muted">{t("new.always")}</span></div>
            <div className="feature"><div className="text"><strong>{t("level.3")}</strong><span>{t("level.3.d")}</span></div>
              <Switch label={t("level.3")} checked={f.step3} onChange={(v) => setF({ ...f, step3: v })} /></div>
            </>}
            </>}
            {me?.tenant?.ai.read && <div className="feature"><div className="text"><strong>{t("new.aiRead")}</strong><span>{t("new.aiReadHint")}</span></div>
              <Switch label={t("new.aiRead")} checked={f.aiRead} onChange={(v) => setF({ ...f, aiRead: v })} /></div>}
            {!review && (f.kind === "blister_foil" || f.kind === "tube") && <div className="feature"><div className="text"><strong>{t("new.mirror")}</strong><span>{t("new.mirrorHint")}</span></div>
              <Switch label={t("new.mirror")} checked={f.mirror} onChange={(v) => setF({ ...f, mirror: v })} /></div>}
            <div className="feature"><div className="text"><strong>{t("engine.rotated")}</strong><span>{t("engine.rotatedHint")}</span></div>
              <select className="select" style={{ maxWidth: 260 }} value={f.rotated} aria-label={t("engine.rotated")} onChange={(e) => setF({ ...f, rotated: e.target.value })}>
                <option value="">{t("new.companyDefault")}</option>
                <option value="ignore">{t("engine.rotated.ignore")}</option>
                <option value="read">{t("engine.rotated.read")}</option>
              </select></div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><h2>{t("new.checks")}</h2></div>
          <div className="panel-body">
            {CHECKS.filter((k) => feat[`check_${k}`] !== false && (k === "colour" ? !review : textOn) && !(review && k === "graphics")).map((k) => (
              <div className="feature" key={k}>
                <div className="text"><strong>{t(`check.${k}` as StringKey)}</strong>
                  <span>{k === "colour"
                    ? (comp?.shade_set_id ? t("new.colourWith", { v: comp.shade_version ?? "", src: t(`shade.source.${comp.shade_source}` as StringKey) })
                      : t("new.colourNone"))
                    : t(`check.${k}.d` as StringKey)}</span></div>
                <Switch label={t(`check.${k}` as StringKey)} checked={checks[k] && (k !== "colour" || !!comp?.shade_set_id)}
                  disabled={k === "colour" && !comp?.shade_set_id} onChange={(v) => setChecks((c) => ({ ...c, [k]: v }))} />
              </div>
            ))}
            {checks.colour && comp?.shade_set_id && !spectroTest && comp.shade_source !== "spectro" && (
              <div className="feature"><div className="text"><strong>{t("new.sampleSource")}</strong><span>{t("new.sampleSourceHint")}</span></div>
                <select className="select" style={{ maxWidth: 260 }} value={f.sample_source} aria-label={t("new.sampleSource")}
                  onChange={(e) => setF({ ...f, sample_source: e.target.value })}>
                  {(["scan", "scan_target", "photo"] as const).map((s2) => <option key={s2} value={s2}>{t(`shade.source.${s2}` as StringKey)}</option>)}
                </select></div>
            )}
          </div>
        </section>
        <div className="row">
          <Button type="submit" variant="primary" icon={<LuPlay />} busy={busy} disabled={(!review && !test) || (!useMaster && !ref) || !f.title || (textOn && !f.eng && !f.ara)}>{t(review ? "review.start" : "new.start")}</Button>
          <Button variant="ghost" onClick={() => history.back()}>{t("common.cancel")}</Button>
        </div>
      </form>
    </>
  );
}
