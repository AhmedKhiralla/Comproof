import { Fragment, useEffect, useState } from "react";
import { LuChevronDown, LuDownload, LuFileSpreadsheet, LuFileText, LuFilterX, LuScrollText, LuSearch, LuShieldCheck } from "react-icons/lu";
import { Badge, Button, Empty, LoadError, LoadingRows, Menu, Notice, PageHead, errorText, useLoad } from "../components/ui";
import { get, post, qs } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSession } from "../lib/session";

interface Entry {
  id: number; occurred_at: string; user_id: string | null; user_name: string | null; action: string; entity: string;
  record_id: string | null; record_label: string | null;
  old_values: Record<string, unknown> | null; new_values: Record<string, unknown> | null; details: Record<string, unknown> | null;
}
interface Facets { entities: string[]; actions: string[]; users: { id: string; name: string }[]; }

const tone = (action: string): "ok" | "warn" | "danger" | "brand" | undefined => {
  if (action === "INSERT") return "ok";
  if (["DELETE", "LOGIN_FAILED", "LOCKED", "SIGNATURE_FAILED", "RUN_FAILED"].includes(action)) return "danger";
  if (action === "UPDATE" || action === "PASSWORD_RESET" || action === "SESSION_TIMEOUT") return "warn";
  if (["EXPORT", "SIGNED", "INTEGRITY_CHECK"].includes(action)) return "brand";
  return undefined;
};

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** Field-level rows; settings stored as objects are expanded to the keys that actually changed. */
function diffRows(e: Entry): { k: string; o: unknown; n: unknown }[] {
  const rows: { k: string; o: unknown; n: unknown }[] = [];
  const keys = Array.from(new Set([...Object.keys(e.old_values ?? {}), ...Object.keys(e.new_values ?? {})])).sort();
  for (const k of keys) {
    const o = e.old_values?.[k], n = e.new_values?.[k];
    if (e.action === "UPDATE" && isObj(o) && isObj(n)) {
      const sub = Array.from(new Set([...Object.keys(o), ...Object.keys(n)])).sort();
      for (const sk of sub) {
        if (JSON.stringify(o[sk]) !== JSON.stringify(n[sk])) rows.push({ k: `${k}.${sk}`, o: o[sk], n: n[sk] });
      }
    } else rows.push({ k, o, n });
  }
  return rows;
}

