import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./app/App";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";
import "./styles/index.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("SharipovAI root element is missing");
}

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
