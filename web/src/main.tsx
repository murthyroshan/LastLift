import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyDisplay, installMediaOverrides, loadDisplay } from "./lib/display";
import "./styles.css";
import "./console.css";
import "./landing.css";
import "./landing-more.css";
import "./site.css";

// The front door is the landing film at #/; a bare visit lands there.
if (!window.location.hash) history.replaceState(null, "", "#/");
installMediaOverrides();
applyDisplay(loadDisplay());
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
