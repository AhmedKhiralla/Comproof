// Shared interface components.
import {
  createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type RefObject, type SelectHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import {
  LuCheck, LuCircleAlert, LuCircleCheck, LuCopy, LuEye, LuEyeOff, LuInfo, LuLoaderCircle, LuTriangleAlert, LuX,
} from "react-icons/lu";
import { ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n";

// ------------------------------------------------------------------ Button
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger" | "default";
  size?: "sm" | "md";
  icon?: ReactNode;
  busy?: boolean;
  iconOnly?: boolean;
  block?: boolean;
};

export function Button({ variant = "default", size = "md", icon, busy, iconOnly, block, className = "", children, disabled, ...rest }: BtnProps) {
  const cls = ["btn", variant !== "default" ? variant : "", size === "sm" ? "sm" : "", iconOnly ? "icon" : "", block ? "block" : "", className]
    .filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {busy ? <LuLoaderCircle className="spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ Fields
export function Field({ label, hint, error, children, id }: { label: ReactNode; hint?: ReactNode; error?: string; children: (id: string, describedBy?: string) => ReactNode; id?: string }) {
  const auto = useId();
  const fid = id ?? auto;
  const hintId = hint ? `${fid}-hint` : undefined;
  const errId = error ? `${fid}-err` : undefined;
  const described = [hintId, errId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={fid}>{label}</label>
      {children(fid, described)}
      {hint && !error && <div className="hint" id={hintId}>{hint}</div>}
      {error && <div className="error" id={errId} role="alert">{error}</div>}
    </div>
  );
}

export function TextField({ label, hint, error, value, onChange, ...rest }: {
  label: ReactNode; hint?: ReactNode; error?: string; value: string; onChange: (v: string) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, describedBy) => (
        <input id={id} className="input" value={value} aria-invalid={!!error} aria-describedby={describedBy}
          onChange={(e) => onChange(e.target.value)} {...rest} />
      )}
    </Field>
  );
}

export function PasswordField({ label, hint, error, value, onChange, autoComplete = "current-password", ...rest }: {
  label: ReactNode; hint?: ReactNode; error?: string; value: string; onChange: (v: string) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">) {
  const [show, setShow] = useState(false);
  const { t } = useI18n();
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, describedBy) => (
        <div className="input-wrap">
          <input id={id} className="input" type={show ? "text" : "password"} value={value} dir="ltr"
            aria-invalid={!!error} aria-describedby={describedBy} autoComplete={autoComplete}
            onChange={(e) => onChange(e.target.value)} {...rest} />
          <Button variant="ghost" iconOnly size="sm" onClick={() => setShow((s) => !s)}
            aria-label={show ? t("login.hide") : t("login.show")} icon={show ? <LuEyeOff /> : <LuEye />} />
        </div>
      )}
    </Field>
  );
}

export function SelectField({ label, hint, error, value, onChange, options, ...rest }: {
  label: ReactNode; hint?: ReactNode; error?: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[];
} & Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange">) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, describedBy) => (
        <select id={id} className="select" value={value} aria-invalid={!!error} aria-describedby={describedBy}
          onChange={(e) => onChange(e.target.value)} {...rest}>
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      )}
    </Field>
  );
}

export function Switch({ checked, onChange, label, id, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; id?: string; disabled?: boolean }) {
  return (
    <span className="switch">
      <input id={id} type="checkbox" role="switch" aria-label={label} checked={checked} disabled={disabled}
        onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      <span className="thumb" />
    </span>
  );
}

export function Badge({ tone, children, dot }: { tone?: "ok" | "warn" | "danger" | "brand"; children: ReactNode; dot?: boolean }) {
  return <span className={`badge ${tone ?? ""}`}>{dot && <span className="dot" />}{children}</span>;
}

