import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyDisplay, installMediaOverrides, loadDisplay } from "./lib/display";
import "./styles.css";
import "./console.css";

// The front door is the scroll story; every app link carries a hash route (#/...), so only a bare visit goes there.
if (!window.location.hash) {
  window.location.replace(`${import.meta.env.BASE_URL}concepts/sequence.html`);
} else {
  installMediaOverrides();
  applyDisplay(loadDisplay());
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
