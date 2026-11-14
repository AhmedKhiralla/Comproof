// Artwork library: products, their packaging components and approved artwork versions.
import { useState } from "react";
import { LuDownload, LuFilePlus2, LuFileSearch, LuLibrary, LuPencil, LuPlus, LuShieldCheck, LuUndo2 } from "react-icons/lu";
import { FileDrop, SignDialog, fileSize, type Meaning, type UploadedFile } from "../components/cp";
import {
  Badge, Button, Empty, LoadError, LoadingRows, Notice, PageHead, SelectField, Sheet, Switch, TextField,
  errorText, fieldErrors, useLoad, useToast,
} from "../components/ui";
import { get, patch, post, qs } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Link, navigate } from "../lib/router";
import { usePerms, useSession } from "../lib/session";
import type { StringKey } from "../lib/strings";
import { ShadeSection, type ShadeSet } from "./Shades";

export const KINDS = ["leaflet", "carton", "label", "sachet", "blister_foil", "tube", "other"] as const;

interface ProductRow {
  id: string; code: string; name: string; name_ar: string | null; generic_name: string | null; strengths: string | null;
  dosage_form: string | null; registration_no: string | null; markets: string[]; active: boolean; gtin: string | null;
  component_count: number; effective_count: number;
}
interface ComponentRow {
  id: string; code: string; kind: string; name: string; languages: string[]; market: string | null; notes: string | null;
  active: boolean; effective: { id: string; version: string; effective_from: string | null } | null;
}
interface ProductDetail extends ProductRow { components: ComponentRow[]; can_edit: boolean; }
interface Signature { id: number; meaning: string; user_name: string; signed_at: string; reason: string | null; statement: string; }
interface Version {
  id: string; version: string; status: "draft" | "effective" | "superseded" | "withdrawn"; effective_from: string | null;
  change_control: string | null; authority_ref: string | null; notes: string | null; file_id: string; filename: string;
  reference_type: "layout" | "text";
  sha256: string; page_count: number | null; doc_kind: string; size_bytes: number; created_at: string; created_by_name: string | null;
  signatures: Signature[];
}
interface ComponentDetail extends ComponentRow { product_id: string; product_code: string; product_name: string; versions: Version[]; can_edit: boolean; shade_sets: ShadeSet[]; }