// ------------------------------------------------------------------ Layout pieces
export function PageHead({ title, lead, actions }: { title: string; lead?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="titles">
        <h1>{title}</h1>
        {lead && <p>{lead}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export function Empty({ icon, title, body, action }: { icon: ReactNode; title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="glyph" aria-hidden>{icon}</div>
      <h3>{title}</h3>
      {body && <p>{body}</p>}
      {action}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "danger" | "ok"; children: ReactNode }) {
  const icon = { info: <LuInfo />, warn: <LuTriangleAlert />, danger: <LuCircleAlert />, ok: <LuCircleCheck /> }[tone];
  return <div className={`notice ${tone}`} role={tone === "danger" ? "alert" : undefined}>{icon}<div>{children}</div></div>;
}

export function LoadingRows({ rows = 4, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <tbody aria-busy="true">
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r}>{Array.from({ length: cols }).map((__, c) => <td key={c}><div className="skeleton" style={{ width: `${50 + ((r + c) % 3) * 15}%` }} /></td>)}</tr>
      ))}
    </tbody>
  );
}

export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div className="panel-body">
      <Notice tone="danger">
        <div className="stack" style={{ gap: 10 }}>
          <span>{errorText(error, t)}</span>
          <div><Button size="sm" onClick={onRetry}>{t("common.retry")}</Button></div>
        </div>
      </Notice>
    </div>
  );
}

export function errorText(error: unknown, t: ReturnType<typeof useI18n>["t"]) {
  if (error instanceof ApiError) {
    if (error.code === "network") return t("common.networkError");
    return error.message;
  }
  return t("common.loadError");
}

// ------------------------------------------------------------------ Overlays
function Portal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body);
}

function useEscape(onClose: () => void) {
  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  }, [onClose]);
}

function useFocusTrap(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const prev = document.activeElement as HTMLElement | null;
    const first = el.querySelector<HTMLElement>("[data-autofocus]")
      ?? el.querySelector<HTMLElement>("input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled])")
      ?? el.querySelector<HTMLElement>("button:not([disabled])");
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = Array.from(el.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea, [tabindex]:not([tabindex='-1'])"));
      if (!items.length) return;
      const a = items[0], b = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); b.focus(); }
      else if (!e.shiftKey && document.activeElement === b) { e.preventDefault(); a.focus(); }
    };
    el.addEventListener("keydown", onKey);
    return () => { el.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [ref]);
}

