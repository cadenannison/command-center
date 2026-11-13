import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { cn } from "../../lib/utils";
import { DashboardView } from "./dashboard-view";
import { fetchDashboards } from "./dashboards-api";
import { dashboardsKey, useCreateMain, useDashboards } from "./use-dashboards";

/** Fixed text: the server's error text is never shown (decision 0375). */
const REFRESH_FAILED = "Couldn't refresh. Showing your last saved view.";

const CONFLICT_NOTICE =
  "This dashboard was changed somewhere else. Showing the latest version; your last change was not saved.";

export function DashboardPage() {
  const queryClient = useQueryClient();
  const dashboards = useDashboards();
  const createMain = useCreateMain();
  const [selected, setSelected] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);
  const flushRef = useRef<(() => Promise<boolean>) | null>(null);
  const creating = useRef(false);
  const noticeRef = useRef<HTMLDivElement>(null);

  const list = dashboards.data;
  useEffect(() => {
    if (list?.length !== 0 || creating.current) return;
    creating.current = true;
    createMain.mutate(undefined, {
      onSettled: () => {
        creating.current = false;
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the mutation object changes every render; the ref guards a second call
  }, [list]);

  // The view is remounted after a conflict, so keyboard focus would fall to the page; the notice takes it.
  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice, epoch]);

  const current = list?.find((d) => d.id === selected) ?? list?.[0];

  const reload = useCallback(async (): Promise<boolean> => {
    try {
      const fresh = await fetchDashboards();
      queryClient.setQueryData(dashboardsKey, fresh);
      setBlocked(false);
      setNotice(CONFLICT_NOTICE);
      setEpoch((n) => n + 1);
      return true;
    } catch {
      return false;
    }
  }, [queryClient]);

  const clearBlocked = useCallback(() => {
    setBlocked(false);
  }, []);

  const select = async (id: string): Promise<boolean> => {
    if (id === current?.id) return true;
    const ok = (await flushRef.current?.()) ?? true;
    setBlocked(!ok);
    if (ok) setSelected(id);
    return ok;
  };

  const onTabKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!list || !current) return;
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = list[(list.indexOf(current) + step + list.length) % list.length];
    if (next) {
      void select(next.id).then((ok) => {
        if (ok) document.getElementById(`dashboard-tab-${next.id}`)?.focus();
      });
    }
  };

  if (dashboards.isPending) {
    return (
      <div role="status" aria-label="Loading dashboards" className="flex flex-col gap-3">
        <Skeleton />
        <Skeleton className="w-2/3" />
      </div>
    );
  }
  // The full panel is only for "nothing to show". A failed refetch keeps the grid and any unsaved edits (decision 0375).
  if (dashboards.isError && dashboards.data === undefined) {
    return (
      <div role="alert" className="flex flex-col items-start gap-3">
        <p className="text-danger">{dashboards.error.message}</p>
        <Button
          variant="outline"
          onClick={() => {
            void dashboards.refetch();
          }}
        >
          Retry
        </Button>
      </div>
    );
  }
  if (!current) {
    return createMain.isError ? (
      <div role="alert" className="flex flex-col items-start gap-3">
        <p className="text-danger">{`Could not create your first dashboard. ${createMain.error.message}`}</p>
        <Button
          variant="outline"
          onClick={() => {
            createMain.reset();
            creating.current = true;
            createMain.mutate(undefined, {
              onSettled: () => {
                creating.current = false;
              },
            });
          }}
        >
          Retry
        </Button>
      </div>
    ) : (
      <p role="status">Setting up your first dashboard…</p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="sr-only">Dashboard</h1>
      <div role="tablist" aria-label="Dashboards" onKeyDown={onTabKey} className="flex flex-wrap gap-2">
        {list?.map((d) => (
          <button
            key={d.id}
            id={`dashboard-tab-${d.id}`}
            type="button"
            role="tab"
            aria-selected={d.id === current.id}
            aria-controls="dashboard-panel"
            tabIndex={d.id === current.id ? 0 : -1}
            className={cn(
              "min-h-8 rounded-control px-4 font-medium",
              d.id === current.id ? "bg-accent text-accent-fg" : "border border-line2 bg-chip text-fg",
            )}
            onClick={() => {
              void select(d.id);
            }}
          >
            {d.name}
          </button>
        ))}
      </div>
      {dashboards.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-muted">
          <span>{REFRESH_FAILED}</span>
          <Button
            size="sm"
            variant="outline"
            disabled={dashboards.isFetching}
            onClick={() => {
              void dashboards.refetch();
            }}
          >
            Retry
          </Button>
        </div>
      )}
      {blocked && (
        <p role="alert" className="text-danger">
          Your last change has not been saved yet, so this dashboard stays open. Retry the save, then switch.
        </p>
      )}
      {notice && (
        <div ref={noticeRef} tabIndex={-1} role="status" className="flex items-center gap-3 text-muted">
          <span>{notice}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setNotice(null);
            }}
          >
            Dismiss
          </Button>
        </div>
      )}
      <div role="tabpanel" id="dashboard-panel" aria-labelledby={`dashboard-tab-${current.id}`}>
        <DashboardView
          key={`${current.id}:${String(epoch)}`}
          dashboard={current}
          flushRef={flushRef}
          onConflict={reload}
          onSaved={clearBlocked}
        />
      </div>
    </div>
  );
}
