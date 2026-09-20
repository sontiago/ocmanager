import { backButton } from "@telegram-apps/sdk-react";
import { useEffect } from "react";
import { useNavigate } from "react-router";

/**
 * Управляет нативной кнопкой «Назад» Telegram.
 * @param target путь, на который уводит кнопка; null — кнопку скрыть.
 *
 * Переход делается по явному пути, а не через history.back(): после
 * возврата из внешней checkout-страницы история браузера непредсказуема.
 */
export function useBackButton(target: string | null): void {
  const navigate = useNavigate();

  useEffect(() => {
    if (!backButton.isMounted()) return;

    if (target === null) {
      if (backButton.hide.isAvailable()) backButton.hide();
      return;
    }

    if (backButton.show.isAvailable()) backButton.show();

    const off = backButton.onClick.isAvailable()
      ? backButton.onClick(() => {
          void navigate(target);
        })
      : undefined;

    return () => {
      off?.();
      if (backButton.hide.isAvailable()) backButton.hide();
    };
  }, [target, navigate]);
}
