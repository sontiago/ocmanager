import type { ReactNode } from "react";

interface HeroProps {
  children: ReactNode;
  /** Мелкий хвост: «дней», «/ 100 ГБ». */
  tail?: ReactNode;
  size?: "xl" | "lg" | "md" | "sm";
}

const SIZES = {
  xl: "text-[64px] tracking-[-0.045em]", // срок на главном
  lg: "text-[56px] tracking-[-0.045em]", // сумма на оплате
  md: "text-[46px] tracking-[-0.04em]", // сумма на продлении
  sm: "text-[40px] tracking-[-0.04em]", // заголовок онбординга
};

const TAIL_SIZES = {
  xl: "text-2xl",
  lg: "text-xl",
  md: "text-lg",
  sm: "text-base",
};

export function Hero({ children, tail, size = "xl" }: HeroProps) {
  return (
    <div className={`my-1.5 font-extrabold leading-none ${SIZES[size]}`}>
      {children}
      {tail && (
        <span className={`${TAIL_SIZES[size]} tracking-[-0.01em]`}>
          {" "}
          {tail}
        </span>
      )}
    </div>
  );
}
