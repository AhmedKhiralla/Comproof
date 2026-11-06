// One comparison: live progress while it runs, then the interactive report with decisions and signatures.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LuChevronLeft, LuChevronRight, LuDownload, LuFileSpreadsheet, LuFileText, LuGlobe, LuLockKeyhole, LuMinus, LuPlus,
  LuRotateCcw, LuShieldCheck, LuShieldX, LuX,
} from "react-icons/lu";
import { SignDialog, StatusBadge, fileSize, type CompStatus, type Meaning } from "../components/cp";
import { Badge, Button, Empty, LoadError, Menu, MenuItem, Notice, errorText, useLoad, useToast } from "../components/ui";
import { get, post } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Link } from "../lib/router";
import type { StringKey } from "../lib/strings";

type Sev = "critical" | "major" | "minor" | "info";
type Loc = [number, number[]];
interface Finding {
  id: string; step: 1 | 2 | 3; lang: "eng" | "ara"; kind: string; severity: Sev; title: string; ref_text: string; des_text: string;
  ref_loc: Loc[]; des_loc: Loc[]; ref_hl: Loc[]; des_hl: Loc[]; ref_anchor: Loc[]; des_anchor: Loc[];
  ai: { verdict?: string; approved_reads?: string; design_reads?: string; explanation?: string; model?: string } | null;
  note: string; section: string; category: string; segments: [string, string][]; context_before: string; context_after: string;
  where_ref: string; where_des: string; explanation: string; action: string; ref_crop: number[]; des_crop: number[]; read_conf?: number;
}
interface Result {
  engine_version: string; kind: string; findings: Finding[];
  exclusions: { doc: string; page: number; reason: string; text: string }[];
  approved: { name: string; pages: number; sizes: [number, number][] }; design: { name: string; pages: number; sizes: [number, number][] };
  ai: { vision_model: string | null; science_model: string | null; reading_model: string | null; notes: string[] };
  reading_order: Record<string, { similarity: number; approved_words: number; design_words: number }>;
  screenshots: Record<string, string>; seconds: number;
}
interface Decision { decision: "confirmed" | "not_deviation"; comment: string | null; user_name: string; decided_at: string; }
interface Sig { id: number; meaning: string; statement: string; reason: string | null; user_id: string; user_name: string; signed_at: string; record_hash: string; }
interface Detail {
  id: string; number: string; title: string; purpose: string; status: CompStatus; progress: string | null; error: string | null;
  site_code: string; component_code: string | null; component_kind: string | null; product_code: string | null; product_name: string | null;
  component_id: string | null; supplier: string | null; reference_no: string | null; created_at: string; finished_at: string | null;
  created_by_name: string; result_sha256: string | null; engine_version: string | null;
  files: { reference: { id: string; filename: string; sha256: string; page_count: number; doc_kind: string; size_bytes: number };
           test: { id: string; filename: string; sha256: string; page_count: number; doc_kind: string; size_bytes: number } };
  artwork?: { version: string; status: string };
  result: Result | null; decisions: Record<string, Decision>; decision_history: (Decision & { id: number; finding_id: string })[];
  signatures: Sig[]; approval_blockers: string[];
  permissions: { decide: boolean; sign_reviewed: boolean; sign_approved: boolean; sign_rejected: boolean; cancel: boolean; retry: boolean };
}

const SEVS: Sev[] = ["critical", "major", "minor", "info"];
const isAr = (s: string) => /[؀-ۿ]/.test(s || "");

