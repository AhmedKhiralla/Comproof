import { useState, type CSSProperties } from "react";
import { LuLanguages, LuMonitor, LuMoon, LuSun } from "react-icons/lu";
import { Button, Notice, PasswordField, TextField, errorText } from "../components/ui";
import { ApiError, get, post } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSession, type Me } from "../lib/session";
import { useTheme } from "../lib/theme";
import { Logo } from "../components/Logo";

/** An illustrative proof check: the approved line, the new artwork line, and what changed. */
const PROOF: { sec: string; ref: (string | [string, string])[]; sev: "critical" | "major" | "minor" }[] = [
  { sec: "2. Composition", sev: "critical", ref: ["Each film contains", ["2.5 mg", "5 mg"], "of bisoprolol fumarate."] },
  { sec: "4.2 Method of administration", sev: "major", ref: ["Instructions on handling the", ["Oro-dispersible", "Oral dissolvable"], "film."] },
  { sec: "4.2 Posology", sev: "minor", ref: ["The maximum recommended dose is", ["10 mg", "10mg"], "once daily."] },
];

function ProofVisual() {
  const { t } = useI18n();
  return (
    <div className="proofviz" aria-hidden>
      {PROOF.map((p, i) => (
        <div className={`pv-line sev-${p.sev}`} key={i} style={{ "--d": `${0.2 + i * 0.25}s` } as CSSProperties}>
          <div className="pv-sec">{p.sec}</div>
          <div className="pv-text">
            {p.ref.map((x, j) => typeof x === "string" ? <span key={j}>{x} </span> : <span key={j}><del>{x[0]}</del> <ins>{x[1]}</ins> </span>)}
          </div>
          <span className="pv-sev">{t(`sev.${p.sev}`)}</span>
        </div>
      ))}
      <div className="pv-sign"><span>✓ {t("login.vizReviewed")}</span><span>✓ {t("login.vizApproved")}</span></div>
    </div>
  );
}

export function Prefs() {
  const { lang } = useI18n();
  const { choice } = useTheme();
  const { savePreference } = useSession();
  const { t } = useI18n();
  return (
    <div className="row wrap">
      <div className="seg" role="group" aria-label={t("common.language")}>
        <button type="button" aria-pressed={lang === "en"} onClick={() => savePreference({ language: "en" })} lang="en">
          <LuLanguages aria-hidden />English
        </button>
        <button type="button" aria-pressed={lang === "ar"} onClick={() => savePreference({ language: "ar" })} lang="ar">العربية</button>
      </div>
      <div className="seg" role="group" aria-label={t("theme.label")}>
        <button type="button" aria-pressed={choice === "light"} onClick={() => savePreference({ theme: "light" })} title={t("theme.light")} aria-label={t("theme.light")}><LuSun /></button>
        <button type="button" aria-pressed={choice === "dark"} onClick={() => savePreference({ theme: "dark" })} title={t("theme.dark")} aria-label={t("theme.dark")}><LuMoon /></button>
        <button type="button" aria-pressed={choice === "system"} onClick={() => savePreference({ theme: "system" })} title={t("theme.system")} aria-label={t("theme.system")}><LuMonitor /></button>
      </div>
    </div>
  );
}

export function Login() {
  const { t } = useI18n();
  const { setMe, signedOutReason } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      await post("/api/auth/login", { email: email.trim(), password });
      setMe(await get<Me>("/api/auth/me"));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 422 ? t("common.fixFields") : errorText(e, t));
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <div className="auth-form">
        <div className="top">
          <Logo height={44} />
        </div>
        <div className="middle">
          <h1>{t("login.title")}</h1>
          <p className="lead">{t("login.lead")}</p>
          <form onSubmit={(e) => { e.preventDefault(); submit(); }} noValidate>
            {signedOutReason === "expired" && !error && <Notice tone="warn">{t("login.expired")}</Notice>}
            {signedOutReason === "signed-out" && !error && <Notice tone="ok">{t("login.signedOut")}</Notice>}
            {error && <Notice tone="danger">{error}</Notice>}
            <TextField label={t("login.email")} type="email" value={email} onChange={setEmail}
              autoComplete="username" dir="ltr" required autoFocus />
            <PasswordField label={t("login.password")} value={password} onChange={setPassword} required />
            <Button type="submit" variant="primary" block busy={busy} disabled={!email || !password}>
              {busy ? t("login.submitting") : t("login.submit")}
            </Button>
            <p className="small subtle">{t("login.forgot")}</p>
          </form>
        </div>
        <div className="foot">
          <Prefs />
          <span>Comproof · Comp11 Labs</span>
        </div>
      </div>
      <div className="auth-visual">
        <div className="claim">
          <h2>{t("login.visualTitle")}</h2>
          <p>{t("login.visualBody")}</p>
        </div>
        <ProofVisual />
        <div className="legend">
          <span><i className="lg-del" />{t("login.legendApproved")}</span>
          <span><i className="lg-ins" />{t("login.legendNew")}</span>
          <span><i className="lg-sig" />{t("login.legendSigned")}</span>
        </div>
      </div>
    </div>
  );
}
