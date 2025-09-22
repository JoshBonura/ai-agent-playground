// src/main.tsx
import "./polyfills";
import { StrictMode } from "react";
import "./index.css";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { I18nProvider } from "./i18n/i18n";
import ServerSettingsSync from "./settings/ServerSettingsSync"; // ← moved

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider>
      <ServerSettingsSync />  
      <AuthProvider>
        <App />
      </AuthProvider>
    </I18nProvider>
  </StrictMode>,
);
