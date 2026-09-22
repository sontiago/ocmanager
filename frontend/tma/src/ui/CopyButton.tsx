import { useEffect, useState } from "react";
import { useTranslation } from "../i18n/useTranslation";
import { copyToClipboard } from "../lib/clipboard";
import { haptic } from "../telegram/haptics";

/** Пилюля «Скопировать» рядом со значением: пароль, адрес сервера. */
export function CopyButton({ value }: { value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  // Подтверждение живёт две секунды: дольше — и оно врёт про «только что».
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <button
      type="button"
      onClick={() => {
        void copyToClipboard(value).then((ok) => {
          if (!ok) return;
          haptic.notification("success");
          setCopied(true);
        });
      }}
      className="shrink-0 cursor-pointer rounded-full bg-fill px-3 py-1.5 text-[12.5px] hover:bg-fill-strong"
    >
      {copied ? t("common.copied") : t("common.copy")}
    </button>
  );
}
