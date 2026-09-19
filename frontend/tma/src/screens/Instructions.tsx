import { useNavigate, useParams } from "react-router";
import { ROUTES } from "../app/routes";
import { PLATFORM_INFO, SECRET, type Platform } from "./demo";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { CellIcon } from "../ui/CellIcon";
import { SectionLabel } from "../ui/SectionLabel";

const T = {
  meta: "4 ШАГА, ОКОЛО 2 МИНУТ",
  done: "Готово",
};

const APPLE_STEPS = [
  {
    title: "Скачайте файл ключа",
    body: "Нажмите ссылку выше. Файл сохранится в «Загрузки».",
  },
  {
    title: "Установите профиль",
    body: `Настройки → Профиль загружен → Установить. Пароль: ${SECRET.password}.`,
  },
  {
    title: "Откройте AnyConnect",
    body: "Подключения → Добавить: vpn.example.com. Сертификат подставится сам.",
  },
  {
    title: "Подключитесь",
    body: "Переключатель AnyConnect → ON. Устройство появится в списке через минуту.",
  },
];

const OPENCONNECT_STEPS = [
  {
    title: "Установите OpenConnect",
    body: "Бесплатный клиент из магазина приложений или с openconnect.gitlab.io.",
  },
  {
    title: "Скачайте файл ключа",
    body: `Ссылка выше. Пароль к файлу: ${SECRET.password}.`,
  },
  {
    title: "Импортируйте сертификат",
    body: "Новое подключение → vpn.example.com → сертификат из файла .p12.",
  },
  {
    title: "Подключитесь",
    body: "Нажмите «Подключиться». Пароль спросят один раз.",
  },
];

export function Instructions() {
  const navigate = useNavigate();
  const { platform } = useParams<{ platform: Platform }>();
  const info = PLATFORM_INFO[platform ?? "ios"];
  const steps = info.isApple ? APPLE_STEPS : OPENCONNECT_STEPS;
  const osName = {
    ios: "iOS",
    android: "Android",
    windows: "Windows",
    macos: "macOS",
  }[platform ?? "ios"];

  return (
    <div>
      <SectionLabel>
        {osName} · {T.meta}
      </SectionLabel>
      <Card>
        {steps.map((step, index) => (
          <Cell
            key={step.title}
            align="start"
            icon={<CellIcon>{String(index + 1).padStart(2, "0")}</CellIcon>}
            title={step.title}
            subtitle={step.body}
          />
        ))}
      </Card>

      <Button className="mt-[18px]" onClick={() => navigate(ROUTES.devices)}>
        {T.done}
      </Button>
    </div>
  );
}
