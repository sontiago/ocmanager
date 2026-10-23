type Listener = (e: Event) => void;

/** Подмена EventSource для тестов: `FakeEventSource.instances` — все созданные соединения. */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static reset() {
    FakeEventSource.instances = [];
  }

  closed = false;
  private listeners = new Map<string, Listener[]>();

  url: string;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }

  removeEventListener(type: string, fn: Listener) {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((l) => l !== fn));
  }

  close() {
    this.closed = true;
  }

  /** Событие от сервера: `data` задан — MessageEvent (в том числе именованный `error`). */
  emit(type: string, data?: string) {
    const event = data === undefined ? new Event(type) : new MessageEvent(type, { data });
    for (const fn of this.listeners.get(type) ?? []) fn(event);
  }
}
