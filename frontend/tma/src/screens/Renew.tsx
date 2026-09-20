import { useState } from "react";
import { SUBSCRIPTION } from "./demo";
import { formatMoney, plural } from "../lib/format";
import { Button } from "../ui/Button";
import { Caption } from "../ui/Caption";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { Hero } from "../ui/Hero";
import { Note } from "../ui/Note";

const T = {
  next: "Следующее списание",
  autoRenew: "Автопродление",
  autoRenewSub: "Нажмите, чтобы переключить",
  plan: "Тариф",
  period: "Период",
  note: "Ключи не перевыпускаются, соединение не рвётся, счётчик трафика начнётся заново. Отключение автопродления не отключает доступ: оплаченный период дорабатывает до конца.",
  extend: (days: number) =>
    `Продлить сейчас на ${days} ${plural(days, "день", "дня", "дней")}`,
};

export function Renew() {
  const s = SUBSCRIPTION;
  // Локальное состояние — только на этом этапе. Дальше это мутация.
  const [autoRenew, setAutoRenew] = useState(s.auto_renew);

  return (
    <div>
      <div className="px-1 pt-3.5">
        <Caption>{T.next}</Caption>
        <Hero size="md">{formatMoney(s.price_amount, s.currency, "ru")}</Hero>
        <Note>{s.expires_at} · Tribute</Note>
      </div>

      <Card className="mt-5">
        <Cell
          title={T.autoRenew}
          subtitle={T.autoRenewSub}
          value={
            <span className="text-accent-700">
              {autoRenew ? "включено" : "выключено"}
            </span>
          }
          onClick={() => setAutoRenew((prev) => !prev)}
        />
        <Cell title={T.plan} value={s.plan_name} />
        <Cell title={T.period} value={`${30} дней`} />
      </Card>

      <Note className="px-1 pt-3.5">{T.note}</Note>

      <Button className="mt-[18px]" onClick={() => console.log("продлить")}>
        {T.extend(30)}
      </Button>
    </div>
  );
}
