import { useState, type FormEvent, type ReactNode } from "react";
import { useCreatePlan, useUpdatePlan } from "../api/hooks/plans";
import type { S } from "../api/types";
import { useT } from "../i18n";
import { errorText } from "../lib/errors";
import { EMPTY_FORM, productsValid, toCreate, toForm, toPatch, type PlanForm } from "../lib/planForm";
import { buttonClass, Field, inputClass, primaryButtonClass } from "../ui/Field";
import { Modal } from "../ui/Modal";
import { Notice } from "../ui/Notice";

export function PlanFormDialog({
  plan,
  onClose,
}: {
  plan: S<"PlanOut"> | null; // null — создание
  onClose(): void;
}) {
  const { t } = useT();
  const create = useCreatePlan();
  const update = useUpdatePlan();
  const [form, setForm] = useState<PlanForm>(plan ? toForm(plan) : EMPTY_FORM);
  const editing = plan !== null;
  const mutation = editing ? update : create;
  const jsonOk = productsValid(form);

  const bind = (key: keyof PlanForm) => ({
    value: String(form[key]),
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!jsonOk) return;
    if (plan) {
      const patch = toPatch(plan, form);
      if (Object.keys(patch).length === 0) return onClose();
      update.mutate({ code: plan.code, patch }, { onSuccess: onClose });
    } else {
      create.mutate(toCreate(form), { onSuccess: onClose });
    }
  }

  const text = (key: keyof PlanForm, label: string, extra: { type?: string; disabled?: boolean; required?: boolean; error?: ReactNode } = {}) => (
    <Field label={label}>
      <input className={inputClass} type={extra.type ?? "text"} disabled={extra.disabled} required={extra.required} {...bind(key)} />
    </Field>
  );

  return (
    <Modal title={editing ? t("plans.edit") : t("plans.new")} onClose={onClose}>
      <form onSubmit={submit} className="max-h-[70vh] space-y-3 overflow-y-auto pr-1">
        {text("code", t("plans.code"), { disabled: editing, required: true })}
        {text("nameRu", t("plans.nameRu"), { required: true })}
        {text("nameEn", t("plans.nameEn"), { required: true })}
        {text("descRu", t("plans.descRu"))}
        {text("descEn", t("plans.descEn"))}
        {text("durationDays", t("plans.duration"), { type: "number", required: true })}
        {text("deviceLimit", t("plans.deviceLimit"), { type: "number", required: true })}
        {text("trafficGb", t("plans.trafficGb"), { type: "number" })}
        {text("speedKbps", t("plans.speedKbps"), { type: "number" })}
        {text("price", t("plans.price"), { type: "number", required: true })}
        {text("currency", t("plans.currency"), { required: true })}
        <Field label={t("plans.products")} error={jsonOk ? null : t("plans.productsInvalid")}>
          <textarea className={inputClass} rows={2} {...bind("products")} />
        </Field>
        {text("sortOrder", t("plans.sortOrder"), { type: "number" })}
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.isActive}
            onChange={(e) => setForm({ ...form, isActive: e.target.checked })}
          />
          {t("plans.active")}
        </label>
        {mutation.error && <Notice tone="danger" text={errorText(mutation.error, t)} />}
        <div className="flex justify-end gap-2">
          <button type="button" className={buttonClass} onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="submit" className={primaryButtonClass} disabled={mutation.isPending}>
            {t("common.save")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
