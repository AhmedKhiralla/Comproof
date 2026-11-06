import { LuBuilding2, LuFilePlus2, LuLibrary, LuPlus, LuSettings, LuUsers } from "react-icons/lu";
import { Button, LoadError, useLoad } from "../components/ui";
import { get } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Link, navigate } from "../lib/router";
import { usePerms, useSession } from "../lib/session";
import { ComparisonTable, type ComparisonRow } from "./Comparisons";

function firstName(name: string) {
  return name.trim().split(/\s+/)[0] ?? name;
}

function PlatformHome() {
  const { t, number } = useI18n();
  const { data, error, reload } = useLoad(() => get<{ items: { status: string; user_count: number; site_count: number }[] }>("/api/platform/tenants"));
  const items = data?.items ?? [];
  return (
    <section className="panel" aria-labelledby="co-h">
      <div className="panel-head">
        <h2 id="co-h">{t("home.companies")}</h2><span className="spacer" />
        <Button size="sm" variant="primary" icon={<LuPlus />} onClick={() => navigate("/companies?new=1")}>{t("home.newCompany")}</Button>
      </div>
      {error ? <LoadError error={error} onRetry={reload} /> : (
        <div className="stat-line">
          <div><strong>{data ? number(items.filter((x) => x.status === "active").length) : "–"}</strong><span>{t("home.activeCompanies")}</span></div>
          <div><strong>{data ? number(items.reduce((a, x) => a + x.site_count, 0)) : "–"}</strong><span>{t("home.totalSites")}</span></div>
          <div><strong>{data ? number(items.reduce((a, x) => a + x.user_count, 0)) : "–"}</strong><span>{t("home.totalUsers")}</span></div>
        </div>
      )}
      <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}>
        <Link to="/companies" className="row"><LuBuilding2 aria-hidden />{t("companies.title")}</Link>
      </div>
    </section>
  );
}

function Queue({ title, status, empty }: { title: string; status: string; empty: string }) {
  const { data, error, reload } = useLoad(() => get<{ items: ComparisonRow[]; total: number }>(`/api/comparisons?status=${status}`), [status]);
  const { t } = useI18n();
  return (
    <section className="panel">
      <div className="panel-head"><h2>{title}</h2><span className="spacer" />
        {data && data.total > 0 && <Link to={`/comparisons`} className="small">{t("home.seeAll", { n: data.total })}</Link>}</div>
      {error ? <LoadError error={error} onRetry={reload} /> : data && data.items.length === 0
        ? <div className="panel-body muted small">{empty}</div>
        : <ComparisonTable items={(data?.items ?? []).slice(0, 8)} loading={!data} />}
    </section>
  );
}

function Setup() {
  const { t } = useI18n();
  const { me } = useSession();
  const steps = [
    { done: (me?.sites.length ?? 0) > 0, to: "/sites", icon: <LuBuilding2 />, title: t("home.setup.sites"), hint: t("home.setup.sitesHint") },
    { done: false, to: "/users", icon: <LuUsers />, title: t("home.setup.users"), hint: t("home.setup.usersHint") },
    { done: !!me?.tenant?.ai.configured, to: "/settings?tab=engine", icon: <LuSettings />, title: t("home.setup.ai"), hint: t("home.setup.aiHint") },
    { done: false, to: "/products", icon: <LuLibrary />, title: t("home.setup.library"), hint: t("home.setup.libraryHint") },
  ];
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("home.setup")}</h2></div>
      <ul className="steps">
        {steps.map((s) => (
          <li key={s.to}>
            <span className="text"><strong>{s.title}</strong><span>{s.hint}</span></span>
            <Link to={s.to} className="btn sm">{t("home.open")}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Home() {
  const { t } = useI18n();
  const { me } = useSession();
  const { startAt, siteId, has } = usePerms();
  if (!me) return null;
  const u = me.user;
  return (
    <>
      <div className="home-hello">
        <h1>{t("home.hello", { name: firstName(u.full_name) })}</h1>
        <p className="muted">{u.is_platform_admin ? t("home.leadPlatform") : t("home.leadCompany", { company: me.tenant?.name ?? "" })}</p>
      </div>
      {u.is_platform_admin ? <PlatformHome /> : (
        <div className="stack">
          {startAt(siteId) && <div className="row wrap">
            <Button variant="primary" icon={<LuFilePlus2 />} onClick={() => navigate("/comparisons/new")}>{t("nav.newComparison")}</Button>
            <Button icon={<LuLibrary />} onClick={() => navigate("/products")}>{t("nav.products")}</Button>
          </div>}
          <Queue title={has("approver") && !has("reviewer") ? t("home.awaitingSignature") : t("home.inReview")} status="review" empty={t("home.inReviewEmpty")} />
          <Queue title={t("home.running")} status="running" empty={t("home.runningEmpty")} />
          {u.is_tenant_admin && <Setup />}
        </div>
      )}
    </>
  );
}
