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
// the landing film floats the bar over itself; set it before the first paint so nothing shifts (FilmHero owns it after)
if (window.location.hash === "#/" || window.location.hash === "#") document.body.classList.add("has-film");
installMediaOverrides();
applyDisplay(loadDisplay());
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