// ------------------------------------------------------------------ running / failed
function Progress({ d, onChange }: { d: Detail; onChange: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const failed = d.status === "failed" || d.status === "cancelled";
  return (
    <section className="panel run-panel">
      <div className="panel-body stack">
        {failed ? <Notice tone="danger">{d.status === "cancelled" ? t("run.cancelled") : t("run.failed", { msg: d.progress ?? "" })}</Notice> : <>
          <div className="run-line"><span className="pulse" aria-hidden /><strong>{d.progress || t("run.waiting")}</strong></div>
          <div className="progressbar" aria-hidden><i /></div>
          <p className="small muted">{t("run.lead")}</p>
        </>}
        <div className="row">
          {d.permissions.cancel && <Button onClick={async () => { await post(`/api/comparisons/${d.id}/cancel`); toast(t("run.cancelledToast")); onChange(); }}>{t("run.cancel")}</Button>}
          {d.permissions.retry && <Button variant="primary" icon={<LuRotateCcw />} onClick={async () => { await post(`/api/comparisons/${d.id}/retry`); onChange(); }}>{t("run.retry")}</Button>}
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ the report
function DiffText({ f }: { f: Finding }) {
  const segs = f.segments?.length ? f.segments : ([["del", f.ref_text], ["ins", f.des_text]].filter((x) => x[1]) as [string, string][]);
  return (
    <div className={`rep-diff ${f.lang === "ara" ? "ar" : ""}`} dir={f.lang === "ara" ? "rtl" : "ltr"}>
      {f.context_before && <span className="c">…{f.context_before} </span>}
      {segs.map(([k, x], i) => k === "eq" ? <span key={i}>{x} </span> : k === "del" ? <del key={i}>{x}</del> : <ins key={i}>{x}</ins>)}
      {f.kind === "missing" && <span className="caret" aria-label="missing text belongs here"> ‸ </span>}
      {f.context_after && <span className="c"> {f.context_after}…</span>}
    </div>
  );
}

function Shot({ cid, f, side, onOpen }: { cid: string; f: Finding; side: "approved" | "design"; onOpen: () => void }) {
  const { t } = useI18n();
  const name = `${f.id}_${side}.jpg`;
  const where = side === "approved" ? f.where_ref : f.where_des;
  const ocr = side === "approved" ? f.ref_text : f.des_text;
  const crop = side === "approved" ? f.ref_crop : f.des_crop;
  return (
    <div className="rep-shot">
      <div className={`lab ${side}`}><b>{t(side === "approved" ? "rep.approved" : "rep.test")}</b><span>{where}</span></div>
      {crop?.length ? (
        <button type="button" onClick={onOpen} aria-label={t("rep.openPages")}>
          <img loading="lazy" alt="" src={`/api/comparisons/${cid}/images/${name}`} />
        </button>
      ) : <div className="none">{t("rep.noShot")}</div>}
      {ocr && <div className={`ocr ${isAr(ocr) ? "ar" : ""}`} dir="auto">{t("rep.read")}: {ocr.slice(0, 300)}</div>}
    </div>
  );
}

function DecisionBar({ f, d, canDecide, onDecided }: { f: Finding; d?: Decision; canDecide: boolean; onDecided: (fid: string, x: Decision) => void }) {
  const { t, dateTime } = useI18n();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const cid = (window.location.pathname.split("/")[2]);
  const send = async (decision: "confirmed" | "not_deviation") => {
    setBusy(decision); setErr(null);
    try {
      const r = await post<Decision & { finding_id: string }>(`/api/comparisons/${cid}/decisions`, { finding_id: f.id, decision, comment });
      onDecided(f.id, r); setComment("");
    } catch (e) { setErr(errorText(e, t)); } finally { setBusy(null); }
  };
  return (
    <div className="rep-decide">
      {d && <div className={`hist ${d.decision}`}>{t(`dec.${d.decision}` as StringKey)} · {d.user_name} · {dateTime(d.decided_at)}{d.comment ? ` · “${d.comment}”` : ""}</div>}
      {canDecide && (
        <div className="row wrap">
          <input className="input grow" placeholder={t("rep.comment")} aria-label={t("rep.comment")} value={comment} onChange={(e) => setComment(e.target.value)} />
          <Button size="sm" variant="danger" busy={busy === "confirmed"} onClick={() => send("confirmed")}>{t("rep.confirm")}</Button>
          <Button size="sm" busy={busy === "not_deviation"} disabled={comment.trim().length < 3} onClick={() => send("not_deviation")}
            title={comment.trim().length < 3 ? t("rep.reasonNeeded") : undefined}>{t("rep.notDeviation")}</Button>
        </div>
      )}
      {err && <div className="error">{err}</div>}
    </div>
  );
}

function Card({ cid, f, open, active, d, canDecide, onToggle, onView, onDecided }: {
  cid: string; f: Finding; open: boolean; active: boolean; d?: Decision; canDecide: boolean;
  onToggle: () => void; onView: () => void; onDecided: (fid: string, x: Decision) => void;
}) {
  const { t } = useI18n();
  const state = d?.decision ?? "pending";
  const peek = (f.segments || []).filter((s) => s[0] !== "eq").map((s) => (s[0] === "del" ? "− " : "+ ") + s[1]).join("   ") || f.ref_text || f.des_text;
  const two = f.step !== 1;
  return (
    <article className={`rep-card sev-${f.severity} ${open ? "open" : ""} ${active ? "active" : ""}`} id={`f-${f.id}`}>
      <button type="button" className="rep-row" aria-expanded={open} onClick={onToggle}>
        <span className="sevtag">{t(`sev.${f.severity}` as StringKey)}</span>
        <span className="ttl" dir="auto">{f.title}</span>
        <span className={`state ${state}`}>{t(`dec.${state}` as StringKey)}</span>
        <span className="meta"><span className="mono-id">{f.id}</span><span dir="auto">{f.section || "—"}</span><span>{f.category}</span>
          <span>{f.lang === "ara" ? "العربية" : "English"}</span>
          {f.read_conf !== undefined && f.read_conf < 75 && <span className="lowconf">{t("rep.lowConf", { n: f.read_conf })}</span>}</span>
        {!open && <span className={`peek ${isAr(peek) ? "ar" : ""}`} dir="auto">{peek}</span>}
      </button>
      {open && (
        <div className="rep-body">
          {(f.segments?.length || f.ref_text) ? (two ? <DiffText f={f} /> : <div className={`rep-diff ${isAr(f.ref_text) ? "ar" : ""}`} dir="auto">{f.ref_text}</div>) : null}
          {two && <div className="rep-key"><span><del>{t("rep.keyDel")}</del></span><span><ins>{t("rep.keyIns")}</ins></span>{f.kind === "missing" && <span>‸ {t("rep.keyCaret")}</span>}</div>}
          <div className={`rep-shots ${two ? "" : "one"}`}>
            <Shot cid={cid} f={f} side="approved" onOpen={onView} />
            {two && <Shot cid={cid} f={f} side="design" onOpen={onView} />}
          </div>
          <div className="rep-explain">
            <div><h4>{t("rep.what")}</h4><p dir="auto">{f.explanation || f.title}</p></div>
            <div><h4>{t("rep.action")}</h4><p>{f.action}</p></div>
          </div>
          {f.note && f.step === 2 && <div className="rep-ai">{f.note}</div>}
          {f.ai?.verdict && <div className="rep-ai"><b>{t("rep.ai")} · {t(`ai.${f.ai.verdict}` as StringKey)}</b>
            {f.ai.approved_reads ? ` — ${t("rep.aiReads", { a: f.ai.approved_reads, d: f.ai.design_reads ?? "" })}` : ""} {f.ai.explanation}</div>}
          <DecisionBar f={f} d={d} canDecide={canDecide} onDecided={onDecided} />
        </div>
      )}
    </article>
  );
}

function Viewer({ cid, res, f, onClose, onStep }: { cid: string; res: Result; f: Finding; onClose: () => void; onStep: (dir: number) => void }) {
  const { t } = useI18n();
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" || e.key === "j") onStep(1);
      if (e.key === "ArrowLeft" || e.key === "k") onStep(-1);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, onStep]);
  const pane = (doc: "approved" | "design") => {
    const loc = doc === "approved" ? [...f.ref_loc, ...f.ref_anchor] : [...f.des_loc, ...f.des_anchor];
    const hl = doc === "approved" ? f.ref_hl : f.des_hl;
    if (!loc.length) return <div className="vpane"><div className={`cap ${doc}`}>{t(doc === "approved" ? "rep.approved" : "rep.test")}</div><div className="none">{t("rep.noShot")}</div></div>;
    const p = loc[0][0];
    const [W, H] = res[doc].sizes[p];
    const fb = (hl.find((x) => x[0] === p) ?? loc.find((x) => x[0] === p))![1];
    const lineW = Math.max(...loc.filter((x) => x[0] === p).map((x) => x[1][2] - x[1][0]), fb[2] - fb[0], 1);
    const z = Math.min(8, Math.max(1, (0.8 * W) / lineW)) * zoom;
    const boxes = [...loc.filter((x) => x[0] === p).map((x) => ({ b: x[1], w: false })), ...hl.filter((x) => x[0] === p).map((x) => ({ b: x[1], w: true }))];
    return <ViewerPane key={`${f.id}-${doc}-${zoom}`} doc={doc} cid={cid} page={p} W={W} H={H} z={z} boxes={boxes}
      where={doc === "approved" ? f.where_ref : f.where_des} />;
  };
  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label={t("rep.viewer")}>
      <div className="vbar">
        <strong className="grow" dir="auto">{f.id} · {f.title}</strong>
        <Button size="sm" iconOnly icon={<LuChevronLeft />} aria-label={t("common.previous")} onClick={() => onStep(-1)} />
        <Button size="sm" iconOnly icon={<LuChevronRight />} aria-label={t("common.next")} onClick={() => onStep(1)} />
        <Button size="sm" iconOnly icon={<LuMinus />} aria-label={t("rep.zoomOut")} onClick={() => setZoom((v) => Math.max(0.6, v / 1.35))} />
        <Button size="sm" iconOnly icon={<LuPlus />} aria-label={t("rep.zoomIn")} onClick={() => setZoom((v) => Math.min(4, v * 1.35))} />
        <Button size="sm" variant="primary" icon={<LuX />} onClick={onClose}>{t("common.close")}</Button>
      </div>
      <div className={`vpanes ${f.step === 1 ? "one" : ""}`}>{pane("approved")}{f.step !== 1 && pane("design")}</div>
    </div>
  );
}