function Changes({ e }: { e: Entry }) {
  const { t } = useI18n();
  const rows = diffRows(e);
  return (
    <div className="stack" style={{ gap: 12, padding: "4px 0 8px" }}>
      {rows.length > 0 && (
        <div className="diff" role="table">
          <div className="h" role="columnheader">{t("audit.field")}</div>
          <div className="h" role="columnheader">{t("audit.old")}</div>
          <div className="h" role="columnheader">{t("audit.new")}</div>
          {rows.map(({ k, o, n }) => {
            return (
              <Fragment key={k}>
                <div className="k mono-id" dir="ltr">{k}</div>
                <div className={o === undefined ? "none" : "old"} dir="auto">{o === undefined ? "—" : show(o)}</div>
                <div className={n === undefined ? "none" : "new"} dir="auto">{n === undefined ? "—" : show(n)}</div>
              </Fragment>
            );
          })}
        </div>
      )}
      {e.details && (
        <div className="small"><strong style={{ fontWeight: 500 }}>{t("audit.details")}: </strong>
          <span className="muted mono-id" dir="ltr">{Object.entries(e.details).map(([k, v]) => `${k}=${show(v)}`).join(", ")}</span></div>
      )}
      {e.record_id && <div className="small subtle mono-id" dir="ltr">ID {e.record_id} · #{e.id}</div>}
    </div>
  );
}

export function Audit() {
  const { t, tx, dateTime, number } = useI18n();
  const { me } = useSession();
  const tz = me?.tenant?.timezone ?? "UTC";
  const [check, setCheck] = useState<{ checked: number; intact: boolean; first_bad_id: string | null; error?: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [filters, setFilters] = useState({ q: "", entity: "", action: "", user_id: "", from: "", to: "" });
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { const h = setTimeout(() => setFilters((f) => (f.q === q ? f : { ...f, q })), 300); return () => clearTimeout(h); }, [q]);
  useEffect(() => { setPage(1); }, [filters]);

  const facets = useLoad(() => get<Facets>("/api/audit/facets"));
  const list = useLoad(() => get<{ items: Entry[]; total: number; page: number; page_size: number }>(
    "/api/audit" + qs({ ...filters, page, page_size: 50 })), [filters, page]);
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;
  const set = (k: keyof typeof filters) => (v: string) => setFilters((f) => ({ ...f, [k]: v }));
  const hasFilters = Object.values(filters).some(Boolean);
  const exportUrl = (format: string) => "/api/audit/export" + qs({ ...filters, format });

  const summary = (e: Entry) => {
    const n = diffRows(e).length;
    if (e.action === "UPDATE") return n === 1 ? t("audit.oneField") : t("audit.fieldsChanged", { n });
    if (e.details && typeof e.details.reason === "string") return e.details.reason.replace(/_/g, " ");
    return "";
  };

  const verify = async () => {
    setChecking(true);
    try { setCheck(await post<{ checked: number; intact: boolean; first_bad_id: string | null }>("/api/audit/verify")); list.reload(); }
    catch (e) { setCheck({ checked: 0, intact: false, first_bad_id: null, error: errorText(e, t) }); }
    finally { setChecking(false); }
  };

  return (
    <>
      <PageHead title={t("audit.title")} lead={t("audit.lead")} actions={<>
        <Button icon={<LuShieldCheck />} busy={checking} onClick={verify}>{t("audit.verify")}</Button>
        <Menu trigger={(p) => <Button icon={<LuDownload />} {...p}>{t("audit.export")}<LuChevronDown /></Button>}>
          {(close) => <>
            <a className="menu-item" role="menuitem" href={exportUrl("xlsx")} onClick={() => { close(); setTimeout(list.reload, 1500); }}><LuFileSpreadsheet />{t("audit.exportXlsx")}</a>
            <a className="menu-item" role="menuitem" href={exportUrl("csv")} onClick={() => { close(); setTimeout(list.reload, 1500); }}><LuFileText />{t("audit.exportCsv")}</a>
            <div className="menu-label">{t("audit.exportNote")}</div>
          </>}
        </Menu>
      </>} />
      {check && (check.error ? <Notice tone="danger">{check.error}</Notice>
        : <Notice tone={check.intact ? "ok" : "danger"}>
            {check.intact ? t("audit.verifyOk", { n: check.checked }) : t("audit.verifyBad", { id: check.first_bad_id ?? "" })}
          </Notice>)}
      <div className="panel">
        <div className="toolbar">
          <div className="search"><LuSearch aria-hidden />
            <input className="input" type="search" placeholder={t("audit.searchPlaceholder")} aria-label={t("audit.searchPlaceholder")} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <select className="select" aria-label={t("audit.entity")} value={filters.entity} onChange={(e) => set("entity")(e.target.value)}>
            <option value="">{t("audit.entity")}: {t("common.all")}</option>
            {(facets.data?.entities ?? []).map((x) => <option key={x} value={x}>{tx(`entity.${x}`, x)}</option>)}
          </select>
          <select className="select" aria-label={t("audit.action")} value={filters.action} onChange={(e) => set("action")(e.target.value)}>
            <option value="">{t("audit.action")}: {t("common.all")}</option>
            {(facets.data?.actions ?? []).map((x) => <option key={x} value={x}>{tx(`action.${x}`, x)}</option>)}
          </select>
          <select className="select" aria-label={t("audit.user")} value={filters.user_id} onChange={(e) => set("user_id")(e.target.value)}>
            <option value="">{t("audit.user")}: {t("common.all")}</option>
            {(facets.data?.users ?? []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
          <label className="row small muted">{t("audit.from")}<input className="input" type="date" value={filters.from} onChange={(e) => set("from")(e.target.value)} /></label>
          <label className="row small muted">{t("audit.to")}<input className="input" type="date" value={filters.to} onChange={(e) => set("to")(e.target.value)} /></label>
          {hasFilters && <Button size="sm" variant="ghost" icon={<LuFilterX />} onClick={() => { setQ(""); setFilters({ q: "", entity: "", action: "", user_id: "", from: "", to: "" }); }}>{t("audit.clear")}</Button>}
        </div>
        {list.error ? <LoadError error={list.error} onRetry={list.reload} /> : list.data && list.data.total === 0 ? (
          <Empty icon={<LuScrollText />} title={t("audit.empty")} body={hasFilters ? t("audit.emptyBody") : undefined} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th>{t("audit.time")}</th><th>{t("audit.user")}</th><th>{t("audit.action")}</th>
                <th>{t("audit.entity")}</th><th>{t("audit.record")}</th><th>{t("audit.changes")}</th>
              </tr></thead>
              {list.loading && !list.data ? <LoadingRows cols={6} rows={8} /> : (
                <tbody>
                  {(list.data?.items ?? []).map((e) => (
                    <Fragment key={e.id}>
                      <tr className={`clickable ${open === e.id ? "expanded" : ""}`} onClick={() => setOpen(open === e.id ? null : e.id)}
                        tabIndex={0} aria-expanded={open === e.id} onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setOpen(open === e.id ? null : e.id); } }}>
                        <td className="num small" style={{ whiteSpace: "nowrap" }}>{dateTime(e.occurred_at, tz)}</td>
                        <td>{e.user_name ?? "—"}</td>
                        <td><Badge tone={tone(e.action)}>{tx(`action.${e.action}`, e.action)}</Badge></td>
                        <td className="muted">{tx(`entity.${e.entity}`, e.entity)}</td>
                        <td dir="auto" style={{ textAlign: "start" }}>{e.entity === "user_site_roles" && e.record_label ? tx(`role.${e.record_label}`, e.record_label) : e.record_label ?? "—"}</td>
                        <td className="small muted">{summary(e)}</td>
                      </tr>
                      {open === e.id && (
                        <tr className="expanded"><td colSpan={6}><Changes e={e} /></td></tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}
        {list.data && list.data.total > 0 && (
          <div className="pager">
            <span>{t("common.entries", { count: number(list.data.total) })} · {t("audit.timeIn", { tz })}</span>
            <span className="spacer" />
            <span>{t("common.pageOf", { page, pages })}</span>
            <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("common.previous")}</Button>
            <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("common.next")}</Button>
          </div>
        )}
      </div>
    </>
  );
}