export function Sheet({ title, lead, onClose, children, footer, onSubmit, wide, toolbar }: {
  title: string; lead?: ReactNode; onClose: () => void; children: ReactNode; footer: ReactNode; onSubmit?: () => void; wide?: boolean;
  toolbar?: ReactNode;
}) {
  const ref = useRef<HTMLFormElement>(null);
  const { t } = useI18n();
  useEscape(onClose);
  useFocusTrap(ref);
  const titleId = useId();
  return (
    <Portal>
      <div className="overlay" onClick={onClose} />
      <form ref={ref} className={`sheet ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}
        onSubmit={(e) => { e.preventDefault(); onSubmit?.(); }} noValidate>
        <div className="sheet-head">
          <div className="titles">
            <h2 id={titleId}>{title}</h2>
            {lead && <p>{lead}</p>}
          </div>
          <Button variant="ghost" iconOnly onClick={onClose} aria-label={t("common.close")} icon={<LuX />} />
        </div>
        {toolbar && <div className="sheet-toolbar">{toolbar}</div>}
        <div className="sheet-body">{children}</div>
        <div className="sheet-foot">{footer}</div>
      </form>
    </Portal>
  );
}

export function Dialog({ title, children, footer, onClose }: { title: string; children: ReactNode; footer: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEscape(onClose);
  useFocusTrap(ref);
  const titleId = useId();
  return (
    <Portal>
      <div className="overlay" onClick={onClose} />
      <div ref={ref} className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="dialog-body">
          <h2 id={titleId}>{title}</h2>
          {children}
        </div>
        <div className="dialog-foot">{footer}</div>
      </div>
    </Portal>
  );
}

export function Confirm({ title, body, confirmLabel, danger, onConfirm, onClose }: {
  title: string; body: string; confirmLabel: string; danger?: boolean; onConfirm: () => Promise<void> | void; onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { t } = useI18n();
  return (
    <Dialog title={title} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant={danger ? "danger" : "primary"} busy={busy} data-autofocus onClick={async () => {
        setBusy(true); setErr(null);
        try { await onConfirm(); onClose(); } catch (e) { setErr(errorText(e, t)); setBusy(false); }
      }}>{confirmLabel}</Button>
    </>}>
      <p>{body}</p>
      {err && <Notice tone="danger">{err}</Notice>}
    </Dialog>
  );
}

export function SecretReveal({ name, email, secret, onClose }: { name: string; email: string; secret: string; onClose: () => void }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  return (
    <Dialog title={t("secret.title", { name })} onClose={onClose}
      footer={<Button variant="primary" onClick={onClose}>{t("secret.done")}</Button>}>
      <p>{t("secret.body", { email })}</p>
      <div className="secret">
        <code>{secret}</code>
        <Button size="sm" icon={copied ? <LuCheck /> : <LuCopy />} onClick={async () => {
          try { await navigator.clipboard.writeText(secret); setCopied(true); } catch { /* clipboard blocked */ }
        }}>{copied ? t("common.copied") : t("common.copy")}</Button>
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ Menu
export function Menu({ trigger, children, align = "end" }: {
  trigger: (props: { onClick: () => void; "aria-expanded": boolean; "aria-haspopup": "menu"; ref: (el: HTMLButtonElement | null) => void }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "start" | "end";
}) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement | null>(null);
  const menu = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const { dir } = useI18n();
  const close = useCallback(() => { setOpen(false); btn.current?.focus(); }, []);

  useLayoutEffect(() => {
    if (!open || !btn.current || !menu.current) return;
    const r = btn.current.getBoundingClientRect();
    const m = menu.current.getBoundingClientRect();
    const endAligned = (align === "end") !== (dir === "rtl");
    let left = endAligned ? r.right - m.width : r.left;
    left = Math.max(8, Math.min(left, window.innerWidth - m.width - 8));
    let top = r.bottom + 6 + window.scrollY;
    if (r.bottom + m.height + 12 > window.innerHeight) top = r.top - m.height - 6 + window.scrollY;
    setPos({ top, left: left + window.scrollX });
    menu.current.querySelector<HTMLElement>(".menu-item")?.focus();
  }, [open, align, dir]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const items = Array.from(menu.current?.querySelectorAll<HTMLElement>(".menu-item") ?? []);
        const i = items.indexOf(document.activeElement as HTMLElement);
        const next = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
        items[next]?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, close]);

  return (
    <>
      {trigger({ onClick: () => setOpen((o) => !o), "aria-expanded": open, "aria-haspopup": "menu", ref: (el) => { btn.current = el; } })}
      {open && (
        <Portal>
          <div ref={menu} className="menu" role="menu" style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}>
            {children(() => setOpen(false))}
          </div>
        </Portal>
      )}
    </>
  );
}

export function MenuItem({ icon, children, onClick, danger }: { icon?: ReactNode; children: ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button type="button" role="menuitem" className={`menu-item ${danger ? "danger" : ""}`} onClick={onClick}>
      {icon}{children}
    </button>
  );
}

// ------------------------------------------------------------------ Toasts
const ToastCtx = createContext<(msg: string) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string }[]>([]);
  const push = useCallback((msg: string) => {
    const id = Date.now() + Math.random();
    setItems((s) => [...s, { id, msg }]);
    setTimeout(() => setItems((s) => s.filter((x) => x.id !== id)), 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((x) => <div key={x.id} className="toast"><LuCheck />{x.msg}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

// ------------------------------------------------------------------ Data loading
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try { setData(await fnRef.current()); } catch (e) { setError(e); } finally { setLoading(false); }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, deps);
  return { data, error, loading, reload, setData };
}

/** Field-level error messages from an API validation error. */
export function fieldErrors(e: unknown): Record<string, string> {
  return e instanceof ApiError ? e.fields : {};
}

export function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "");
}
