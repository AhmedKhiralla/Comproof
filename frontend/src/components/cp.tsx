// Comproof building blocks: status badges, file upload, electronic signature dialog.
import { useRef, useState, type DragEvent } from "react";
import { LuFileCheck2, LuFileUp, LuLockKeyhole, LuX } from "react-icons/lu";
import { ApiError, qs } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSession } from "../lib/session";
import type { StringKey } from "../lib/strings";
import { Badge, Button, Dialog, Notice, PasswordField, TextField, errorText, fieldErrors } from "./ui";

export type CompStatus = "queued" | "running" | "review" | "approved" | "rejected" | "failed" | "cancelled";

export function StatusBadge({ status }: { status: CompStatus }) {
  const { t } = useI18n();
  const tone = ({ approved: "ok", rejected: "danger", failed: "danger", review: "warn", running: "brand", queued: "brand" } as const)[
    status as "approved"] as "ok" | "danger" | "warn" | "brand" | undefined;
  return <Badge tone={tone} dot>{t(`status.${status}` as StringKey)}</Badge>;
}

export function SevCounts({ summary }: { summary: { steps?: Record<string, Record<string, number>> } | null }) {
  const { t } = useI18n();
  if (!summary?.steps) return <span className="subtle">—</span>;
  const tot = { critical: 0, major: 0, minor: 0 };
  Object.values(summary.steps).forEach((s) => { tot.critical += s.critical ?? 0; tot.major += s.major ?? 0; tot.minor += s.minor ?? 0; });
  return (
    <span className="sev-counts">
      {(["critical", "major", "minor"] as const).map((k) => (
        <span key={k} className={`sev-n sev-${k} ${tot[k] ? "" : "zero"}`} title={t(`sev.${k}`)}>{tot[k]}</span>
      ))}
    </span>
  );
}

export interface UploadedFile {
  id: string; sha256: string; filename: string; mime: string; size_bytes: number; page_count: number | null; doc_kind: string;
}

async function uploadFile(file: File): Promise<UploadedFile> {
  const res = await fetch("/api/files" + qs({ filename: file.name }), {
    method: "POST", body: file, credentials: "same-origin",
    headers: { "X-Requested-With": "comproof", "Content-Type": "application/octet-stream" },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data?.error?.code ?? "server_error", data?.error?.message ?? res.statusText);
  return data as UploadedFile;
}

export function fileSize(n: number) {
  return n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

/** Drop zone that uploads straight away and shows what was stored (name, pages, type, SHA-256). */
export function FileDrop({ label, hint, value, onChange, error }: {
  label: string; hint?: string; value: UploadedFile | null; onChange: (f: UploadedFile | null) => void; error?: string;
}) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const take = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true); setErr(null);
    try { onChange(await uploadFile(file)); } catch (e) { setErr(errorText(e, t)); } finally { setBusy(false); }
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files?.[0]); };
  return (
    <div className="field">
      <span className="label-like">{label}</span>
      {value ? (
        <div className="file-chip">
          <LuFileCheck2 aria-hidden className="ok-ic" />
          <div className="grow">
            <strong>{value.filename}</strong>
            <span className="small muted">
              {t(`doc.${value.doc_kind}` as StringKey)} · {value.page_count ?? "–"} {t("cp.pages")} · {fileSize(value.size_bytes)}
            </span>
            <span className="small subtle mono-id" title={value.sha256}>SHA-256 {value.sha256.slice(0, 16)}…</span>
          </div>
          <Button size="sm" variant="ghost" iconOnly icon={<LuX />} aria-label={t("cp.removeFile")} onClick={() => onChange(null)} />
        </div>
      ) : (
        <button type="button" className={`drop ${over ? "over" : ""}`} onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop} aria-busy={busy}>
          <LuFileUp aria-hidden />
          <span><strong>{busy ? t("cp.uploading") : t("cp.dropFile")}</strong><span className="small muted">{hint ?? t("cp.fileTypes")}</span></span>
        </button>
      )}
      <input ref={input} type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.docx"
        onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }} />
      {(err || error) && <div className="error" role="alert">{err || error}</div>}
    </div>
  );
}

export type Meaning = "reviewed" | "approved" | "rejected" | "approved_master" | "withdrawn";

/** Electronic signature: shows the statement and the meaning, re-asks for email and password (21 CFR 11.200). */
export function SignDialog({ meaning, label, needsReason, blockers, onSign, onClose }: {
  meaning: Meaning; label: string; needsReason?: boolean; blockers?: string[];
  onSign: (body: { meaning: Meaning; email: string; password: string; reason?: string }) => Promise<void>; onClose: () => void;
}) {
  const { t } = useI18n();
  const { me } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const submit = async () => {
    setBusy(true); setErr(null); setFields({});
    try { await onSign({ meaning, email, password, reason: reason || undefined }); onClose(); }
    catch (e) { setErr(errorText(e, t)); setFields(fieldErrors(e)); setBusy(false); setPassword(""); }
  };
  const danger = meaning === "rejected" || meaning === "withdrawn";
  return (
    <Dialog title={t(`sign.title.${meaning}` as StringKey)} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant={danger ? "danger" : "primary"} icon={<LuLockKeyhole />} busy={busy}
        disabled={!email || !password || (needsReason && reason.trim().length < 3)} onClick={submit}>{t(`sign.do.${meaning}` as StringKey)}</Button>
    </>}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="sign-record"><span className="small muted">{t("sign.record")}</span><strong>{label}</strong></div>
        <blockquote className="sign-statement">{t(`sign.statement.${meaning}` as StringKey)}</blockquote>
        {blockers && blockers.length > 0 && <Notice tone="warn"><ul className="plain">{blockers.map((b) => <li key={b}>{b}</li>)}</ul></Notice>}
        {err && <Notice tone="danger">{err}</Notice>}
        {(needsReason || meaning === "approved") && (
          <div className="field">
            <label htmlFor="sign-reason">{t(needsReason ? "sign.reason" : "sign.comment")}</label>
            <textarea id="sign-reason" className="textarea" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
            {fields.reason && <div className="error">{fields.reason}</div>}
          </div>
        )}
        <TextField label={t("sign.email")} type="email" autoComplete="off" value={email} onChange={setEmail} dir="ltr"
          hint={t("sign.emailHint", { name: me?.user.full_name ?? "" })} />
        <PasswordField label={t("sign.password")} autoComplete="off" value={password} onChange={setPassword} />
        <p className="small muted">{t("sign.legal")}</p>
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
