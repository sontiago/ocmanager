import type { components } from "./generated";

type Schemas = components["schemas"];

/** Схема ответа или тела запроса из OpenAPI бэкенда: `S<"ClientCard">`. */
export type S<K extends keyof Schemas> = Schemas[K];

/** Страница списка: бэкенд отдаёт `Page[T]`, а в OpenAPI это набор конкретных схем. */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
