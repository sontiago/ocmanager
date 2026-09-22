/**
 * Возвращает false вместо исключения: копирование — удобство, а не условие
 * работы экрана. В Telegram на iOS Clipboard API доступен только по жесту
 * пользователя, а в небезопасном контексте отсутствует вовсе.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
