import { useQueryClient } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";
import { SCENARIOS, type ScenarioId } from "../api/mock/scenarios";
import {
  getState,
  resetStore,
  setFault,
  setLatency,
  subscribeStore,
  type FaultId,
} from "../api/mock/store";
import { Sheet } from "../ui/Sheet";

// Тексты панели намеренно не в каталогах i18n: это инструмент разработчика,
// а не интерфейс продукта, и засорять им каталоги нельзя.
const FAULTS: { id: FaultId; label: string }[] = [
  { id: "none", label: "нет" },
  { id: "network", label: "сеть недоступна" },
  { id: "internal", label: "500 на сервере" },
  { id: "rate_limited", label: "429 rate limit" },
  { id: "node_unavailable", label: "503 нода недоступна" },
];

const LATENCIES = [0, 350, 1500, 4000];

export function DevPanel() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const state = useSyncExternalStore(subscribeStore, getState);

  // Смена сценария меняет данные под кэшем — его надо сбросить целиком.
  const applyScenario = async (id: ScenarioId) => {
    resetStore(id);
    await queryClient.resetQueries();
    setOpen(false);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed top-[calc(0.75rem+var(--safe-top))] right-3 z-50 rounded-full bg-black/70 px-3 py-1.5 font-mono text-[11px] text-white"
      >
        сценарий: {state.scenario}
      </button>

      <Sheet open={open} onClose={() => setOpen(false)} title="Мок-окружение">
        <div className="max-h-[60vh] space-y-4 overflow-y-auto px-4 pb-4">
          <div>
            <p className="mb-2 text-[13px] text-ink-2">Сценарий</p>
            <div className="overflow-hidden rounded-card bg-fill">
              {SCENARIOS.map((scenario) => (
                <button
                  key={scenario.id}
                  type="button"
                  onClick={() => void applyScenario(scenario.id)}
                  className={`flex w-full items-center justify-between border-b border-divider px-4 py-2.5 text-left text-[15px] last:border-b-0 ${
                    state.scenario === scenario.id ? "text-accent" : "text-ink"
                  }`}
                >
                  <span>{scenario.label}</span>
                  <span className="font-mono text-[11px] text-ink-3">
                    {scenario.id}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-1">
              <label htmlFor="dev-fault" className="text-[13px] text-ink-2">
                Сбой
              </label>
              <select
                id="dev-fault"
                value={state.fault}
                onChange={(event) => setFault(event.target.value as FaultId)}
                className="mt-1 w-full rounded-lg bg-fill px-3 py-2 text-[15px] text-ink"
              >
                {FAULTS.map((fault) => (
                  <option key={fault.id} value={fault.id}>
                    {fault.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex-1">
              <label htmlFor="dev-latency" className="text-[13px] text-ink-2">
                Задержка
              </label>
              <select
                id="dev-latency"
                value={state.latencyMs}
                onChange={(event) => setLatency(Number(event.target.value))}
                className="mt-1 w-full rounded-lg bg-fill px-3 py-2 text-[15px] text-ink"
              >
                {LATENCIES.map((ms) => (
                  <option key={ms} value={ms}>
                    {ms} мс
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </Sheet>
    </>
  );
}
