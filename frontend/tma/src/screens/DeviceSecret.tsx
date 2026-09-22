import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ROUTES } from "../app/routes";
import { useTranslation } from "../i18n/useTranslation";
import { formatCountdown } from "../lib/format";
import { openExternal } from "../telegram/links";
import { Button } from "../ui/Button";
import { Callout } from "../ui/Callout";
import { Card } from "../ui/Card";
import { CopyButton } from "../ui/CopyButton";
import { Mono } from "../ui/Mono";
import { Note } from "../ui/Note";
import { QrCode } from "../ui/QrCode";
import { SectionLabel } from "../ui/SectionLabel";
import { clearIssued, peekIssued } from "./secretVault";

export function DeviceSecret() {
  const navigate = useNavigate();
  const { t } = useTranslation();

  // Читаем один раз при первом рендере: дальше экран живёт со своей копией,
  // а хранилище можно стирать, не боясь потерять показанное.
  const [issued] = useState(peekIssued);
  const [msLeft, setMsLeft] = useState(() =>
    issued ? Date.parse(issued.download_expires_at) - Date.now() : 0,
  );

  // Экран открыли напрямую — перезагрузкой или вставленной ссылкой.
  // Показывать нечего, и пустота здесь пугает сильнее, чем возврат в список.
  useEffect(() => {
    if (!issued) navigate(ROUTES.devices, { replace: true });
  }, [issued, navigate]);

  // Секрет живёт ровно столько, сколько открыт этот экран.
  useEffect(() => clearIssued, []);

  useEffect(() => {
    if (!issued) return;
    const expiresAt = Date.parse(issued.download_expires_at);
    const timer = setInterval(() => setMsLeft(expiresAt - Date.now()), 1000);
    return () => clearInterval(timer);
  }, [issued]);

  if (!issued) return null;

  const expired = msLeft <= 0;

  return (
    <div>
      <Callout>
        <span className="text-[12.5px] leading-[1.4]">
          {t("deviceSecret.warning")}
        </span>
      </Callout>

      <SectionLabel>{t("deviceSecret.password")}</SectionLabel>
      <Card className="flex items-center justify-between gap-2.5 p-4">
        <Mono className="text-[19px] tracking-[0.05em]">
          {issued.p12_password}
        </Mono>
        <CopyButton value={issued.p12_password} />
      </Card>

      {expired ? (
        // Пароль остаётся верным — истекла только ссылка на файл.
        <Note tone="danger" className="px-1 pt-3.5">
          {t("deviceSecret.expired")}
        </Note>
      ) : (
        <>
          <Card className="mt-3 flex items-center gap-4 p-4">
            <QrCode
              value={issued.download_url}
              label={t("deviceSecret.qrHint")}
            />
            <Note>{t("deviceSecret.qrHint")}</Note>
          </Card>

          <Button
            className="mt-[18px]"
            onClick={() => openExternal(issued.download_url)}
          >
            {t("deviceSecret.download")}
          </Button>

          <Note className="px-1 pt-2 text-center">
            {t("deviceSecret.expiresIn", { time: formatCountdown(msLeft) })}
          </Note>
        </>
      )}

      <Button
        variant="secondary"
        className="mt-2.5"
        onClick={() => navigate(ROUTES.deviceGuide(issued.device.platform))}
      >
        {t("deviceSecret.next")}
      </Button>
    </div>
  );
}