function ViewerPane({ doc, cid, page, W, H, z, boxes, where }: {
  doc: "approved" | "design"; cid: string; page: number; W: number; H: number; z: number; boxes: { b: number[]; w: boolean }[]; where: string;
}) {
  const { t } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  const centre = useCallback(() => {
    const el = ref.current;
    const bx = el?.querySelector<HTMLElement>(".vbox.word") ?? el?.querySelector<HTMLElement>(".vbox");
    if (!el || !bx) return;
    const r = bx.getBoundingClientRect(), pr = el.getBoundingClientRect();
    el.scrollBy({ top: r.top - pr.top - el.clientHeight / 3, left: r.left - pr.left - (el.clientWidth - r.width) / 2 });
  }, []);
  return (
    <div className="vpane" ref={ref}>
      <div className={`cap ${doc}`}>{t(doc === "approved" ? "rep.approved" : "rep.test")} · {where}</div>
      <div className="vpage" style={{ width: `calc(${z * 100}% - 24px)` }}>
        <img src={`/api/comparisons/${cid}/images/${doc}_p${page}.jpg`} alt="" onLoad={() => requestAnimationFrame(centre)} />
        {boxes.map(({ b, w }, i) => (
          <div key={i} className={`vbox ${w ? "word" : ""} ${doc}`}
            style={{ left: `${(b[0] / W) * 100}%`, top: `${(b[1] / H) * 100}%`, width: `${((b[2] - b[0]) / W) * 100}%`, height: `${((b[3] - b[1]) / H) * 100}%` }} />
        ))}
      </div>
    </div>
  );
}

