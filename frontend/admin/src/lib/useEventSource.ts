import { useCallback, useEffect, useState } from "react";

export type StreamState = "idle" | "connecting" | "open" | "error";

/**
 * Поток SSE построчно. `url = null` — не подключаться. При обрыве соединение закрывается,
 * а не переподключается само: браузерный реконнект повторил бы `tail` и задвоил строки.
 * Хранятся последние `max` строк.
 */
export function useEventSource(url: string | null, opts: { max: number }) {
  const { max } = opts;
  const [lines, setLines] = useState<string[]>([]);
  const [state, setState] = useState<StreamState>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (url === null) {
      setState("idle");
      return;
    }
    setState("connecting");
    setError(null);
    setLines([]);
    const source = new EventSource(url);
    source.addEventListener("open", () => setState("open"));
    source.addEventListener("message", (e) => {
      const line = (e as MessageEvent<string>).data;
      setLines((prev) => [...prev, line].slice(-max));
    });
    source.addEventListener("error", (e) => {
      // Именованное `event: error` от сервера несёт текст; обрыв соединения — голое событие.
      const data = (e as MessageEvent<string>).data;
      setError(typeof data === "string" && data ? data : null);
      setState("error");
      source.close();
    });
    return () => source.close();
  }, [url, max]);

  const clear = useCallback(() => setLines([]), []);
  return { lines, state, error, clear };
}
