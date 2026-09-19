import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { initTelegram } from "./telegram/init";
import "./index.css";

async function bootstrap(): Promise<void> {
  if (import.meta.env.DEV) {
    await import("./telegram/mockEnv");
  }

  initTelegram();

  // App импортируется динамически по той же причине: любой модуль в его
  // дереве может читать сигналы SDK на верхнем уровне, а к этому моменту
  // SDK уже инициализирован.
  const { App } = await import("./app/App");

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
