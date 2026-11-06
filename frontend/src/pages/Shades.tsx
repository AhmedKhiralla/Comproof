// Shade standards: the Standard / Light / Dark colour reference of a packaging component.
import { useState } from "react";
import { LuPalette, LuPlus, LuShieldCheck, LuUndo2 } from "react-icons/lu";
import { FileDrop, SignDialog, type Meaning, type UploadedFile } from "../components/cp";
import { Badge, Button, Empty, Notice, SelectField, Sheet, TextField, errorText, fieldErrors, useToast } from "../components/ui";
import { post } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { usePerms } from "../lib/session";
import type { StringKey } from "../lib/strings";

type Lab = { L: number; a: number; b: number };
export interface Ink {
  id: string; name: string; status: "ok" | "flat" | "one_sided" | "swapped" | "outside"; note: string; area_pct: number | null;
  standard: Lab; light: Lab; dark: Lab;
}
export interface ShadeSet {
  id: string; version: string; source: "scan_target" | "scan" | "spectro" | "photo"; status: "draft" | "effective" | "superseded" | "withdrawn";
  verification: "pass" | "warn" | "fail"; measurement_sha256: string; supplier: string | null; reference_no: string | null; notes: string | null;
  standard_filename: string; light_filename: string; dark_filename: string; created_at: string; created_by_name: string | null;
  measurement: { confidence: string; messages: string[]; inks: Ink[]; calibration?: Record<string, { method: string; note?: string; residual_de00?: number }>;
    previews?: Record<string, string> };
  signatures: { id: number; meaning: string; user_name: string; signed_at: string; reason: string | null }[];
}

/** L*a*b* -> sRGB hex, for the swatches. */
export function labHex({ L, a, b }: Lab): string {
  const fy = (L + 16) / 116, fx = fy + a / 500, fz = fy - b / 200;
  const inv = (t: number) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787);
  const X = 0.95047 * inv(fx), Y = 1.0 * inv(fy), Z = 1.08883 * inv(fz);
  const lin = [3.2406 * X - 1.5372 * Y - 0.4986 * Z, -0.9689 * X + 1.8758 * Y + 0.0415 * Z, 0.0557 * X - 0.204 * Y + 1.057 * Z];
  return "#" + lin.map((c) => {
    const v = c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055;
    return Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16).padStart(2, "0");
  }).join("");
}

export function Swatch({ lab, label }: { lab: Lab | null | undefined; label?: string }) {
  return <span className="swatch" title={lab ? `L* ${lab.L.toFixed(1)} a* ${lab.a.toFixed(1)} b* ${lab.b.toFixed(1)}` : "—"}
    style={{ background: lab ? labHex(lab) : "transparent" }}>{label && <i>{label}</i>}</span>;
}