function LeafletMap({ cid, res, items, active, onPick }: { cid: string; res: Result; items: Finding[]; active: string | null; onPick: (id: string) => void }) {
  const { t } = useI18n();
  const [doc, setDoc] = useState<"design" | "approved">("design");
  const sizes = res[doc].sizes;
  return (
    <aside className="rep-map" aria-label={t("rep.map")}>
      <h3>{t("rep.map")}</h3>
      <div className="seg" role="group">
        <button type="button" aria-pressed={doc === "design"} onClick={() => setDoc("design")}>{t("rep.test")}</button>
        <button type="button" aria-pressed={doc === "approved"} onClick={() => setDoc("approved")}>{t("rep.approved")}</button>
      </div>
      <div className="pages">
        {sizes.map(([W, H], p) => (
          <div className="pg" key={p}>
            <img loading="lazy" src={`/api/comparisons/${cid}/images/${doc}_p${p}.jpg`} alt={`${doc} ${p + 1}`} />
            <span className="no">{p + 1}</span>
            {items.map((f) => {
              const loc = doc === "design" ? (f.des_hl.length ? f.des_hl : f.des_loc.length ? f.des_loc : f.des_anchor)
                : (f.ref_hl.length ? f.ref_hl : f.ref_loc.length ? f.ref_loc : f.ref_anchor);
              if (!loc?.length || loc[0][0] !== p) return null;
              const b = loc[0][1];
              return <button key={f.id} type="button" className={`pin sev-${f.severity} ${active === f.id ? "active" : ""}`}
                title={`${f.id} · ${f.title}`} aria-label={`${f.id} · ${f.title}`} onClick={() => onPick(f.id)}
                style={{ left: `${((b[0] + b[2]) / 2 / W) * 100}%`, top: `${((b[1] + b[3]) / 2 / H) * 100}%` }} />;
            })}
          </div>
        ))}
      </div>
      <p className="small muted">{t("rep.mapHint")}</p>
    </aside>
  );
}

