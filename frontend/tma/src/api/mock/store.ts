import type { ConnectionInfo, Device, Me, Plan, Subscription } from "../types";
import { CONNECTION, ME, PLANS, TRIAL_PLAN } from "./fixtures";
import {
  buildScenario,
  DEFAULT_SCENARIO,
  SCENARIOS,
  type ScenarioId,
} from "./scenarios";

export type FaultId =
  | "none"
  | "network"
  | "internal"
  | "rate_limited"
  | "node_unavailable";

export interface MockState {
  scenario: ScenarioId;
  me: Me;
  plans: Plan[];
  trialPlan: Plan;
  subscription: Subscription | null;
  devices: Device[];
  connection: ConnectionInfo;
  /** Счётчик для генерации id и CN новых устройств. */
  deviceSeq: number;
  latencyMs: number;
  fault: FaultId;
}

const STORAGE_KEY = "tma.mock.scenario";

const listeners = new Set<() => void>();
let state: MockState = build(DEFAULT_SCENARIO);

function isScenarioId(value: unknown): value is ScenarioId {
  return SCENARIOS.some((s) => s.id === value);
}

function readStoredScenario(): ScenarioId {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return isScenarioId(raw) ? raw : DEFAULT_SCENARIO;
  } catch {
    return DEFAULT_SCENARIO;
  }
}

function build(scenario: ScenarioId): MockState {
  const s = buildScenario(scenario);
  return {
    scenario,
    me: { ...ME, trial_available: s.trialAvailable, is_blocked: s.isBlocked },
    // Глубокое копирование: сценарии переиспользуют одни и те же объекты,
    // а стор мутабельный — иначе правки протекут между сбросами.
    plans: structuredClone(PLANS),
    trialPlan: structuredClone(TRIAL_PLAN),
    subscription: structuredClone(s.subscription),
    devices: structuredClone(s.devices),
    connection: { ...CONNECTION },
    deviceSeq: s.devices.length,
    latencyMs: 350,
    fault: "none",
  };
}

function notify(): void {
  for (const fn of listeners) fn();
}

export function getState(): MockState {
  return state;
}

/** Без аргумента — восстанавливает сценарий, выбранный до перезагрузки. */
export function resetStore(scenario?: ScenarioId): void {
  const next = scenario ?? readStoredScenario();
  const latency = state.latencyMs;
  const fault = state.fault;
  state = { ...build(next), latencyMs: latency, fault };
  try {
    sessionStorage.setItem(STORAGE_KEY, next);
  } catch {
    // приватный режим — не критично
  }
  notify();
}

export function setFault(fault: FaultId): void {
  state.fault = fault;
  notify();
}

export function setLatency(ms: number): void {
  state.latencyMs = ms;
  notify();
}

export function subscribeStore(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
