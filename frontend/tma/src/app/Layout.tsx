import { Outlet, useLocation } from "react-router";
import { Header } from "./Header";
import { TabBar } from "./TabBar";
import { hasTabBar, titleFor } from "./routes";

export function Layout() {
  const { pathname } = useLocation();
  const showTabBar = hasTabBar(pathname);

  return (
    <div className="flex h-full flex-col bg-bg text-ink">
      <Header title={titleFor(pathname)} />

      {/* Скроллит именно эта область, а не body: скролл на body
          внутри Telegram срабатывает как жест закрытия приложения. */}
      <main
        className={`flex-1 overflow-y-auto px-4 ${
          // Когда таб-бара нет, нижний край экрана принадлежит контенту —
          // значит, safe-area устройства обязан учесть он сам.
          showTabBar ? "pb-[22px]" : "pb-[calc(22px+var(--safe-bottom))]"
        }`}
      >
        <Outlet />
      </main>

      {showTabBar && <TabBar />}
    </div>
  );
}
