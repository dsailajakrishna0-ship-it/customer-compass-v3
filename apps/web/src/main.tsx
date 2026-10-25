import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { App } from "./App";

// UI stack: React + TypeScript (built with Vite) renders the whole front end
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
