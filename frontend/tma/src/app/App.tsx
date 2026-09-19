import { BrowserRouter, Route, Routes } from "react-router";
import { ThemeProvider } from "./ThemeProvider";
import { Layout } from "./Layout";
import { PATHS } from "./routes";
import { Subscription } from "../screens/Subscription";
import { Plans } from "../screens/Plans";
import { Checkout } from "../screens/Checkout";
import { Devices } from "../screens/Devices";
import { DeviceCreate } from "../screens/DeviceCreate";
import { ErrorState } from "../ui/ErrorState";
import { Onboarding } from "../screens/Onboarding";
import { Account } from "../screens/Account";
import { Renew } from "../screens/Renew";
import { Instructions } from "../screens/Instructions";
import { DeviceSecret } from "../screens/DeviceSecret";

export function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path={PATHS.home} element={<Subscription />} />
            <Route path={PATHS.plans} element={<Plans />} />
            <Route path={PATHS.checkout} element={<Checkout />} />
            <Route path={PATHS.devices} element={<Devices />} />
            <Route path={PATHS.deviceNew} element={<DeviceCreate />} />
            <Route path={PATHS.deviceKey} element={<DeviceSecret />} />
            <Route path={PATHS.deviceGuide} element={<Instructions />} />
            <Route path={PATHS.renew} element={<Renew />} />
            <Route path={PATHS.account} element={<Account />} />
            <Route path={PATHS.onboarding} element={<Onboarding />} />
            {/* Временно: уберётся на этапе 3, когда появится граница ошибок. */}
            <Route
              path="/error"
              element={<ErrorState onRetry={() => {}} onSupport={() => {}} />}
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
