import { createRootRoute, createRoute, createRouter, Link, Outlet, redirect } from "@tanstack/react-router";
import { lazy, Suspense } from "react";
import { AppBackdrop } from "./components/app-backdrop";
import { ThemeSwitcher } from "./components/theme-switcher";
import { TodayPage } from "./features/today/today-page";

function Shell() {
  return (
    <div className="mx-auto max-w-3xl p-4">
      <AppBackdrop />
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

// The gallery is dev only (decision 0342). Vite replaces import.meta.env.DEV with false in a production
// build, so the dynamic import below is dropped and no gallery code ships; the route then redirects.
const GalleryPage = import.meta.env.DEV
  ? lazy(() => import("./features/gallery/gallery-page").then((m) => ({ default: m.GalleryPage })))
  : null;

function GalleryRoute() {
  if (!GalleryPage) return null;
  return (
    <Suspense fallback={null}>
      <GalleryPage />
    </Suspense>
  );
}

const galleryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/gallery",
  beforeLoad: () => {
    // eslint-disable-next-line @typescript-eslint/only-throw-error -- redirect() is TanStack Router's own signal
    if (!import.meta.env.DEV) throw redirect({ to: "/today" });
  },
  component: GalleryRoute,
});

export const routeTree = rootRoute.addChildren([indexRoute, todayRoute, galleryRoute]);

export function createAppRouter(history?: Parameters<typeof createRouter>[0]["history"]) {
  return createRouter({ routeTree, ...(history ? { history } : {}) });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
