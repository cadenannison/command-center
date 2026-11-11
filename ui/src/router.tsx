import { createRootRoute, createRoute, createRouter, Link, Outlet, redirect } from "@tanstack/react-router";
import { ThemeSwitcher } from "./components/theme-switcher";
import { TodayPage } from "./features/today/today-page";

function Shell() {
  return (
    <div className="mx-auto max-w-3xl p-4">
      <header className="mb-6 flex items-center justify-between gap-4">
        <nav aria-label="Main">
          <Link to="/today">Today</Link>
        </nav>
        <ThemeSwitcher />
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}

const rootRoute = createRootRoute({ component: Shell });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    // eslint-disable-next-line @typescript-eslint/only-throw-error -- redirect() is TanStack Router's own signal
    throw redirect({ to: "/today" });
  },
});

const todayRoute = createRoute({ getParentRoute: () => rootRoute, path: "/today", component: TodayPage });

export const routeTree = rootRoute.addChildren([indexRoute, todayRoute]);

export function createAppRouter(history?: Parameters<typeof createRouter>[0]["history"]) {
  return createRouter({ routeTree, ...(history ? { history } : {}) });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
