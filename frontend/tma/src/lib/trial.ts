/**
 * Витрина пробного периода: его тариф скрытый и в каталог GET /tma/plans
 * не попадает, а показать условия нужно до активации.
 *
 * Значения обязаны совпадать с settings.trial_days и
 * settings.trial_traffic_bytes на бэкенде. Когда появится отдельный
 * GET /tma/trial — файл удаляется, экраны переходят на ответ сервера.
 */
export const TRIAL_PREVIEW = {
  duration_days: 3,
  device_limit: 1,
  traffic_limit_bytes: 5 * 1024 ** 3,
} as const;
