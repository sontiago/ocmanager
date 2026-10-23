import { Navigate, Outlet, useLocation } from "react-router";
import { useSession } from "../api/session";
import { useT } from "../i18n";

export function RequireAuth() {
  const { status } = useSession();
  const { t } = useT();
  const location = useLocation();

  if (status === "loading") return <p className="p-6 text-muted">{t("common.loading")}</p>;
  if (status === "anon") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}
