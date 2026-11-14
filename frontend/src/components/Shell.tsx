import { useEffect, useState, type ReactNode } from "react";
import {
  LuBuilding2, LuChevronDown, LuFilePlus2, LuFileSearch, LuHouse, LuKeyRound, LuLanguages, LuLibrary, LuLogOut,
  LuMapPin, LuMenu, LuMonitor, LuMoon, LuScrollText, LuSettings, LuSun, LuUsers, LuX,
} from "react-icons/lu";
import { useI18n } from "../lib/i18n";
import { Link, navigate, usePath } from "../lib/router";
import { useSession } from "../lib/session";
import { useTheme } from "../lib/theme";
import type { StringKey } from "../lib/strings";
import { Button, Menu, MenuItem, initials } from "./ui";
import { Logo } from "./Logo";

type NavItem = { to?: string; label: StringKey; icon: ReactNode; phase?: number };
type NavGroup = { title?: StringKey; items: NavItem[] };

function groupsFor(isPlatform: boolean, isAdmin: boolean): NavGroup[] {
  if (isPlatform) {
    return [
      { items: [{ to: "/", label: "nav.home", icon: <LuHouse /> }] },
      { title: "nav.platform", items: [
        { to: "/companies", label: "nav.companies", icon: <LuBuilding2 /> },
        { to: "/audit", label: "nav.audit", icon: <LuScrollText /> },
      ] },
    ];
  }
  const groups: NavGroup[] = [
    { items: [{ to: "/", label: "nav.home", icon: <LuHouse /> }] },
    { title: "nav.work", items: [
      { to: "/comparisons", label: "nav.comparisons", icon: <LuFileSearch /> },
      { to: "/comparisons/new", label: "nav.newComparison", icon: <LuFilePlus2 /> },
    ] },
    { title: "nav.library", items: [
      { to: "/products", label: "nav.products", icon: <LuLibrary /> },
    ] },
  ];
  if (isAdmin) {
    groups.push({ title: "nav.admin", items: [
      { to: "/users", label: "nav.users", icon: <LuUsers /> },
      { to: "/sites", label: "nav.sites", icon: <LuMapPin /> },
      { to: "/settings", label: "nav.settings", icon: <LuSettings /> },
      { to: "/audit", label: "nav.audit", icon: <LuScrollText /> },
    ] });
  }
  return groups;
}

function isCurrent(path: string, to: string) {
  if (to === "/comparisons" && path === "/comparisons/new") return false;
  return to === "/" ? path === "/" : path === to || path.startsWith(to + "/");
}

export function Shell({ children }: { children: ReactNode }) {
  const { t, lang } = useI18n();
  const { me, siteId, setSiteId, signOut, savePreference } = useSession();
  const { choice } = useTheme();
  const path = usePath();
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => { setNavOpen(false); }, [path]);
  if (!me) return null;
  const u = me.user;
  const groups = groupsFor(u.is_platform_admin, u.is_tenant_admin);
  const roleLabel = u.is_platform_admin ? t("user.platformAdmin") : u.is_tenant_admin ? t("user.companyAdmin") : me.tenant?.name ?? "";

  return (
    <div className={`shell ${navOpen ? "nav-open" : ""}`}>
      <aside className="sidebar" aria-label={t("app.name")}>
        <div className="brand-block">
          <Logo height={30} />
          <div className="product"><strong>Comproof</strong><span>{u.is_platform_admin ? t("shell.platformScope") : me.tenant?.name}</span></div>
        </div>
        <nav className="nav">
          {groups.map((g, i) => (
            <div className="nav-group" key={i}>
              {g.title && <div className="nav-group-title">{t(g.title)}</div>}
              {g.items.map((item) => item.to ? (
                <Link key={item.label} to={item.to} className="nav-item" aria-current={isCurrent(path, item.to) ? "page" : undefined}>
                  {item.icon}<span className="label">{t(item.label)}</span>
                </Link>
              ) : (
                <span key={item.label} className="nav-item disabled" aria-disabled="true">
                  {item.icon}<span className="label" title={t(item.label)}>{t(item.label)}</span><span className="later">{t("nav.phase", { n: item.phase ?? 0 })}</span>
                </span>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">{t("shell.version", { v: "1.4.0" })} · Comp11 Labs</div>
      </aside>
      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}

      <div className="main">
        <header className="topbar">
          <Button className="menu-btn" variant="ghost" iconOnly onClick={() => setNavOpen((o) => !o)}
            aria-label={navOpen ? t("nav.closeMenu") : t("nav.openMenu")} icon={navOpen ? <LuX /> : <LuMenu />} />
          {!u.is_platform_admin && (
            <div className="site-switch">
              <label htmlFor="site-switch" className="small muted">{t("shell.site")}</label>
              {me.sites.length ? (
                <select id="site-switch" className="select" value={siteId ?? ""} onChange={(e) => setSiteId(e.target.value)}>
                  {me.sites.map((s) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}
                </select>
              ) : <span className="small subtle">{t("shell.noSites")}</span>}
            </div>
          )}
          <span className="spacer" />
          <Menu trigger={(p) => (
            <button type="button" className="user-btn" {...p} aria-label={t("user.menu")}>
              <span className="avatar" aria-hidden>{initials(u.full_name).toUpperCase()}</span>
              <span className="who"><strong>{u.full_name}</strong><span>{roleLabel}</span></span>
              <LuChevronDown aria-hidden className="subtle" />
            </button>
          )}>
            {(close) => (
              <>
                <div className="menu-label">{u.email}</div>
                <div className="menu-sep" />
                <div className="menu-label">{t("common.language")}</div>
                {([["en", "English"], ["fr", "Français"], ["ar", "العربية"]] as const).filter(([l]) => l !== lang).map(([l, label]) => (
                  <MenuItem key={l} icon={<LuLanguages />} onClick={() => { savePreference({ language: l }); close(); }}>{label}</MenuItem>
                ))}
                <div className="menu-label">{t("theme.label")}</div>
                <div style={{ padding: "2px 6px 6px" }}>
                  <div className="seg" role="group" aria-label={t("theme.label")}>
                    <button type="button" aria-pressed={choice === "light"} onClick={() => savePreference({ theme: "light" })}><LuSun />{t("theme.light")}</button>
                    <button type="button" aria-pressed={choice === "dark"} onClick={() => savePreference({ theme: "dark" })}><LuMoon />{t("theme.dark")}</button>
                    <button type="button" aria-pressed={choice === "system"} onClick={() => savePreference({ theme: "system" })}><LuMonitor />{t("theme.system")}</button>
                  </div>
                </div>
                <div className="menu-sep" />
                <MenuItem icon={<LuKeyRound />} onClick={() => { close(); navigate("/account/password"); }}>{t("user.changePassword")}</MenuItem>
                <MenuItem icon={<LuLogOut />} onClick={() => { close(); signOut(); navigate("/", true); }}>{t("user.signOut")}</MenuItem>
              </>
            )}
          </Menu>
        </header>
        <main className="content" id="main">{children}</main>
      </div>
    </div>
  );
}
