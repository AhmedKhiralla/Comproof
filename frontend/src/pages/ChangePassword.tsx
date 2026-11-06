import { useState } from "react";
import { LuCheck, LuCircle } from "react-icons/lu";
import { Button, Notice, PasswordField, errorText, useToast } from "../components/ui";
import { ApiError, post } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { navigate } from "../lib/router";
import { useSession, type Me, type Policy } from "../lib/session";
import { Logo } from "../components/Logo";
import { Prefs } from "./Login";

export function rulesFor(policy: Policy, pw: string) {
  const rules: { key: string; met: boolean; n?: number }[] = [
    { key: "min_length", met: pw.length >= policy.min_length, n: policy.min_length },
  ];
  if (policy.require_upper) rules.push({ key: "require_upper", met: /[A-Z]/.test(pw) });
  if (policy.require_lower) rules.push({ key: "require_lower", met: /[a-z]/.test(pw) });
  if (policy.require_digit) rules.push({ key: "require_digit", met: /\d/.test(pw) });
  if (policy.require_symbol) rules.push({ key: "require_symbol", met: /[^A-Za-z0-9]/.test(pw) });
  return rules;
}

export function PasswordForm({ onDone, compact }: { onDone?: () => void; compact?: boolean }) {
  const { t, tx } = useI18n();
  const { me, setMe } = useSession();
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  if (!me) return null;
  const rules = rulesFor(me.policy, next);
  const allMet = rules.every((r) => r.met);

  const submit = async () => {
    setErrors({}); setGeneral(null);
    if (next !== confirm) { setErrors({ confirm: t("pw.mismatch") }); return; }
    setBusy(true);
    try {
      const updated = await post<Me>("/api/auth/change-password", { current_password: current, new_password: next });
      toast(t("pw.done"));
      setMe(updated);
      onDone?.();
    } catch (e) {
      if (e instanceof ApiError && e.code === "reused_password") setErrors({ new_password: e.message || t("pw.reused") });
      else if (e instanceof ApiError && e.fields.current_password) setErrors({ current_password: e.fields.current_password });
      else setGeneral(errorText(e, t));
      setBusy(false);
    }
  };

  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); submit(); }} noValidate>
      {general && <Notice tone="danger">{general}</Notice>}
      <PasswordField label={t("pw.current")} value={current} onChange={setCurrent} error={errors.current_password} autoComplete="current-password" />
      <div className="field">
        <PasswordField label={t("pw.new")} value={next} onChange={setNext} error={errors.new_password} autoComplete="new-password" />
        <ul className="rules" aria-label={t("pw.new")}>
          {rules.map((r) => (
            <li key={r.key} className={r.met ? "met" : ""}>
              {r.met ? <LuCheck aria-hidden /> : <LuCircle aria-hidden />}
              {tx(`pw.rule.${r.key}`, r.key, { n: r.n ?? "" })}
            </li>
          ))}
        </ul>
      </div>
      <PasswordField label={t("pw.confirm")} value={confirm} onChange={setConfirm} error={errors.confirm} autoComplete="new-password" />
      <div className={compact ? "row" : ""}>
        <Button type="submit" variant="primary" block={!compact} busy={busy} disabled={!current || !allMet || !confirm}>{t("pw.submit")}</Button>
      </div>
    </form>
  );
}

/** Shown when a password change is required before anything else. */
export function ForcedPasswordChange() {
  const { t } = useI18n();
  const { signOut } = useSession();
  return (
    <div className="center-card">
      <div className="panel">
        <div className="panel-body">
          <div className="row"><Logo height={36} /><span className="spacer" /><Prefs /></div>
          <div className="stack" style={{ gap: 6 }}>
            <h1>{t("pw.title")}</h1>
            <p className="muted">{t("pw.leadFirst")}</p>
          </div>
          <PasswordForm onDone={() => navigate("/", true)} />
          <Button variant="ghost" onClick={signOut}>{t("pw.signOut")}</Button>
        </div>
      </div>
    </div>
  );
}

export function ChangePasswordPage() {
  const { t } = useI18n();
  return (
    <div style={{ maxWidth: 480 }}>
      <div className="page-head"><div className="titles"><h1>{t("user.changePassword")}</h1><p>{t("pw.leadVoluntary")}</p></div></div>
      <div className="panel"><div className="panel-body"><PasswordForm compact onDone={() => navigate("/")} /></div></div>
    </div>
  );
}
