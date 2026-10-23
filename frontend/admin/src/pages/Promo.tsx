import { Fragment, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useCreatePromo, usePatchPromo, usePromoCodes, useRedemptions } from "../api/hooks/promo";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { dayStartUtc } from "../lib/dates";
import { errorText } from "../lib/errors";
import { formatDateTime } from "../lib/format";
import { buttonClass, Field, inputClass, primaryButtonClass } from "../ui/Field";
import { Modal } from "../ui/Modal";
import { Notice } from "../ui/Notice";
import { StatusBadge } from "../ui/StatusBadge";

function PromoForm({ onClose }: { onClose(): void }) {
  const { t } = useT();
  const create = useCreatePromo();
  const [code, setCode] = useState("");
  const [kind, setKind] = useState<"days" | "traffic">("days");
  const [value, setValue] = useState("");
  const [maxUses, setMaxUses] = useState("");
  const [until, setUntil] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    const expires = dayStartUtc(until, 1);
    create.mutate(
      {
        code: code.trim(),
        kind,
        value: Number(value),
        ...(maxUses ? { max_uses: Number(maxUses) } : {}),
        ...(expires ? { expires_at: expires } : {}),
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal title={t("promo.new")} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Field label={t("promo.code")}>
          <input className={inputClass} value={code} onChange={(e) => setCode(e.target.value)} required />
        </Field>
        <Field label={t("promo.reward")}>
          <select
            className={inputClass}
            value={kind}
            onChange={(e) => setKind(e.target.value as "days" | "traffic")}
          >
            <option value="days">{t("promo.kindDays")}</option>
            <option value="traffic">{t("promo.kindTraffic")}</option>
          </select>
        </Field>
        <Field label={t("promo.value")}>
          <input className={inputClass} type="number" min={1} value={value} onChange={(e) => setValue(e.target.value)} required />
        </Field>
        <Field label={t("promo.maxUses")}>
          <input className={inputClass} type="number" min={1} value={maxUses} onChange={(e) => setMaxUses(e.target.value)} />
        </Field>
        <Field label={t("promo.until")}>
          <input className={inputClass} type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
        </Field>
        {create.error && <Notice tone="danger" text={errorText(create.error, t("common.error"))} />}
        <div className="flex justify-end gap-2">
          <button type="button" className={buttonClass} onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="submit" className={primaryButtonClass} disabled={create.isPending}>
            {t("promo.create")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Redemptions({ id }: { id: number }) {
  const { t } = useT();
  const { data, isPending } = useRedemptions(id);
  if (isPending) return <p className="text-muted">{t("common.loading")}</p>;
  if (!data?.length) return <p className="text-muted">{t("promo.noRedemptions")}</p>;
  return (
    <ul className="space-y-1 text-sm">
      {data.map((r) => (
        <li key={r.id} className="flex gap-3">
          <Link to={`/clients/${r.client_id}`} className="text-accent">
            {r.client_name}
          </Link>
          <span className="text-muted">{formatDateTime(r.redeemed_at)}</span>
        </li>
      ))}
    </ul>
  );
}

export function PromoPage() {
  const { t } = useT();
  const query = usePromoCodes();
  const patch = usePatchPromo();
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  const reward = (p: S<"PromoOut">) =>
    p.kind === "days" ? t("promo.plusDays", { n: p.value }) : t("promo.plusGb", { n: p.value });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-normal">{t("nav.promo")}</h1>
        <button className={primaryButtonClass} onClick={() => setCreating(true)}>
          {t("promo.new")}
        </button>
      </div>
      {patch.error && <Notice tone="danger" text={errorText(patch.error, t("common.error"))} />}
      {query.error && <Notice tone="danger" text={t("common.error")} />}
      {query.isPending && <p className="text-muted">{t("common.loading")}</p>}
      {query.data && (
        <div className="overflow-x-auto rounded-md bg-surface shadow-card">
          <table className="w-full text-left">
            <thead className="border-b-2 border-border">
              <tr>
                {["promo.code", "promo.reward", "promo.used", "promo.until", "clients.status", ""].map(
                  (h) => (
                    <th key={h} className="px-3 py-2 font-bold">
                      {h && t(h)}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {query.data.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-muted">
                    {t("promo.empty")}
                  </td>
                </tr>
              )}
              {query.data.map((p) => (
                <Fragment key={p.id}>
                  <tr className="border-t border-border">
                    <td className="px-3 py-2 font-mono">{p.code}</td>
                    <td className="px-3 py-2">{reward(p)}</td>
                    <td className="px-3 py-2">
                      {p.uses} / {p.max_uses ?? "∞"}
                    </td>
                    <td className="px-3 py-2">{p.expires_at ? formatDateTime(p.expires_at) : "—"}</td>
                    <td className="px-3 py-2">
                      <StatusBadge
                        tone={p.is_active ? "ok" : "neutral"}
                        label={p.is_active ? t("promo.active") : t("promo.inactive")}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex justify-end gap-2">
                        <button
                          className={buttonClass}
                          aria-label={t("promo.redemptionsOf", { code: p.code })}
                          onClick={() => setOpen(open === p.id ? null : p.id)}
                        >
                          {t("promo.redemptions")}
                        </button>
                        <button
                          className={buttonClass}
                          aria-label={t(p.is_active ? "promo.switchOff" : "promo.switchOn", { code: p.code })}
                          disabled={patch.isPending}
                          onClick={() => patch.mutate({ id: p.id, patch: { is_active: !p.is_active } })}
                        >
                          {p.is_active ? t("promo.off") : t("promo.on")}
                        </button>
                      </span>
                    </td>
                  </tr>
                  {open === p.id && (
                    <tr>
                      <td colSpan={6} className="bg-black/[0.03] px-3 py-2">
                        <Redemptions id={p.id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <PromoForm onClose={() => setCreating(false)} />}
    </div>
  );
}
