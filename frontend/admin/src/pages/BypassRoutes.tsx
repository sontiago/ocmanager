import { useState, type FormEvent } from "react";
import { usePatchSettings } from "../api/hooks/settings";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { checkRoute } from "../lib/routes";
import { Card } from "../ui/Card";
import { buttonClass, inputClass, primaryButtonClass } from "../ui/Field";
import { Notice } from "../ui/Notice";

const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** Конструктор правил «этот адрес — напрямую, мимо VPN» (no-route в ocserv). */
export function BypassRoutes({ saved }: { saved: string[] }) {
  const { t } = useT();
  const patch = usePatchSettings();
  const [routes, setRoutes] = useState(saved);
  const [baseline, setBaseline] = useState(saved);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Вставка списка целиком: через пробел, запятую или с новой строки.
  function add(e: FormEvent) {
    e.preventDefault();
    setNotice(null);
    const tokens = draft.split(/[\s,;]+/).filter(Boolean);
    if (tokens.length === 0) return;
    const next = [...routes];
    for (const token of tokens) {
      const checked = checkRoute(token);
      if (!checked.ok) {
        setError(t(`routes.error.${checked.reason}`, { value: token }));
        return;
      }
      if (!next.includes(checked.value)) next.push(checked.value);
    }
    setError(null);
    setRoutes(next);
    setDraft("");
  }

  function save() {
    setNotice(null);
    patch.mutate(
      { bypass_routes: routes },
      {
        onSuccess: (response) => {
          const stored = (response.runtime.bypass_routes as string[] | undefined) ?? [];
          setBaseline(stored);
          setRoutes(stored);
          setNotice(t("routes.saved"));
        },
      },
    );
  }

  return (
    <Card title={t("routes.title")}>
      <p className="mb-3 text-muted">{t("routes.hint")}</p>
      <form onSubmit={add} className="mb-3 flex gap-2">
        <input
          className={inputClass}
          aria-label={t("routes.add")}
          placeholder="85.142.247.47 или 10.0.0.0/8"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className={buttonClass}>
          {t("routes.addButton")}
        </button>
      </form>
      {error && <Notice tone="danger" text={error} />}
      {routes.length === 0 ? (
        <p className="mb-3 text-muted">{t("routes.empty")}</p>
      ) : (
        <ul className="mb-3 flex flex-wrap gap-2" aria-label={t("routes.title")}>
          {routes.map((route) => (
            <li
              key={route}
              className="flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 font-mono text-sm"
            >
              <span>{route}</span>
              <button
                type="button"
                className="px-1 text-muted hover:text-danger"
                aria-label={t("routes.remove", { value: route })}
                onClick={() => setRoutes(routes.filter((r) => r !== route))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {patch.error && <Notice tone="danger" text={errorText(patch.error, t)} />}
      <Notice text={notice} />
      <button
        type="button"
        className={primaryButtonClass}
        disabled={patch.isPending || sameList(routes, baseline)}
        onClick={save}
      >
        {t("routes.save")}
      </button>
    </Card>
  );
}
