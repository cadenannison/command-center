import { Outlet, useRouterState } from "@tanstack/react-router";
import { useState } from "react";
import { AppBackdrop } from "../components/app-backdrop";
import { ToastProvider } from "../components/toast";
import { ThemeSwitcher } from "../components/theme-switcher";
import { DisplayMenu } from "../features/display/display-menu";
import { Rail } from "./rail";
import { useRailCollapsed } from "./rail-state";

/** The layout route: a titlebar strip, the slim left rail and the page. The Undo toast lives inside <main> too (decision 0402). The Display popover is opened from the
 *  titlebar and portals into <main>, non-modal (decisions 0383, 0392). */
export function AppShell() {
  const [collapsed, toggle] = useRailCollapsed();
  const [main, setMain] = useState<HTMLElement | null>(null);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // The grid needs a wide page (12 columns); every other page keeps the narrow column.
  const wide = pathname.startsWith("/dashboard");
  return (
    <div className="flex min-h-screen flex-col">
      <AppBackdrop />
      <header className="flex items-center justify-between gap-4 border-b border-line px-4 py-2">
        <span className="font-display font-semibold">Command Center</span>
        <div className="flex items-center gap-3">
          {/* /today keeps this switcher until cutover (it predates the Display popover). */}
          {pathname.startsWith("/today") && <ThemeSwitcher />}
          <DisplayMenu container={main} />
        </div>
      </header>
      <div className="flex min-h-0 min-w-0 flex-1">
        <Rail collapsed={collapsed} onToggle={toggle} />
        <main ref={setMain} className="relative min-w-0 flex-1">
          <ToastProvider>
            <div className={wide ? "mx-auto min-w-0 max-w-[1800px] p-4" : "mx-auto min-w-0 max-w-3xl p-4"}>
              <Outlet />
            </div>
          </ToastProvider>
        </main>
      </div>
    </div>
  );
}
