"use client";

import { BrowserRouter } from "react-router-dom";
import { App } from "./app";

export function NextEntry() {
  return (
    <BrowserRouter>
      <App />
    </BrowserRouter>
  );
}
