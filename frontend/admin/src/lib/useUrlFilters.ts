import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

export const PAGE_SIZE = 50;

export type FilterPatch<K extends string> = Partial<Record<K, string | undefined>>;

/**
 * Фильтры списка в query-строке. Значения — строки; пустое значение убирает ключ из URL.
 * Любое изменение фильтра сбрасывает `offset`: иначе после сужения выборки страница пуста.
 */
export function useUrlFilters<K extends string>(keys: readonly K[]) {
  const [params, setParams] = useSearchParams();

  const values = useMemo(() => {
    const out = {} as Record<K, string | undefined>;
    for (const key of keys) out[key] = params.get(key) || undefined;
    return out;
  }, [params, keys]);

  const rawOffset = Number(params.get("offset"));
  const offset = Number.isInteger(rawOffset) && rawOffset > 0 ? rawOffset : 0;

  const set = useCallback(
    (patch: FilterPatch<K>) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(patch) as [K, string | undefined][]) {
          if (value) next.set(key, value);
          else next.delete(key);
        }
        next.delete("offset");
        return next;
      });
    },
    [setParams],
  );

  const setOffset = useCallback(
    (n: number) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        if (n > 0) next.set("offset", String(n));
        else next.delete("offset");
        return next;
      });
    },
    [setParams],
  );

  return { values, set, limit: PAGE_SIZE, offset, setOffset };
}