// ------------------------------------------------------------------ products
function ProductSheet({ product, onClose, onSaved }: { product: ProductRow | null; onClose: () => void; onSaved: (id: string) => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [f, setF] = useState({
    code: product?.code ?? "", name: product?.name ?? "", name_ar: product?.name_ar ?? "", generic_name: product?.generic_name ?? "",
    strengths: product?.strengths ?? "", dosage_form: product?.dosage_form ?? "", registration_no: product?.registration_no ?? "",
    markets: (product?.markets ?? ["EG"]).join(", "), active: product?.active ?? true, gtin: product?.gtin ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (v: string) => setF((s) => ({ ...s, [k]: v }));
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    const body = { name: f.name, name_ar: f.name_ar, generic_name: f.generic_name, strengths: f.strengths, dosage_form: f.dosage_form,
      registration_no: f.registration_no, markets: f.markets.split(/[\s,;]+/).filter(Boolean), gtin: f.gtin.trim() };
    try {
      const r = product ? await patch<ProductRow>(`/api/products/${product.id}`, { ...body, active: f.active })
        : await post<ProductRow>("/api/products", { ...body, code: f.code });
      toast(t("lib.savedToast")); onSaved(r.id); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={product ? t("lib.product.edit") : t("lib.product.new")} lead={product?.code} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{product ? t("common.save") : t("common.create")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      {!product && <TextField label={t("common.code")} value={f.code} dir="ltr" onChange={(v) => set("code")(v.toUpperCase())} error={errs.code} required />}
      <TextField label={t("lib.product.name")} value={f.name} onChange={set("name")} error={errs.name} required />
      <TextField label={t("lib.product.nameAr")} value={f.name_ar} onChange={set("name_ar")} dir="rtl" />
      <TextField label={t("lib.product.generic")} value={f.generic_name} onChange={set("generic_name")} />
      <div className="grid-2">
        <TextField label={t("lib.product.strengths")} value={f.strengths} onChange={set("strengths")} hint={t("lib.product.strengthsHint")} />
        <TextField label={t("lib.product.form")} value={f.dosage_form} onChange={set("dosage_form")} />
      </div>
      <div className="grid-2">
        <TextField label={t("lib.product.regNo")} value={f.registration_no} onChange={set("registration_no")} dir="ltr" />
        <TextField label={t("lib.product.markets")} value={f.markets} onChange={set("markets")} dir="ltr" hint={t("lib.product.marketsHint")} error={errs.markets} />
      </div>
      <TextField label={t("lib.product.gtin")} value={f.gtin} onChange={set("gtin")} dir="ltr" hint={t("lib.product.gtinHint")} error={errs.gtin} />
      {product && <div className="feature" style={{ border: 0, padding: "4px 0" }}>
        <div className="text"><strong>{t("common.active")}</strong><span>{t("lib.product.activeHint")}</span></div>
        <Switch label={t("common.active")} checked={f.active} onChange={(v) => setF((s) => ({ ...s, active: v }))} />
      </div>}
    </Sheet>
  );
}

export function Products() {
  const { t, number } = useI18n();
  const { editLibrary } = usePerms();
  const [q, setQ] = useState("");
  const [showAll, setShowAll] = useState(false);
  const { data, error, loading, reload } = useLoad(() => get<{ items: ProductRow[] }>("/api/products" + qs({ q, active: showAll ? "all" : undefined })), [q, showAll]);
  const [editing, setEditing] = useState(false);
  const items = data?.items ?? [];
  return (
    <>
      <PageHead title={t("lib.title")} lead={t("lib.lead")}
        actions={editLibrary && <Button variant="primary" icon={<LuPlus />} onClick={() => setEditing(true)}>{t("lib.product.new")}</Button>} />
      <div className="panel">
        <div className="panel-head">
          <input className="input" style={{ maxWidth: 320 }} placeholder={t("lib.search")} aria-label={t("lib.search")} value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="spacer" />
          <label className="row small"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />{t("lib.showInactive")}</label>
        </div>
        {error ? <LoadError error={error} onRetry={reload} /> : !loading && items.length === 0 ? (
          <Empty icon={<LuLibrary />} title={t("lib.empty")} body={t("lib.emptyBody")}
            action={editLibrary && <Button variant="primary" icon={<LuPlus />} onClick={() => setEditing(true)}>{t("lib.product.new")}</Button>} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>{t("lib.product.name")}</th><th>{t("lib.product.form")}</th><th>{t("lib.product.markets")}</th>
                <th className="num">{t("lib.components")}</th><th className="num">{t("lib.effective")}</th></tr></thead>
              {loading && !data ? <LoadingRows cols={5} /> : (
                <tbody>
                  {items.map((p) => (
                    <tr key={p.id} className={`clickable ${p.active ? "" : "inactive"}`} tabIndex={0}
                      onClick={() => navigate(`/products/${p.id}`)} onKeyDown={(e) => { if (e.key === "Enter") navigate(`/products/${p.id}`); }}>
                      <td><div className="cell-main">{p.name}{p.name_ar && <span className="subtle" dir="rtl"> · {p.name_ar}</span>}</div>
                        <div className="cell-sub mono-id">{p.code}{p.strengths ? ` · ${p.strengths}` : ""}</div></td>
                      <td>{p.dosage_form ?? "—"}</td>
                      <td dir="ltr" style={{ textAlign: "start" }}>{p.markets.join(", ") || "—"}</td>
                      <td className="num">{number(p.component_count)}</td>
                      <td className="num">{p.effective_count === p.component_count && p.component_count > 0
                        ? <Badge tone="ok">{number(p.effective_count)}</Badge> : number(p.effective_count)}</td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}
      </div>
      {editing && <ProductSheet product={null} onClose={() => setEditing(false)} onSaved={(id) => navigate(`/products/${id}`)} />}
    </>
  );
}

// ------------------------------------------------------------------ one product
function ComponentSheet({ productId, component, onClose, onSaved }: {
  productId: string; component: ComponentRow | null; onClose: () => void; onSaved: (id: string) => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [f, setF] = useState({
    code: component?.code ?? "", kind: component?.kind ?? "leaflet", name: component?.name ?? "",
    en: component ? component.languages.includes("en") : true, fr: component ? component.languages.includes("fr") : false, ar: component ? component.languages.includes("ar") : true,
    market: component?.market ?? "", notes: component?.notes ?? "", active: component?.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    const languages = [f.en && "en", f.fr && "fr", f.ar && "ar"].filter(Boolean);
    try {
      const r = component
        ? await patch<ComponentDetail>(`/api/components/${component.id}`, { name: f.name, languages, market: f.market, notes: f.notes, active: f.active })
        : await post<ComponentDetail>(`/api/products/${productId}/components`, { code: f.code, kind: f.kind, name: f.name, languages, market: f.market || null, notes: f.notes });
      toast(t("lib.savedToast")); onSaved(r.id); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={component ? t("lib.comp.edit") : t("lib.comp.new")} lead={component?.code} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{component ? t("common.save") : t("common.create")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      {!component && <>
        <TextField label={t("common.code")} value={f.code} dir="ltr" onChange={(v) => setF({ ...f, code: v.toUpperCase() })} error={errs.code} hint={t("lib.comp.codeHint")} required />
        <SelectField label={t("lib.comp.kind")} value={f.kind} onChange={(v) => setF({ ...f, kind: v })}
          options={KINDS.map((k) => ({ value: k, label: t(`kind.${k}` as StringKey) }))} />
      </>}
      <TextField label={t("common.name")} value={f.name} onChange={(v) => setF({ ...f, name: v })} error={errs.name} required />
      <fieldset className="field">
        <legend className="label-like">{t("lib.comp.languages")}</legend>
        <div className="row">
          <label className="row small"><input type="checkbox" checked={f.en} onChange={(e) => setF({ ...f, en: e.target.checked })} />{t("common.english")}</label>
          <label className="row small"><input type="checkbox" checked={f.fr} onChange={(e) => setF({ ...f, fr: e.target.checked })} />{t("common.french")}</label>
          <label className="row small"><input type="checkbox" checked={f.ar} onChange={(e) => setF({ ...f, ar: e.target.checked })} />{t("common.arabic")}</label>
        </div>
        {errs.languages && <div className="error">{errs.languages}</div>}
      </fieldset>
      <TextField label={t("lib.comp.market")} value={f.market} onChange={(v) => setF({ ...f, market: v.toUpperCase().slice(0, 2) })} dir="ltr" hint={t("lib.comp.marketHint")} />
      <div className="field">
        <label htmlFor="comp-notes">{t("lib.notes")}</label>
        <textarea id="comp-notes" className="textarea" rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      </div>
      {component && <div className="feature" style={{ border: 0, padding: "4px 0" }}>
        <div className="text"><strong>{t("common.active")}</strong></div>
        <Switch label={t("common.active")} checked={f.active} onChange={(v) => setF({ ...f, active: v })} />
      </div>}
    </Sheet>
  );
}

export function ProductPage({ productId }: { productId: string }) {
  const { t, countryName } = useI18n();
  const { data, error, reload } = useLoad(() => get<ProductDetail>(`/api/products/${productId}`), [productId]);
  const [edit, setEdit] = useState(false);
  const [newComp, setNewComp] = useState(false);
  if (error) return <div className="panel"><LoadError error={error} onRetry={reload} /></div>;
  if (!data) return <div className="panel"><div className="panel-body"><div className="skeleton" style={{ width: "40%" }} /></div></div>;
  return (
    <>
      <nav className="crumbs small"><Link to="/products">{t("lib.title")}</Link> / <span className="mono-id">{data.code}</span></nav>
      <PageHead title={data.name} lead={[data.generic_name, data.strengths, data.dosage_form].filter(Boolean).join(" · ")}
        actions={data.can_edit && <>
          <Button icon={<LuPencil />} onClick={() => setEdit(true)}>{t("common.edit")}</Button>
          <Button variant="primary" icon={<LuPlus />} onClick={() => setNewComp(true)}>{t("lib.comp.new")}</Button>
        </>} />
      <dl className="facts panel panel-body">
        <div><dt>{t("common.code")}</dt><dd className="mono-id">{data.code}</dd></div>
        {data.name_ar && <div><dt>{t("lib.product.nameAr")}</dt><dd dir="rtl">{data.name_ar}</dd></div>}
        <div><dt>{t("lib.product.regNo")}</dt><dd>{data.registration_no ?? "—"}</dd></div>
        <div><dt>{t("lib.product.gtin")}</dt><dd className="mono-id">{data.gtin ?? "—"}</dd></div>
        <div><dt>{t("lib.product.markets")}</dt><dd>{data.markets.map((m) => countryName(m)).join(", ") || "—"}</dd></div>
        <div><dt>{t("common.status")}</dt><dd>{data.active ? t("common.active") : t("common.inactive")}</dd></div>
      </dl>
      <section className="panel" aria-labelledby="comp-h">
        <div className="panel-head"><h2 id="comp-h">{t("lib.components")}</h2></div>
        {data.components.length === 0 ? (
          <Empty icon={<LuFilePlus2 />} title={t("lib.comp.empty")} body={t("lib.comp.emptyBody")}
            action={data.can_edit && <Button variant="primary" icon={<LuPlus />} onClick={() => setNewComp(true)}>{t("lib.comp.new")}</Button>} />
        ) : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>{t("common.name")}</th><th>{t("lib.comp.kind")}</th><th>{t("lib.comp.languages")}</th><th>{t("lib.effectiveMaster")}</th></tr></thead>
            <tbody>
              {data.components.map((c) => (
                <tr key={c.id} className={`clickable ${c.active ? "" : "inactive"}`} tabIndex={0}
                  onClick={() => navigate(`/components/${c.id}`)} onKeyDown={(e) => { if (e.key === "Enter") navigate(`/components/${c.id}`); }}>
                  <td><div className="cell-main">{c.name}</div><div className="cell-sub mono-id">{c.code}</div></td>
                  <td>{t(`kind.${c.kind}` as StringKey)}</td>
                  <td>{c.languages.map((l) => l.toUpperCase()).join(" + ")}</td>
                  <td>{c.effective ? <Badge tone="ok" dot>{t("lib.version", { v: c.effective.version })}</Badge> : <Badge tone="warn">{t("lib.noMaster")}</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>
      {edit && <ProductSheet product={data} onClose={() => setEdit(false)} onSaved={() => reload()} />}
      {newComp && <ComponentSheet productId={data.id} component={null} onClose={() => setNewComp(false)} onSaved={(id) => navigate(`/components/${id}`)} />}
    </>
  );
}

// ------------------------------------------------------------------ one component and its artwork versions
function VersionSheet({ component, onClose, onSaved }: { component: ComponentDetail; onClose: () => void; onSaved: (c: ComponentDetail) => void }) {
  const { t } = useI18n();
  const [file, setFile] = useState<UploadedFile | null>(null);
  const next = String(component.versions.length + 1).padStart(2, "0");
  const [f, setF] = useState({ version: next, effective_from: "", change_control: "", authority_ref: "", notes: "" });
  // what the approved file is a reference for; Word defaults to the approved continuous text
  const [refType, setRefType] = useState<"" | "layout" | "text">("");
  const refTypeShown = refType || (file?.doc_kind === "docx" ? "text" : "layout");
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      onSaved(await post<ComponentDetail>(`/api/components/${component.id}/artwork`, {
        ...f, effective_from: f.effective_from || null, file_id: file?.id ?? "", reference_type: refTypeShown,
      }));
      onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={t("lib.ver.new")} lead={t("lib.ver.newLead")} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy} disabled={!file}>{t("lib.ver.register")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <FileDrop label={t("lib.ver.file")} value={file} onChange={setFile} error={errs.file_id} hint={t("lib.ver.fileHint")} />
      <SelectField label={t("ref.type")} value={refTypeShown} onChange={(v) => setRefType(v as "layout" | "text")}
        error={errs.reference_type} hint={t(`ref.type.${refTypeShown}.hint` as StringKey)}
        options={(["layout", "text"] as const).map((k) => ({ value: k, label: t(`ref.type.${k}` as StringKey) }))} />
      <div className="grid-2">
        <TextField label={t("lib.ver.version")} value={f.version} dir="ltr" onChange={(v) => setF({ ...f, version: v })} error={errs.version} />
        <TextField label={t("lib.ver.effectiveFrom")} type="date" value={f.effective_from} onChange={(v) => setF({ ...f, effective_from: v })} />
      </div>
      <div className="grid-2">
        <TextField label={t("lib.ver.changeControl")} value={f.change_control} dir="ltr" onChange={(v) => setF({ ...f, change_control: v })} />
        <TextField label={t("lib.ver.authority")} value={f.authority_ref} dir="ltr" onChange={(v) => setF({ ...f, authority_ref: v })} hint={t("lib.ver.authorityHint")} />
      </div>
      <div className="field">
        <label htmlFor="ver-notes">{t("lib.notes")}</label>
        <textarea id="ver-notes" className="textarea" rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      </div>
      <Notice>{t("lib.ver.signNote")}</Notice>
    </Sheet>
  );
}

export function ComponentPage({ componentId }: { componentId: string }) {
  const { t, dateTime, date } = useI18n();
  const { has, startAt, siteId } = usePerms();
  const { me } = useSession();
  const toast = useToast();
  const { data, error, reload, setData } = useLoad(() => get<ComponentDetail>(`/api/components/${componentId}`), [componentId]);
  const [edit, setEdit] = useState(false);
  const [addVer, setAddVer] = useState(false);
  const [signing, setSigning] = useState<{ v: Version; meaning: Meaning } | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  if (error) return <div className="panel"><LoadError error={error} onRetry={reload} /></div>;
  if (!data) return <div className="panel"><div className="panel-body"><div className="skeleton" style={{ width: "40%" }} /></div></div>;
  const approver = has("approver");
  const tone = { draft: "brand", effective: "ok", superseded: undefined, withdrawn: "danger" } as const;
  const reviewSite = siteId && startAt(siteId) ? siteId : (me?.sites ?? []).find((s) => startAt(s.id))?.id ?? null;
  const review = async (v: Version) => {
    if (!reviewSite) return;
    setReviewing(v.id);
    try {
      const r = await post<{ id: string }>("/api/comparisons", {
        site_id: reviewSite, purpose: "master_review", component_id: data.id, artwork_version_id: v.id,
        title: `${data.product_code} ${data.code} v${v.version} · ${t("review.titleSuffix")}`,
        languages: data.languages.map((l) => (l === "ar" ? "ara" : l === "fr" ? "fra" : "eng")),
      });
      navigate(`/comparisons/${r.id}`);
    } catch (e) { toast(errorText(e, t)); setReviewing(null); }
  };
  return (
    <>
      <nav className="crumbs small"><Link to="/products">{t("lib.title")}</Link> / <Link to={`/products/${data.product_id}`}>{data.product_code}</Link> / <span className="mono-id">{data.code}</span></nav>
      <PageHead title={data.name} lead={`${t(`kind.${data.kind}` as StringKey)} · ${data.languages.map((l) => l.toUpperCase()).join(" + ")}${data.market ? ` · ${data.market}` : ""}`}
        actions={<>
          {data.can_edit && <Button icon={<LuPencil />} onClick={() => setEdit(true)}>{t("common.edit")}</Button>}
          {data.can_edit && <Button icon={<LuPlus />} onClick={() => setAddVer(true)}>{t("lib.ver.new")}</Button>}
          {data.effective && <Button variant="primary" icon={<LuFilePlus2 />} onClick={() => navigate(`/comparisons/new?component=${data.id}`)}>{t("lib.compareAgainst")}</Button>}
        </>} />
      <section className="panel" aria-labelledby="ver-h">
        <div className="panel-head"><h2 id="ver-h">{t("lib.versions")}</h2><span className="spacer" />
          {!approver && data.versions.some((v) => v.status === "draft") && <span className="small muted">{t("lib.ver.needApprover")}</span>}</div>
        {data.versions.length === 0 ? (
          <Empty icon={<LuShieldCheck />} title={t("lib.ver.empty")} body={t("lib.ver.emptyBody")}
            action={data.can_edit && <Button variant="primary" icon={<LuPlus />} onClick={() => setAddVer(true)}>{t("lib.ver.new")}</Button>} />
        ) : (
          <ul className="versions">
            {data.versions.map((v) => (
              <li key={v.id} className={`version st-${v.status}`}>
                <div className="v-head">
                  <strong className="mono-id">v{v.version}</strong>
                  <Badge tone={tone[v.status]} dot>{t(`ver.${v.status}` as StringKey)}</Badge>
                  <Badge title={t(`ref.type.${v.reference_type}.hint` as StringKey)}>{t(`ref.type.${v.reference_type}` as StringKey)}</Badge>
                  {v.effective_from && <span className="small muted">{t("lib.ver.from", { d: date(v.effective_from) })}</span>}
                  <span className="spacer" />
                  <a className="btn sm ghost" href={`/api/files/${v.file_id}/content`}><LuDownload aria-hidden />{t("lib.ver.download")}</a>
                  {reviewSite && (v.status === "draft" || v.status === "effective") &&
                    <Button size="sm" icon={<LuFileSearch />} busy={reviewing === v.id} onClick={() => review(v)} title={t("review.buttonHint")}>{t("review.button")}</Button>}
                  {approver && v.status === "draft" && <Button size="sm" variant="primary" icon={<LuShieldCheck />} onClick={() => setSigning({ v, meaning: "approved_master" })}>{t("lib.ver.approve")}</Button>}
                  {approver && (v.status === "draft" || v.status === "effective") && <Button size="sm" variant="ghost" icon={<LuUndo2 />} onClick={() => setSigning({ v, meaning: "withdrawn" })}>{t("lib.ver.withdraw")}</Button>}
                </div>
                <div className="v-body small">
                  <span><strong>{v.filename}</strong> · {v.page_count ?? "–"} {t("cp.pages")} · {t(`doc.${v.doc_kind}` as StringKey)} · {fileSize(v.size_bytes)}</span>
                  <span className="mono-id subtle" title={v.sha256}>SHA-256 {v.sha256}</span>
                  {(v.change_control || v.authority_ref) && <span>{[v.change_control && `${t("lib.ver.changeControl")}: ${v.change_control}`, v.authority_ref && `${t("lib.ver.authority")}: ${v.authority_ref}`].filter(Boolean).join(" · ")}</span>}
                  {v.notes && <span className="muted">{v.notes}</span>}
                  <span className="muted">{t("lib.ver.registered", { who: v.created_by_name ?? "—", when: dateTime(v.created_at) })}</span>
                </div>
                {v.signatures.length > 0 && (
                  <ul className="sig-list">
                    {v.signatures.map((s) => (
                      <li key={s.id}><LuShieldCheck aria-hidden /><span><strong>{s.user_name}</strong> · {t(`meaning.${s.meaning}` as StringKey)} · {dateTime(s.signed_at)}{s.reason ? ` · “${s.reason}”` : ""}</span></li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <ShadeSection component={data} onChanged={(c) => setData(c)} />
      {edit && <ComponentSheet productId={data.product_id} component={data} onClose={() => setEdit(false)} onSaved={() => reload()} />}
      {addVer && <VersionSheet component={data} onClose={() => setAddVer(false)} onSaved={(c) => { setData(c); toast(t("lib.ver.registered.toast")); }} />}
      {signing && <SignDialog meaning={signing.meaning} label={`${data.code} v${signing.v.version} · ${signing.v.filename}`}
        needsReason={signing.meaning === "withdrawn"} onClose={() => setSigning(null)}
        onSign={async (b) => { setData(await post<ComponentDetail>(`/api/artwork/${signing.v.id}/sign`, b)); toast(t("sign.done")); }} />}
    </>
  );
}