function Report({ d, setD }: { d: Detail; setD: (d: Detail) => void }) {
  const { t, dateTime } = useI18n();
  const toast = useToast();
  const res = d.result!;
  const F = res.findings;
  const [step, setStep] = useState<1 | 2 | 3 | "x">(() => (F.some((f) => f.step === 2 && f.severity !== "info") ? 2 : 1));
  const [sec, setSec] = useState("");
  const [lang, setLang] = useState<"" | "eng" | "ara">("");
  const [pending, setPending] = useState(false);
  const [noise, setNoise] = useState(false);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [allOpen, setAllOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const [signing, setSigning] = useState<Meaning | null>(null);
  const dec = (f: Finding): Decision["decision"] | "pending" => d.decisions[f.id]?.decision ?? "pending";
  const base = useMemo(() => F.filter((f) => f.step === step && (noise || f.severity !== "info") && (!lang || f.lang === lang)), [F, step, noise, lang]);
  const items = useMemo(() => {
    const s = q.toLowerCase();
    return base.filter((f) => (!sec || (f.section || "—") === sec) && (!pending || dec(f) === "pending")
      && (!s || [f.id, f.title, f.section, f.ref_text, f.des_text, f.category].join(" ").toLowerCase().includes(s)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, sec, pending, q, d.decisions]);
  useEffect(() => { if (!active && items[0]) setActive(items[0].id); }, [items, active]);

  const counts = SEVS.map((s) => F.filter((f) => f.severity === s && dec(f) !== "not_deviation").length);
  const open_ = F.filter((f) => f.severity !== "info" && dec(f) !== "not_deviation");
  const crit = open_.filter((f) => f.severity === "critical").length, maj = open_.filter((f) => f.severity === "major").length;
  const undecided = F.filter((f) => f.severity !== "info" && dec(f) === "pending").length;
  const closed = d.status === "approved" || d.status === "rejected";
  const verdict = d.status === "approved" ? { cls: "ok", v: t("verdict.approved") }
    : d.status === "rejected" ? { cls: "bad", v: t("verdict.rejected") }
    : crit || maj ? { cls: undecided ? "wip" : "bad", v: undecided ? t("verdict.inReview") : t("verdict.notReady") }
    : { cls: undecided ? "wip" : "ok", v: undecided ? t("verdict.inReview") : t("verdict.ready") };

  const sections = useMemo(() => {
    const by = new Map<string, Finding[]>();
    base.forEach((f) => { const k = f.section || "—"; by.set(k, [...(by.get(k) ?? []), f]); });
    const key = (s: string) => { const m = s.match(/^(?:PIL )?(\d+(?:\.\d+)?)/); return (s.startsWith("PIL") ? "2" : "1") + (m ? m[1].padStart(5, "0") : "99999") + s; };
    return [...by.entries()].sort((a, b) => key(a[0]).localeCompare(key(b[0]), undefined, { numeric: true }));
  }, [base]);
  const maxSec = Math.max(1, ...sections.map(([, v]) => v.length));

  const pick = (id: string) => {
    setActive(id);
    setOpen((o) => new Set(o).add(id));
    requestAnimationFrame(() => document.getElementById(`f-${id}`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  };
  const stepBy = useCallback((dir: number) => {
    const i = items.findIndex((f) => f.id === (viewing ?? active));
    const n = items[i + dir];
    if (!n) return;
    if (viewing) setViewing(n.id); else pick(n.id);
    setActive(n.id);
  }, [items, viewing, active]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).matches("input,textarea,select") || viewing || signing) return;
      if (e.key === "/") { e.preventDefault(); document.getElementById("rep-q")?.focus(); }
      else if (e.key === "j") stepBy(1);
      else if (e.key === "k") stepBy(-1);
      else if (e.key === "Enter" && active) setViewing(active);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [stepBy, active, viewing, signing]);

  const onDecided = (fid: string, x: Decision) => setD({ ...d, decisions: { ...d.decisions, [fid]: x } });
  const viewF = viewing ? F.find((f) => f.id === viewing) : null;
  const sign = async (b: { meaning: Meaning; email: string; password: string; reason?: string }) => {
    setD(await post<Detail>(`/api/comparisons/${d.id}/sign`, b));
    toast(t("sign.done"));
  };
  const stepLabel = (s: 1 | 2 | 3) => t(`level.${s}` as StringKey);

  return (
    <>
      <header className="rep-head">
        <div className="grow">
          <div className="files small muted">
            <span className="mono-id">{d.number}</span>
            {d.product_name && <span>{d.product_code} · {d.product_name}</span>}
            {d.component_kind && <span>{t(`kind.${d.component_kind}` as StringKey)}</span>}
            <span>{t(`purpose.${d.purpose}` as StringKey)}</span>
            {d.supplier && <span>{d.supplier}</span>}
            {d.reference_no && <span>{d.reference_no}</span>}
          </div>
          <h1 className="rep-title" dir="auto">{d.title}</h1>
          <div className="files">
            <span><b className="ref">{t("rep.approved")}</b> {d.files.reference.filename}{d.artwork ? ` · v${d.artwork.version}` : ""}
              <span className="subtle"> · {d.files.reference.page_count} {t("cp.pages")} · {fileSize(d.files.reference.size_bytes)}</span></span>
            <span><b className="tst">{t("rep.test")}</b> {d.files.test.filename}
              <span className="subtle"> · {d.files.test.page_count} {t("cp.pages")} · {fileSize(d.files.test.size_bytes)}</span></span>
          </div>
        </div>
        <div className={`verdict ${verdict.cls}`}>
          <div className="v">{verdict.v}</div>
          <div className="why">{closed ? t("verdict.closedOn", { when: dateTime(d.signatures[d.signatures.length - 1]?.signed_at) })
            : t("verdict.why", { c: crit, m: maj, p: undecided })}</div>
        </div>
      </header>

      <div className="rep-actions row wrap">
        <StatusBadge status={d.status} />
        <span className="spacer" />
        <Menu trigger={(p) => <Button icon={<LuDownload />} {...p}>{t("rep.export")}</Button>}>
          {(close) => <>
            <MenuItem icon={<LuFileText />} onClick={() => { close(); window.location.href = `/api/comparisons/${d.id}/export.pdf`; }}>{t("rep.exportPdf")}</MenuItem>
            <MenuItem icon={<LuFileSpreadsheet />} onClick={() => { close(); window.location.href = `/api/comparisons/${d.id}/export.xlsx`; }}>{t("rep.exportXlsx")}</MenuItem>
            <MenuItem icon={<LuGlobe />} onClick={() => { close(); window.location.href = `/api/comparisons/${d.id}/export.html`; }}>{t("rep.exportHtml")}</MenuItem>
          </>}
        </Menu>
        {d.permissions.sign_reviewed && <Button icon={<LuLockKeyhole />} onClick={() => setSigning("reviewed")}>{t("sign.do.reviewed")}</Button>}
        {d.permissions.sign_rejected && <Button variant="danger" icon={<LuShieldX />} onClick={() => setSigning("rejected")}>{t("sign.do.rejected")}</Button>}
        {d.permissions.sign_approved && <Button variant="primary" icon={<LuShieldCheck />} onClick={() => setSigning("approved")}>{t("sign.do.approved")}</Button>}
      </div>

      <section className="rep-ledger" aria-label={t("rep.severity")}>
        <div className="track">
          {SEVS.map((s, i) => counts[i] ? <i key={s} className={`sev-${s}`} style={{ width: `${(counts[i] / Math.max(1, counts.reduce((a, b) => a + b, 0))) * 100}%` }} title={`${t(`sev.${s}`)}: ${counts[i]}`} /> : null)}
        </div>
        <div className="legend">
          {SEVS.map((s, i) => <span key={s} className={`sev-${s}`}><b>{counts[i]}</b>{t(`sev.${s}`)}</span>)}
          <span className="ok"><b>{F.filter((f) => dec(f) === "not_deviation").length}</b>{t("dec.not_deviation")}</span>
        </div>
      </section>

      {res.ai.notes?.length > 0 && <Notice tone="warn">{res.ai.notes.join(" ")}</Notice>}

      <div className="rep-grid">
        <aside className="rep-rail">
          <nav className="rep-steps" aria-label={t("rep.levels")}>
            {([1, 2, 3] as const).map((s) => (
              <button key={s} type="button" className={step === s ? "on" : ""} aria-current={step === s}
                onClick={() => { setStep(s); setSec(""); setActive(null); }}>
                {stepLabel(s)}<span className="n">{F.filter((f) => f.step === s && f.severity !== "info").length}</span>
                <small>{t(`level.${s}.short` as StringKey)}</small>
              </button>
            ))}
            <button type="button" className={step === "x" ? "on" : ""} onClick={() => setStep("x")}>{t("rep.excluded")}<span className="n">{res.exclusions.length}</span></button>
          </nav>
          {step !== "x" && <>
            <h3>{t("rep.sections")}</h3>
            <div className="rep-secs">
              <button type="button" className={sec === "" ? "on" : ""} onClick={() => setSec("")}><span>{t("rep.allSections")}</span><span>{base.length}</span></button>
              {sections.map(([s, fs]) => (
                <button key={s} type="button" className={sec === s ? "on" : ""} onClick={() => setSec(s)}>
                  <span dir="auto">{s}</span><span>{fs.length}</span>
                  <span className="mini" style={{ width: `${(fs.length / maxSec) * 100}%` }}>
                    {SEVS.map((v) => { const c = fs.filter((f) => f.severity === v).length; return c ? <i key={v} className={`sev-${v}`} style={{ flex: c }} /> : null; })}
                  </span>
                </button>
              ))}
            </div>
          </>}
        </aside>

        <main className="rep-main">
          {step === "x" ? (
            <div className="table-wrap panel">
              <table className="table">
                <thead><tr><th>{t("rep.document")}</th><th>{t("rep.page")}</th><th>{t("rep.reason")}</th><th>{t("rep.text")}</th></tr></thead>
                <tbody>{res.exclusions.map((e, i) => (
                  <tr key={i}><td>{t(e.doc === "approved" ? "rep.approved" : "rep.test")}</td><td>{e.page + 1}</td><td>{e.reason}</td>
                    <td className="muted" dir="auto">{(e.text || "").slice(0, 180)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          ) : <>
            <div className="rep-tools">
              <input id="rep-q" className="input grow" type="search" placeholder={t("rep.search")} aria-label={t("rep.search")} value={q} onChange={(e) => setQ(e.target.value)} />
              <button type="button" className="chip" aria-pressed={lang === "eng"} onClick={() => setLang(lang === "eng" ? "" : "eng")}>English</button>
              <button type="button" className="chip" aria-pressed={lang === "ara"} onClick={() => setLang(lang === "ara" ? "" : "ara")}>العربية</button>
              <button type="button" className="chip" aria-pressed={pending} onClick={() => setPending(!pending)}>{t("rep.undecided", { n: undecided })}</button>
              <button type="button" className="chip" aria-pressed={noise} onClick={() => setNoise(!noise)}>{t("rep.showNoise")}</button>
              <button type="button" className="chip" aria-pressed={allOpen} onClick={() => { setAllOpen(!allOpen); setOpen(new Set(allOpen ? [] : items.map((f) => f.id))); }}>
                {allOpen ? t("rep.collapse") : t("rep.expand")}</button>
              <span className="small muted">{t("rep.shown", { n: items.length })}</span>
            </div>
            {items.length === 0 ? <Empty icon={<LuShieldCheck />} title={t("rep.none")} body={t("rep.noneBody")} /> : items.map((f) => (
              <Card key={f.id} cid={d.id} f={f} open={open.has(f.id)} active={active === f.id} d={d.decisions[f.id]}
                canDecide={d.permissions.decide}
                onToggle={() => { setActive(f.id); setOpen((o) => { const n = new Set(o); if (n.has(f.id)) n.delete(f.id); else n.add(f.id); return n; }); }}
                onView={() => { setActive(f.id); setViewing(f.id); }} onDecided={onDecided} />
            ))}
          </>}

          <section className="panel rep-sigs" aria-labelledby="sig-h">
            <div className="panel-head"><h2 id="sig-h">{t("rep.signatures")}</h2></div>
            <div className="panel-body stack">
              {d.signatures.length === 0 ? <p className="muted">{t("rep.noSignatures")}</p> : (
                <ul className="sig-cards">
                  {d.signatures.map((s) => (
                    <li key={s.id}>
                      <strong>{s.user_name}</strong>
                      <span>{t(`meaning.${s.meaning}` as StringKey)} · {dateTime(s.signed_at)}</span>
                      <span className="small muted">{s.statement}</span>
                      {s.reason && <span className="small">“{s.reason}”</span>}
                      <span className="small subtle mono-id">SHA-256 {s.record_hash.slice(0, 20)}…</span>
                    </li>
                  ))}
                </ul>
              )}
              {d.status === "review" && d.approval_blockers.length > 0 && (
                <Notice tone="warn"><strong>{t("rep.beforeApproval")}</strong><ul className="plain">{d.approval_blockers.map((b) => <li key={b}>{b}</li>)}</ul></Notice>
              )}
              <p className="small subtle">{t("rep.integrity", { sha: (d.result_sha256 ?? "").slice(0, 24), engine: res.engine_version, s: Math.round(res.seconds) })}
                {res.ai.vision_model || res.ai.reading_model || res.ai.science_model ? " · " + t("rep.aiModels", { m: [res.ai.reading_model, res.ai.vision_model, res.ai.science_model].filter(Boolean).join(", ") }) : ""}</p>
            </div>
          </section>
        </main>

        {step !== "x" && <LeafletMap cid={d.id} res={res} items={items} active={active} onPick={pick} />}
      </div>

      {viewF && <Viewer cid={d.id} res={res} f={viewF} onClose={() => setViewing(null)} onStep={stepBy} />}
      {signing && <SignDialog meaning={signing} label={`${d.number} · ${d.title}`} needsReason={signing === "rejected"}
        blockers={signing === "approved" ? d.approval_blockers : undefined} onClose={() => setSigning(null)} onSign={sign} />}
    </>
  );
}

export function ComparisonView({ comparisonId }: { comparisonId: string }) {
  const { t } = useI18n();
  const { data, error, reload, setData } = useLoad(() => get<Detail>(`/api/comparisons/${comparisonId}`), [comparisonId]);
  useEffect(() => {
    if (!data || !(data.status === "queued" || data.status === "running")) return;
    const id = setInterval(async () => {
      try {
        const s = await get<{ status: CompStatus; progress: string }>(`/api/comparisons/${comparisonId}/status`);
        if (s.status !== data.status && !(s.status === "running" && data.status === "queued")) reload();
        else setData({ ...data, status: s.status, progress: s.progress });
      } catch { /* keep polling */ }
    }, 2500);
    return () => clearInterval(id);
  }, [data, comparisonId, reload, setData]);
  if (error) return <div className="panel"><LoadError error={error} onRetry={reload} /></div>;
  if (!data) return <div className="panel"><div className="panel-body"><div className="skeleton" style={{ width: "50%" }} /></div></div>;
  return (
    <div className="report">
      <nav className="crumbs small"><Link to="/comparisons">{t("cmp.title")}</Link> / <span className="mono-id">{data.number}</span></nav>
      {data.result ? <Report d={data} setD={setData} /> : (
        <>
          <h1 className="rep-title" dir="auto">{data.title}</h1>
          <div className="row wrap" style={{ marginBottom: 12 }}><StatusBadge status={data.status} /><span className="small muted mono-id">{data.number}</span>
            <Badge>{data.files.reference.filename}</Badge><Badge>{data.files.test.filename}</Badge></div>
          <Progress d={data} onChange={reload} />
        </>
      )}
    </div>
  );
}