function ShadeSheet({ componentId, next, onClose, onSaved }: { componentId: string; next: string; onClose: () => void; onSaved: (c: any) => void }) {
  const { t } = useI18n();
  const [files, setFiles] = useState<Record<"standard" | "light" | "dark", UploadedFile | null>>({ standard: null, light: null, dark: null });
  const [f, setF] = useState({ version: next, source: "scan", supplier: "", reference_no: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      onSaved(await post(`/api/components/${componentId}/shades`, {
        ...f, standard_file_id: files.standard?.id ?? "", light_file_id: files.light?.id ?? "", dark_file_id: files.dark?.id ?? "",
      }));
      onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  const ready = files.standard && files.light && files.dark;
  return (
    <Sheet title={t("shade.new")} lead={t("shade.newLead")} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button type="submit" variant="primary" busy={busy} disabled={!ready}>{busy ? t("shade.measuring") : t("shade.measure")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <SelectField label={t("shade.source")} value={f.source} onChange={(v) => setF({ ...f, source: v })} error={errs.source}
        hint={t(`shade.source.${f.source}.hint` as StringKey)}
        options={(["scan", "scan_target", "spectro", "photo"] as const).map((s) => ({ value: s, label: t(`shade.source.${s}` as StringKey) }))} />
      {(["standard", "light", "dark"] as const).map((k) => (
        <FileDrop key={k} label={t(`shade.${k}` as StringKey)} value={files[k]} onChange={(v) => setFiles((x) => ({ ...x, [k]: v }))}
          error={errs[`${k}_file_id`]} hint={t(f.source === "spectro" ? "shade.fileHintSpectro" : "shade.fileHint")} />
      ))}
      <div className="grid-2">
        <TextField label={t("lib.ver.version")} value={f.version} dir="ltr" onChange={(v) => setF({ ...f, version: v })} error={errs.version} />
        <TextField label={t("cmp.supplier")} value={f.supplier} onChange={(v) => setF({ ...f, supplier: v })} />
      </div>
      <TextField label={t("shade.refNo")} value={f.reference_no} dir="ltr" onChange={(v) => setF({ ...f, reference_no: v })} />
      <Notice>{t("shade.howItWorks")}</Notice>
    </Sheet>
  );
}

export function ShadeSection({ component, onChanged }: { component: { id: string; code: string; can_edit: boolean; shade_sets?: ShadeSet[] }; onChanged: (c: any) => void }) {
  const { t, dateTime } = useI18n();
  const { has } = usePerms();
  const toast = useToast();
  const [add, setAdd] = useState(false);
  const [signing, setSigning] = useState<{ s: ShadeSet; meaning: Meaning } | null>(null);
  const sets = component.shade_sets ?? [];
  const approver = has("approver");
  const tone = { draft: "brand", effective: "ok", superseded: undefined, withdrawn: "danger" } as const;
  const vtone = { pass: "ok", warn: "warn", fail: "danger" } as const;
  return (
    <section className="panel" aria-labelledby="shade-h">
      <div className="panel-head"><h2 id="shade-h">{t("shade.title")}</h2><span className="spacer" />
        {component.can_edit && <Button size="sm" icon={<LuPlus />} onClick={() => setAdd(true)}>{t("shade.new")}</Button>}</div>
      {sets.length === 0 ? (
        <Empty icon={<LuPalette />} title={t("shade.empty")} body={t("shade.emptyBody")}
          action={component.can_edit && <Button variant="primary" icon={<LuPlus />} onClick={() => setAdd(true)}>{t("shade.new")}</Button>} />
      ) : (
        <ul className="versions">
          {sets.map((s) => (
            <li key={s.id} className={`version st-${s.status}`}>
              <div className="v-head">
                <strong className="mono-id">{s.version}</strong>
                <Badge tone={tone[s.status]} dot>{t(`ver.${s.status}` as StringKey)}</Badge>
                <Badge tone={vtone[s.verification]}>{t(`shade.verify.${s.verification}` as StringKey)}</Badge>
                <span className="small muted">{t(`shade.source.${s.source}` as StringKey)} · {t(`shade.conf.${s.measurement.confidence}` as StringKey)}</span>
                <span className="spacer" />
                {approver && s.status === "draft" && s.verification !== "fail" &&
                  <Button size="sm" variant="primary" icon={<LuShieldCheck />} onClick={() => setSigning({ s, meaning: "approved_master" })}>{t("shade.approve")}</Button>}
                {approver && (s.status === "draft" || s.status === "effective") &&
                  <Button size="sm" variant="ghost" icon={<LuUndo2 />} onClick={() => setSigning({ s, meaning: "withdrawn" })}>{t("lib.ver.withdraw")}</Button>}
              </div>
              <div className="v-body small">
                {s.measurement.messages.map((m) => <span key={m} className={s.verification === "fail" ? "error" : "muted"}>{m}</span>)}
                {Object.entries(s.measurement.calibration ?? {}).filter(([, c]) => c.note).slice(0, 1).map(([k, c]) => <span key={k} className="muted">{c.note}</span>)}
              </div>
              {s.measurement.previews && (
                <div className="shade-previews">
                  {(["dark", "standard", "light"] as const).map((k) => (
                    <figure key={k}><img loading="lazy" alt="" src={`/api/shades/${s.id}/preview/${k}.jpg`} />
                      <figcaption>{t(`shade.${k}` as StringKey)}</figcaption></figure>
                  ))}
                </div>
              )}
              <div className="table-wrap"><table className="table ink-table">
                <thead><tr><th>{t("shade.ink")}</th><th>{t("shade.dark")}</th><th>{t("shade.standard")}</th><th>{t("shade.light")}</th><th>{t("shade.inkStatus")}</th></tr></thead>
                <tbody>
                  {s.measurement.inks.map((i) => (
                    <tr key={i.id}>
                      <td><span className="mono-id subtle">{i.id}</span> {i.name}{i.area_pct != null && <div className="cell-sub">{i.area_pct}% {t("shade.ofArea")}</div>}</td>
                      {(["dark", "standard", "light"] as const).map((k) => (
                        <td key={k}><span className="lab-cell"><Swatch lab={i[k]} /><span className="mono-id small">{i[k].L.toFixed(1)} / {i[k].a.toFixed(1)} / {i[k].b.toFixed(1)}</span></span></td>
                      ))}
                      <td><Badge tone={i.status === "ok" ? "ok" : i.status === "flat" || i.status === "one_sided" ? undefined : "danger"}>{t(`shade.ink.${i.status}` as StringKey)}</Badge>
                        <div className="cell-sub">{i.note}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
              <div className="v-body small">
                <span className="muted">{[s.standard_filename, s.light_filename, s.dark_filename].join(" · ")}{s.supplier ? ` · ${s.supplier}` : ""}</span>
                <span className="mono-id subtle">SHA-256 {s.measurement_sha256}</span>
                <span className="muted">{t("lib.ver.registered", { who: s.created_by_name ?? "—", when: dateTime(s.created_at) })}</span>
              </div>
              {s.signatures.length > 0 && (
                <ul className="sig-list">
                  {s.signatures.map((g) => <li key={g.id}><LuShieldCheck aria-hidden /><span><strong>{g.user_name}</strong> · {t(`shade.meaning.${g.meaning}` as StringKey)} · {dateTime(g.signed_at)}{g.reason ? ` · “${g.reason}”` : ""}</span></li>)}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {add && <ShadeSheet componentId={component.id} next={`S${sets.length + 1}`} onClose={() => setAdd(false)}
        onSaved={(c) => { onChanged(c); toast(t("shade.saved")); }} />}
      {signing && <SignDialog meaning={signing.meaning} label={`${component.code} · ${t("shade.title")} ${signing.s.version}`}
        needsReason={signing.meaning === "withdrawn"} onClose={() => setSigning(null)}
        titleKey={`shade.signTitle.${signing.meaning}` as StringKey} statementKey={`shade.statement.${signing.meaning}` as StringKey}
        onSign={async (b) => { onChanged(await post(`/api/shades/${signing.s.id}/sign`, b)); toast(t("sign.done")); }} />}
    </section>
  );
}
