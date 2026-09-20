import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createApiClientAsync } from "./api";
import { initTelegram } from "./telegram/init";
import "./index.css";

async function bootstrap(): Promise<void> {
  if (import.meta.env.DEV) {
    await import("./telegram/mockEnv");
  }

  initTelegram();

  // App импортируется динамически по той же причине, что и раньше: любой
  // модуль в его дереве может читать сигналы SDK на верхнем уровне, а к
  // этому моменту SDK уже инициализирован. Клиент API создаётся параллельно.
  const [{ App }, client] = await Promise.all([
    import("./app/App"),
    createApiClientAsync(),
  ]);

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App client={client} />
    </StrictMode>,
  );
}

void bootstrap();
