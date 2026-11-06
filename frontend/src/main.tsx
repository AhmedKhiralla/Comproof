import { StrictMode, type ReactElement } from "react";
import { createRoot } from "react-dom/client";
import { LuCompass, LuShieldCheck } from "react-icons/lu";
import "./styles.css";
import { Shell } from "./components/Shell";
import { Button, Empty, ToastProvider } from "./components/ui";
import { I18nProvider, useI18n } from "./lib/i18n";
import { match, navigate, usePath } from "./lib/router";
import { SessionProvider, useSession } from "./lib/session";
import { ThemeProvider } from "./lib/theme";
import { Audit } from "./pages/Audit";
import { ChangePasswordPage, ForcedPasswordChange } from "./pages/ChangePassword";
import { Companies } from "./pages/Companies";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Settings } from "./pages/Settings";
import { Sites } from "./pages/Sites";
import { Users } from "./pages/Users";
import { Logo } from "./components/Logo";
import { ComparisonView } from "./pages/ComparisonView";
import { Comparisons, NewComparison } from "./pages/Comparisons";
import { ComponentPage, ProductPage, Products } from "./pages/Products";

function NotFound() {
  const { t } = useI18n();
  return <div className="panel"><Empty icon={<LuCompass />} title={t("notFound.title")} body={t("notFound.body")}
    action={<Button onClick={() => navigate("/")}>{t("notFound.home")}</Button>} /></div>;
}

function Forbidden() {
  const { t } = useI18n();
  return <div className="panel"><Empty icon={<LuShieldCheck />} title={t("forbidden.title")} body={t("forbidden.body")}
    action={<Button onClick={() => navigate("/")}>{t("notFound.home")}</Button>} /></div>;
}

function Routes() {
  const path = usePath();
  const { me } = useSession();
  if (!me) return null;
  const platform = me.user.is_platform_admin;
  const admin = me.user.is_tenant_admin;
  const gate = (ok: boolean, el: ReactElement) => (ok ? el : <Forbidden />);
  const tenantUser = !!me.tenant;
  let m: Record<string, string> | null;
  if (path === "/comparisons/new") return gate(tenantUser, <NewComparison key={window.location.search} />);
  if ((m = match("/comparisons/:id", path))) return gate(tenantUser, <ComparisonView key={m.id} comparisonId={m.id} />);
  if ((m = match("/products/:id", path))) return gate(tenantUser, <ProductPage key={m.id} productId={m.id} />);
  if ((m = match("/components/:id", path))) return gate(tenantUser, <ComponentPage key={m.id} componentId={m.id} />);
  switch (path) {
    case "/comparisons": return gate(tenantUser, <Comparisons />);
    case "/products": return gate(tenantUser, <Products />);
    case "/":
    case "/login": return <Home />;
    case "/companies": return gate(platform, <Companies />);
    case "/users": return gate(admin, <Users />);
    case "/sites": return gate(admin, <Sites />);
    case "/settings": return gate(admin, <Settings />);
    case "/audit": return gate(platform || admin, <Audit />);
    case "/account/password": return <ChangePasswordPage />;
    default: return <NotFound />;
  }
}

function App() {
  const { status, me } = useSession();
  if (status === "loading") return <div className="boot" aria-busy="true"><Logo height={40} /></div>;
  if (status === "signed-out" || !me) return <Login />;
  if (me.user.must_change_password) return <ForcedPasswordChange />;
  return <Shell><Routes /></Shell>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <ToastProvider>
          <SessionProvider>
            <App />
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
);
