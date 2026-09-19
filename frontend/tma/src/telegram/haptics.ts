import { hapticFeedback } from "@telegram-apps/sdk-react";

type ImpactStyle = "light" | "medium" | "heavy";
type NotificationType = "success" | "error" | "warning";

export const haptic = {
  /** Нажатие на кнопку, переключение. */
  impact(style: ImpactStyle = "light"): void {
    if (hapticFeedback.impactOccurred.isAvailable()) {
      hapticFeedback.impactOccurred(style);
    }
  },
  /** Исход операции: ключ выпущен, устройство отозвано, ошибка. */
  notification(type: NotificationType): void {
    if (hapticFeedback.notificationOccurred.isAvailable()) {
      hapticFeedback.notificationOccurred(type);
    }
  },
  /** Смена выбора в списке. */
  selection(): void {
    if (hapticFeedback.selectionChanged.isAvailable()) {
      hapticFeedback.selectionChanged();
    }
  },
};
