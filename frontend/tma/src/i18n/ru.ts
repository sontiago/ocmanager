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

  // Тарифы
  "plans.title": "Тарифы",
  "plans.subtitle": "Выберите подходящий вариант",
  "plans.buy": "Купить за {price}",
  "plans.current": "Текущий тариф",
  "plans.currentShort": "ТЕКУЩИЙ",
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
  "devices.slots": "Занято {used} из {limit}",
  "devices.freeSlot": "Свободный слот",
  "devices.freeSlotBody": "Выпустить ключ на новое устройство",
  "devices.revokeConfirm": "Отозвать устройство",
  "devices.note":
    "Один ключ работает на одном устройстве. Отозванный ключ перестаёт подключаться сразу, слот освобождается.",

  // Выпуск устройства
  "deviceCreate.title": "Новое устройство",
  "deviceCreate.pickPlatform": "Выберите операционную систему",
  "deviceCreate.name": "Название",
  "deviceCreate.namePlaceholder": "iPhone Ивана",
  "deviceCreate.submit": "Выпустить ключ",
  "deviceCreate.issuing": "Выпускаем ключ…",
  "deviceCreate.intro":
    "Выберите систему устройства — от неё зависит формат ключа и инструкция.",

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

  "devices.manage": "К списку устройств",
  // Инструкции
  "instructions.title": "Как подключиться",
  "instructions.step": "Шаг {n}",
  "instructions.server": "Адрес сервера",
  "instructions.openStore": "Открыть в магазине приложений",

  // Покупка
  "checkout.total": "К оплате",
  "checkout.plan": "Тариф",
  "checkout.period": "Период",
  "checkout.method": "Способ оплаты",
  "checkout.autoRenew": "Автопродление",
  "checkout.autoRenewOn": "включится",
  "checkout.pay": "Перейти к оплате",
  "checkout.opening": "Открываем оплату…",
  "checkout.note":
    "Оплата откроется в Tribute. Приложение закроется — бот пришлёт сообщение в чат, когда доступ будет готов. Обычно это занимает несколько секунд.",
  "checkout.hint":
    "После оплаты вернитесь в Telegram — бот пришлёт сообщение, когда подписка активируется.",
  "checkout.notFound": "Тариф не найден",
  "checkout.notFoundBody": "Возможно, он больше не продаётся. Выберите другой.",

  "subscription.autoRenew": "Автопродление",
  "subscription.nextCharge": "Списание {price}",
  "subscription.on": "включено",
  "subscription.off": "выключено",
  "subscription.accessLeft": "Доступ активен ещё",
  "subscription.changePlan": "Сменить тариф",
  "subscription.changePlanBody": "Больше устройств или трафика",

  "instructions.ios.1": "Установите Cisco Secure Client из App Store",
  "instructions.ios.2":
    "Откройте скачанный файл ключа и введите пароль — iOS предложит установить профиль",
  "instructions.ios.3":
    "Настройки → Основные → VPN и управление устройством → установите профиль",
  "instructions.ios.4":
    "Откройте Cisco Secure Client, добавьте подключение с адресом сервера и включите VPN",

  "instructions.android.1": "Установите Cisco Secure Client из Google Play",
  "instructions.android.2":
    "В приложении откройте меню → Управление сертификатами → Импорт из файла",
  "instructions.android.3": "Выберите скачанный файл ключа и введите пароль",
  "instructions.android.4":
    "Добавьте подключение с адресом сервера, выберите импортированный сертификат и включите VPN",

  "instructions.windows.1": "Установите OpenConnect GUI с официального сайта",
  "instructions.windows.2":
    "Дважды щёлкните по скачанному файлу ключа и введите пароль — Windows положит сертификат в личное хранилище",
  "instructions.windows.3":
    "В OpenConnect GUI создайте профиль, укажите адрес сервера и выберите сертификат из хранилища",
  "instructions.windows.4":
    "Нажмите «Подключиться» — соединение установится за пару секунд",

  "instructions.macos.1": "Установите OpenConnect GUI или Cisco Secure Client",
  "instructions.macos.2":
    "Откройте скачанный файл ключа двойным щелчком и введите пароль — сертификат попадёт в Связку ключей",
  "instructions.macos.3":
    "Создайте профиль с адресом сервера и выберите импортированный сертификат",
  "instructions.macos.4":
    "Подключитесь и разрешите системе добавить VPN-конфигурацию",

  "instructions.linux.1":
    "Установите пакет openconnect: apt install openconnect или dnf install openconnect",
  "instructions.linux.2":
    "Распакуйте ключ: openssl pkcs12 -in key.p12 -out key.pem -nodes (спросит пароль)",
  "instructions.linux.3":
    "Подключитесь: sudo openconnect --certificate=key.pem <адрес сервера>",
  "instructions.linux.4":
    "Для постоянного подключения добавьте профиль в NetworkManager: nmcli connection add type vpn",

  // Продление
  "renew.nextCharge": "Следующее списание",
  "renew.price": "Стоимость продления",
  "renew.accessEnds": "Доступ заканчивается {date}",
  "renew.managed":
    "Включается и отключается в Tribute — там же, где оформлялась оплата",
  "renew.note":
    "Продление меняет только дату: ключи не перевыпускаются, соединение не рвётся, счётчик трафика начинается заново. Отключение автопродления не отключает доступ — оплаченный период дорабатывает до конца.",
  "renew.submit": "Продлить сейчас на {days}",

  // Аккаунт
  "account.language": "Язык",
  "account.theme": "Тема",
  "account.themeSystem": "Как в Telegram",
  "account.themeLight": "Светлая",
  "account.themeDark": "Тёмная",
  "account.support": "Поддержка",

  // Онбординг
  "onboarding.title1": "Доступ",
  "onboarding.title2": "за две минуты",
  "onboarding.step1Title": "Выберите тариф",
  "onboarding.step1Body": "Срок, число устройств, трафик",
  "onboarding.step2Title": "Оплатите в Tribute",
  "onboarding.step2Body": "Доступ включится сам",
  "onboarding.step3Title": "Получите ключ",
  "onboarding.step3Body": "И инструкцию под свою систему",

  // Глобальные состояния
  "gate.outsideTelegram": "Откройте приложение из Telegram",
  "gate.outsideTelegramBody":
    "Мини-приложение работает только внутри Telegram — вернитесь в чат с ботом и откройте его оттуда.",
  "gate.blocked": "Доступ приостановлен",
  "gate.blockedBody":
    "Подписка и ключи сохранены. Напишите в поддержку, чтобы разобраться с блокировкой.",
  "gate.crashed": "Приложение не смогло продолжить",
  "gate.crashedBody":
    "Это сбой приложения, а не вашего доступа: подписка и ключи не пострадали.",
  "gate.reload": "Перезапустить",
} as const;

export const ruPlural = {
  "unit.day": {
    one: "{n} день",
    few: "{n} дня",
    many: "{n} дней",
    other: "{n} дня",
  },
  "unit.dayBare": {
    one: "день",
    few: "дня",
    many: "дней",
    other: "дня",
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
