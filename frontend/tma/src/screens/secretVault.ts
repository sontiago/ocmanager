import type { IssuedDevice } from "../api/types";

/**
 * Пароль от .p12 и одноразовая ссылка живут только в памяти модуля —
 * ровно столько, сколько открыта вкладка.
 *
 * Не URL: адрес попадает в историю и в логи прокси.
 * Не location.state: history.state сериализуется и переживает перезагрузку.
 * Не кэш React Query: виден в девтулзах и переживает навигацию.
 * Не storage: переживает закрытие приложения.
 *
 * peek() намеренно не стирает значение: React в StrictMode вызывает
 * инициализатор useState дважды, и стирающее чтение потеряло бы секрет
 * на первом же рендере. Стирание — явное, при размонтировании экрана.
 */
let held: IssuedDevice | null = null;

export function stashIssued(value: IssuedDevice): void {
  held = value;
}

export function peekIssued(): IssuedDevice | null {
  return held;
}

export function clearIssued(): void {
  held = null;
}
