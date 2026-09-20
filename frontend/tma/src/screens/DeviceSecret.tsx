import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import QRCode from "qrcode";
import { ROUTES } from "../app/routes";
import { PLATFORM_INFO, SECRET, type Platform } from "./demo";
import { formatCountdown } from "../lib/format";
import { Button } from "../ui/Button";
import { Callout } from "../ui/Callout";
import { Card } from "../ui/Card";
import { Note } from "../ui/Note";
import { SectionLabel } from "../ui/SectionLabel";

const T = {
  once: "Пароль и ссылка показываются один раз",
  expired: "Ссылка истекла",
  passwordLabel: "ПАРОЛЬ К ФАЙЛУ КЛЮЧА",
  copy: "Копировать",
  copied: "Скопировано",
  qrNote:
    "Сканируйте с телефона, чтобы открыть ссылку там, где будет стоять ключ. Ссылка одноразовая: после первого скачивания перестаёт работать.",
  download: "Скачать ключ .p12",
  guide: (os: string) => `Инструкция для ${os}`,
  note: "Ту же ссылку бот отправил сообщением. Потерянный ключ не восстанавливается — выпускается новый, старый отзывается.",
};

export function DeviceSecret() {
  const navigate = useNavigate();
  const { platform } = useParams<{ platform: Platform }>();
  const info = PLATFORM_INFO[platform ?? "ios"];

  const [secondsLeft, setSecondsLeft] = useState(SECRET.ttl_seconds);
  const [qr, setQr] = useState<string>("");
  const [copied, setCopied] = useState(false);

  // Таймер: одна секунда, останавливается на нуле.
  useEffect(() => {
    const id = setInterval(() => {
      setSecondsLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    QRCode.toDataURL(SECRET.download_url, { margin: 1, width: 236 }).then(
      setQr,
    );
  }, []);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(SECRET.password);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const expired = secondsLeft === 0;

  return (
    <div>
      <Callout className="flex items-center justify-between gap-3">
        <span className="text-[12.5px] leading-[1.4]">
          {expired ? T.expired : T.once}
        </span>
        <span className="text-[19px] font-extrabold tabular-nums text-accent-700">
          {formatCountdown(secondsLeft * 1000)}
        </span>
      </Callout>

      <SectionLabel>{T.passwordLabel}</SectionLabel>
      <Card className="flex items-center justify-between gap-2.5 p-4">
        <code className="font-mono text-[19px] tracking-[0.05em]">
          {SECRET.password}
        </code>
        <button
          type="button"
          onClick={handleCopy}
          className="shrink-0 cursor-pointer rounded-full bg-fill px-3 py-1.5 text-[12.5px] hover:bg-fill-strong"
        >
          {copied ? T.copied : T.copy}
        </button>
      </Card>

      <Card className="mt-3 flex items-center gap-4 p-4">
        <div className="grid size-[118px] shrink-0 place-items-center overflow-hidden rounded-[20px] bg-white">
          {qr && <img src={qr} alt="" className="size-full" />}
        </div>
        <Note>{T.qrNote}</Note>
      </Card>

      <Button className="mt-[18px]" onClick={() => console.log("скачать .p12")}>
        {T.download}
      </Button>
      <Button
        variant="secondary"
        className="mt-2.5"
        onClick={() => navigate(ROUTES.deviceGuide(platform ?? "ios"))}
      >
        {T.guide(info.badge === "iOS" ? "iOS" : info.label)}
      </Button>

      <Note className="px-1 pt-3">{T.note}</Note>
    </div>
  );
}
