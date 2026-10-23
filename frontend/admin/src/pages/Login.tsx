import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router";
import { isApiError } from "../api/errors";
import { useSession } from "../api/session";
import { useT } from "../i18n";
import { Field, inputClass, primaryButtonClass } from "../ui/Field";

export function LoginPage() {
  const { t } = useT();
  const { status, login } = useSession();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (status === "authed") return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login({ username, password, ...(needTotp ? { totp_code: totp } : {}) });
    } catch (err) {
      if (isApiError(err) && err.code === "totp_required") {
        setNeedTotp(true);
      } else if (isApiError(err) && err.status === 429) {
        setError(t("login.tooMany"));
      } else if (isApiError(err) && err.code === "network") {
        setError(t("login.networkError"));
      } else {
        setError(t("login.failed"));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="mx-auto mt-24 w-full max-w-sm px-4">
      <div className="mb-4 text-center text-4xl font-light">
        <b>ocm</b>anager
      </div>
      <div className="rounded-md border-t-[3px] border-t-accent bg-surface p-6 shadow-card">
      <h1 className="mb-4 text-center text-muted">{t("login.title")}</h1>
      <form onSubmit={submit} className="space-y-3">
        <Field label={t("login.username")}>
          <input
            className={inputClass}
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </Field>
        <Field label={t("login.password")}>
          <input
            className={inputClass}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        {needTotp && (
          <Field label={t("login.totp")}>
            <input
              className={inputClass}
              inputMode="numeric"
              autoComplete="one-time-code"
              value={totp}
              onChange={(e) => setTotp(e.target.value)}
              required
              autoFocus
            />
          </Field>
        )}
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
        <button type="submit" className={`${primaryButtonClass} w-full`} disabled={pending}>
          {t("login.submit")}
        </button>
      </form>
      </div>
    </main>
  );
}
