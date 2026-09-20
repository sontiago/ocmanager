export const ru = {
  // Общее
  "common.retry": "Повторить",
  "common.cancel": "Отмена",
  "common.close": "Закрыть",
  "common.copy": "Скопировать",
  "common.copied": "Скопировано",
  "common.loading": "Загрузка…",
  "common.done": "Готово",
  "common.back": "Назад",

  // Ошибки
  "error.title": "Что-то пошло не так",
  "error.network": "Нет связи с сервером. Проверьте интернет.",
  "error.unauthorized": "Откройте приложение из Telegram.",
  "error.initdata_expired":
    "Сессия устарела. Закройте и откройте приложение заново.",
  "error.rate_limited": "Слишком много запросов. Подождите минуту.",
  "error.device_limit_reached": "Достигнут лимит устройств для вашего тарифа.",
  "error.trial_already_used": "Пробный период уже был использован.",
  "error.subscription_inactive": "Подписка неактивна.",
  "error.node_unavailable": "Сервер временно недоступен. Попробуйте позже.",
  "error.not_found": "Не найдено.",
  "error.internal": "Внутренняя ошибка сервера.",
  "error.code": "Код",
  "error.support": "Написать в поддержку",

  // Навигация
  "nav.subscription": "Подписка",
  "nav.devices": "Устройства",
  "nav.plans": "Тарифы",
  "nav.more": "Ещё",

  // Заголовки в шапке
  "title.home": "Моя подписка",
  "title.plans": "Тарифы",
  "title.checkout": "Оплата",
  "title.devices": "Устройства",
  "title.deviceNew": "Новое устройство",
  "title.deviceKey": "Ключ подключения",
  "title.deviceGuide": "Подключение",
  "title.renew": "Продление",
  "title.account": "Аккаунт",
  "title.onboarding": "ocmanager",
  "title.error": "Ошибка",

  // Тарифы
  "plans.title": "Тарифы",
  "plans.subtitle": "Выберите подходящий вариант",
  "plans.buy": "Купить за {price}",
  "plans.current": "Текущий тариф",
  "plans.unlimitedTraffic": "Безлимитный трафик",
  "plans.trafficPerMonth": "{amount} в месяц",
  "plans.trialTitle": "Попробовать бесплатно",
  "plans.trialBody": "{days} и {traffic} — без оплаты и привязки карты",
  "plans.trialStart": "Активировать пробный период",
  "plans.trialUsed": "Пробный период уже использован",
  "plans.empty": "Тарифы пока не настроены",

  // Подписка
  "subscription.title": "Подписка",
  "subscription.none": "Подписки нет",
  "subscription.noneBody": "Выберите тариф, чтобы начать пользоваться VPN",
  "subscription.choosePlan": "Выбрать тариф",
  "subscription.expiresOn": "Действует до {date}",
  "subscription.expiredOn": "Закончилась {date}",
  "subscription.autoRenewOn": "Продлевается автоматически",
  "subscription.autoRenewOff": "Автопродление отключено",
  "subscription.traffic": "Трафик",
  "subscription.trafficUsed": "{used} из {limit}",
  "subscription.trafficUnlimited": "Без ограничений",
  "subscription.trafficResets": "Обнулится {date}",
  "subscription.devicesUsed": "Устройства: {used} из {limit}",
  "subscription.extend": "Продлить",
  "subscription.renew": "Возобновить",

  // Статусы
  "status.trial": "Пробный период",
  "status.active": "Активна",
  "status.expired": "Истекла",
  "status.exhausted": "Трафик исчерпан",
  "status.cancelled": "Активна до конца периода",
  "status.blocked": "Заблокирована",
  "status.pending_payment": "Ожидает оплаты",

  // Устройства
  "devices.title": "Устройства",
  "devices.add": "Добавить устройство",
  "devices.empty": "Устройств пока нет",
  "devices.emptyBody": "Добавьте устройство, чтобы получить ключ подключения",
  "devices.online": "Подключено",
  "devices.lastSeen": "Был(а) {when}",
  "devices.neverConnected": "Ни разу не подключалось",
  "devices.revoke": "Отозвать",
  "devices.revokeTitle": "Отозвать устройство?",
  "devices.revokeBody":
    "Ключ «{name}» перестанет работать немедленно и восстановлению не подлежит.",
  "devices.revoked": "Устройство отозвано",
  "devices.limitReached": "Достигнут лимит устройств тарифа",
  "devices.instructions": "Инструкция",

  // Выпуск устройства
  "deviceCreate.title": "Новое устройство",
  "deviceCreate.pickPlatform": "Выберите операционную систему",
  "deviceCreate.name": "Название",
  "deviceCreate.namePlaceholder": "iPhone Ивана",
  "deviceCreate.submit": "Выпустить ключ",
  "deviceCreate.issuing": "Выпускаем ключ…",

  // Секрет — показывается один раз
  "deviceSecret.title": "Ключ готов",
  "deviceSecret.warning":
    "Пароль и ссылка показываются один раз. Скачайте файл сейчас — восстановить его нельзя.",
  "deviceSecret.password": "Пароль от файла",
  "deviceSecret.download": "Скачать ключ",
  "deviceSecret.expiresIn": "Ссылка действует ещё {time}",
  "deviceSecret.expired": "Ссылка истекла. Выпустите новое устройство.",
  "deviceSecret.qrHint": "Отсканируйте, чтобы открыть на телефоне",
  "deviceSecret.next": "Перейти к инструкции",

  // Инструкции
  "instructions.title": "Как подключиться",
  "instructions.step": "Шаг {n}",
  "instructions.server": "Адрес сервера",
  "instructions.openStore": "Открыть в магазине приложений",

  // Покупка
  "checkout.opening": "Открываем оплату…",
  "checkout.hint":
    "После оплаты вернитесь в Telegram — бот пришлёт сообщение, когда подписка активируется.",
  "checkout.failed": "Не удалось открыть оплату. Попробуйте ещё раз.",
} as const;

export const ruPlural = {
  "unit.day": {
    one: "{n} день",
    few: "{n} дня",
    many: "{n} дней",
    other: "{n} дня",
  },
  "unit.device": {
    one: "{n} устройство",
    few: "{n} устройства",
    many: "{n} устройств",
    other: "{n} устройства",
  },
  "unit.dayLeft": {
    one: "остался {n} день",
    few: "осталось {n} дня",
    many: "осталось {n} дней",
    other: "осталось {n} дня",
  },
} as const;

export type MessageKey = keyof typeof ru;
export type PluralKey = keyof typeof ruPlural;
