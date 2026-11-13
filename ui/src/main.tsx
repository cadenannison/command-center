import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createAppQueryClient } from "./api/query-client";
import { createAppRouter } from "./router";
import { DisplaySettingsProvider } from "./features/display/display-settings";
import { DisplayProvider } from "./lib/display";
import { ThemeProvider } from "./lib/theme";
import "./styles/index.css";

const queryClient = createAppQueryClient();
const router = createAppRouter();

const container = document.getElementById("root");
if (!container) throw new Error("index.html has no #root element");

createRoot(container).render(
  <StrictMode>
    <ThemeProvider>
      <DisplayProvider>
        <QueryClientProvider client={queryClient}>
          <DisplaySettingsProvider>
            <RouterProvider router={router} />
          </DisplaySettingsProvider>
        </QueryClientProvider>
      </DisplayProvider>
    </ThemeProvider>
  </StrictMode>,
);
