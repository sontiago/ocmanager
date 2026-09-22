import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";

import { Skeleton } from "../ui/Skeleton";
import { Layout } from "./Layout";
import { PATHS, ROUTES } from "./routes";

export { ROUTES, PATHS };

// Экраны грузятся лениво: Mini App открывается на мобильной сети, и первый
// экран не должен ждать кода инструкций, QR-генератора и экрана оплаты.
// Экспорт именованный, поэтому переупаковываем в default для lazy().
const Subscription = lazy(() =>
  import("../screens/Subscription").then((m) => ({ default: m.Subscription })),
);
const Plans = lazy(() =>
  import("../screens/Plans").then((m) => ({ default: m.Plans })),
);
const Checkout = lazy(() =>
  import("../screens/Checkout").then((m) => ({ default: m.Checkout })),
);
const Devices = lazy(() =>
  import("../screens/Devices").then((m) => ({ default: m.Devices })),
);
const DeviceCreate = lazy(() =>
  import("../screens/DeviceCreate").then((m) => ({ default: m.DeviceCreate })),
);
const DeviceSecret = lazy(() =>
  import("../screens/DeviceSecret").then((m) => ({ default: m.DeviceSecret })),
);
const Instructions = lazy(() =>
  import("../screens/Instructions").then((m) => ({ default: m.Instructions })),
);
const Renew = lazy(() =>
  import("../screens/Renew").then((m) => ({ default: m.Renew })),
);
const Account = lazy(() =>
  import("../screens/Account").then((m) => ({ default: m.Account })),
);
const Onboarding = lazy(() =>
  import("../screens/Onboarding").then((m) => ({ default: m.Onboarding })),
);

function ScreenFallback() {
  return (
    <div className="space-y-3 pt-4">
      <Skeleton className="h-6 w-1/3" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route
          path={PATHS.home}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <Subscription />
            </Suspense>
          }
        />
        <Route
          path={PATHS.plans}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <Plans />
            </Suspense>
          }
        />
        <Route
          path={PATHS.checkout}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <Checkout />
            </Suspense>
          }
        />
        <Route
          path={PATHS.devices}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <Devices />
            </Suspense>
          }
        />
        <Route
          path={PATHS.deviceNew}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <DeviceCreate />
            </Suspense>
          }
        />
        <Route
          path={PATHS.deviceKey}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <DeviceSecret />
            </Suspense>
          }
        />
        <Route
          path={PATHS.deviceGuide}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <Instructions />
            </Suspense>
          }
        />
        <Route
          path={PATHS.renew}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <Renew />
            </Suspense>
          }
        />
        <Route
          path={PATHS.account}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <Account />
            </Suspense>
          }
        />
        <Route
          path={PATHS.onboarding}
          element={
            <Suspense fallback={<ScreenFallback />}>
              <Onboarding />
            </Suspense>
          }
        />
      </Route>

      {/* Неизвестный путь — на главную, а не белый экран. */}
      <Route path="*" element={<Navigate to={ROUTES.home} replace />} />
    </Routes>
  );
}
