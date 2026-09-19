import { useParams } from "react-router";
import { PLANS } from "./demo";
import { formatMoney, plural } from "../lib/format";
import { Button } from "../ui/Button";
import { Caption } from "../ui/Caption";
import { Card } from "../ui/Card";
import { Cell } from "../ui/Cell";
import { Hero } from "../ui/Hero";
import { Note } from "../ui/Note";

const T = {
  total: "К оплате",
  plan: "Тариф",
  period: "Период",
  method: "Способ оплаты",
  autoRenew: "Автопродление",
  willBeOn: "включится",
  // Прототип обещал «доступ включится сразу после подтверждения».
  // Обещание верное, но неполное: человек уходит из приложения и должен
  // знать, ГДЕ увидит ответ (решение C5).
  note: "Оплата откроется в Tribute. Приложение закроется — бот пришлёт сообщение в чат, когда доступ будет готов. Обычно это занимает несколько секунд.",
  pay: "Перейти к оплате",
};

export function Checkout() {
  const { planCode } = useParams();
  const plan = PLANS.find((p) => p.code === planCode);

  if (!plan) return <div className="py-8 text-ink-3">Тариф не найден</div>;

  const handlePay = () => {
    // ЭТАП 2: openLink(paymentUrl), затем miniApp.close().
    console.log("оплата тарифа", plan.code);
  };

  return (
    <div>
      <div className="px-1 pt-3.5">
        <Caption>{T.total}</Caption>
        <Hero size="lg">{formatMoney(plan.price_amount, plan.currency)}</Hero>
      </div>

      <Card className="mt-5">
        <Cell title={T.plan} value={plan.name} />
        <Cell
          title={T.period}
          value={`${plan.duration_days} ${plural(plan.duration_days, "день", "дня", "дней")}`}
        />
        <Cell title={T.method} value="Tribute" />
        <Cell title={T.autoRenew} value={T.willBeOn} />
      </Card>

      <Note className="px-1 pt-3.5">{T.note}</Note>

      <Button className="mt-[18px]" onClick={handlePay}>
        {T.pay}
      </Button>
    </div>
  );
}
