import QRCode from "qrcode";
import { useEffect, useState } from "react";

export function QrCode({
  value,
  size = 118,
  label,
}: {
  value: string;
  size?: number;
  label: string;
}) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    void QRCode.toDataURL(value, {
      width: size * 2, // экран ретиновый: рисуем вдвое крупнее
      margin: 1,
      errorCorrectionLevel: "M",
      // Цвета зафиксированы: код обязан остаться контрастным в тёмной теме,
      // иначе камера его не прочитает.
      color: { dark: "#000000", light: "#ffffff" },
    }).then((url) => {
      if (!cancelled) setDataUrl(url);
    });

    return () => {
      cancelled = true;
    };
  }, [value, size]);

  return (
    <div
      className="grid shrink-0 place-items-center overflow-hidden rounded-[20px] bg-white"
      style={{ width: size, height: size }}
    >
      {dataUrl && <img src={dataUrl} alt={label} className="size-full" />}
    </div>
  );
}
