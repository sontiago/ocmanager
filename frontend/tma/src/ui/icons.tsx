import type { ReactNode, SVGProps } from "react";

type IconProps = Omit<SVGProps<SVGSVGElement>, "children"> & { size?: number };

function Icon({ size = 24, ...rest }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="block"
      {...rest}
    />
  );
}

/** Продлить, автопродление */
export const IconRenew = (p: IconProps) => (
  <Icon {...p}>
    <path d="M20.5 12a8.5 8.5 0 1 1-2.9-6.4" />
    <path d="M20.5 3.5v5h-5" />
  </Icon>
);

/** Добавить устройство */
export const IconPlus = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);

/** Тарифы */
export const IconGrid = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.8" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="1.8" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1.8" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="1.8" />
  </Icon>
);

/** Помощь */
export const IconHelp = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.7 9.4a2.4 2.4 0 0 1 4.6.8c0 1.6-2.3 2-2.3 3.6" />
    <path d="M12 17.3h.01" />
  </Icon>
);

/** Устройства */
export const IconPhone = (p: IconProps) => (
  <Icon {...p}>
    <rect x="6" y="2.5" width="12" height="19" rx="3.5" />
    <path d="M11 18.6h2" />
  </Icon>
);

/** Сменить тариф */
export const IconArrowUp = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 19V6" />
    <path d="M6 11.5 12 5.5l6 6" />
  </Icon>
);

/** Подписка */
export const IconCard = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2.5" y="5" width="19" height="14" rx="3.5" />
    <path d="M2.5 10h19" />
  </Icon>
);

/** Ещё. Единственная с заливкой вместо обводки. */
export const IconMore = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
    <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
  </Icon>
);
