import { createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";
import { lazy, Suspense } from "react";
import { DashboardPage } from "./features/dashboard/dashboard-page";
import { TodayPage } from "./features/today/today-page";
import { AppShell } from "./shell/app-shell";
import { NotFoundPage, PlaceholderPage } from "./shell/pages";

// The shell is the root layout; every route renders inside it (decision 0394). Unknown paths get the not-found view.
const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFoundPage });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    // eslint-disable-next-line @typescript-eslint/only-throw-error -- redirect() is TanStack Router's own signal
    throw redirect({ to: "/dashboard" });
  },
});

const chatRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/chat",
  component: () => <PlaceholderPage title="Chat" />,
});
const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  component: () => <PlaceholderPage title="History" />,
});
const focusRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/focus",
  component: () => <PlaceholderPage title="Focus" />,
});
const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: () => <PlaceholderPage title="Settings" />,
});

const todayRoute = createRoute({ getParentRoute: () => rootRoute, path: "/today", component: TodayPage });

const dashboardRoute = createRoute({ getParentRoute: () => rootRoute, path: "/dashboard", component: DashboardPage });

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
    if (!import.meta.env.DEV) throw redirect({ to: "/dashboard" });
  },
  component: GalleryRoute,
});

export const routeTree = rootRoute.addChildren([
  indexRoute,
  todayRoute,
  dashboardRoute,
  chatRoute,
  historyRoute,
  focusRoute,
  settingsRoute,
  galleryRoute,
]);

export function createAppRouter(history?: Parameters<typeof createRouter>[0]["history"]) {
  return createRouter({ routeTree, ...(history ? { history } : {}) });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
