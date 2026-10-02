# Фикстуры вебхуков Tribute

**Статус: по схеме из официального OpenAPI Tribute** (`https://tribute.tg/api/v1/openapi/en`,
вебхуки `new_subscription`, `renewed_subscription`, `cancelled_subscription`,
`new_digital_product`, `digital_product_refunded`), значения синтетические. С живого вебхука
они не снимались: Задача 5.8 плана Фазы 5 заменяет их настоящими. `new_donation.json` —
придуманный пример события, которое нам не нужно.

Подпись в файлах не хранится: тесты считают её сами (`billing/testing.py: sign`).
Персональные данные в снятых фикстурах заменяйте синтетическими.

Что известно из документации и что ещё проверить в 5.8:

- имя события — `name` (snake_case), данные — `payload`;
- `payload.telegram_user_id` — Telegram ID плательщика;
- `payload.price` — сколько заплатил клиент, `payload.amount` — после комиссии Tribute, оба в
  минорных единицах. **Выручкой считаем `price`** (платёж пишется с ним; чистая сумма остаётся
  в `raw_payload`). У цифровых товаров `price` нет — берётся `amount`;
- `payload.period_id` — период подписки (месяц, год…); **по нему тариф связывается с продуктом**
  (`provider_product_ids.tribute.product_ref`), `payload.subscription_id` — сама подписка;
- `payload.expires_at` — конец оплаченного периода;
- у вебхука нет собственного уникального идентификатора: идентификатор события — `sha256(тело)`;
- возврата подписки в вебхуках нет, есть только `digital_product_refunded` (цифровые товары,
  `purchase_id`); покупки цифровых товаров (`new_digital_product`) этот код пока не обрабатывает;
- **проверить на живом вебхуке:** приходит ли `type` = `regular` у первой оплаты, формат
  `expires_at` при продлении, отличаются ли `period_id` у месячного и годового периода.

## Снято с живого Tribute

- `live_new_subscription_trial.json` — настоящий `new_subscription` (2026-10-02), персональные данные
  заменены. Подтверждено: схема payload совпадает с OpenAPI; в вебхуке есть `web_app_link`;
  `expires_at` с наносекундами и `Z`; **у пробного периода (`type: "trial"`, `period: "trial"`)
  `price` = цена полного периода, а `amount` = 0** — это не оплата, парсер пишет сумму 0.
  Пробный период у этой подписки длится час (`expires_at` − `created_at`), а наш тариф выдаёт
  `duration_days` — тариф для пробного `period_id` надо настраивать осознанно.
- `live_renewed_subscription.json` — настоящий `renewed_subscription` (2026-10-02), пришёл сразу после
  часового пробного периода. Подтверждено: после триала `type` = `regular`, `period` = `monthly`,
  `period_id` — **месячный** (не пробный), `price` и `amount` равны (в тесте комиссии нет),
  `expires_at` — ровно месяц календарный (2 ноября), а не 30 дней.
