import { useEffect, useState } from "react";
import { useDayAgenda } from "./use-agenda";
import { deriveTodayState, localDateString } from "./state";
import { TodayView } from "./today-view";

export function TodayPage() {
  const date = localDateString(new Date());
  const query = useDayAgenda(date);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => {
      setNow(Date.now());
    }, 30_000);
    return () => {
      clearInterval(id);
    };
  }, []);
  const state = deriveTodayState(
    {
      data: query.data,
      isPending: query.isPending,
      isError: query.isError,
      errorMessage: query.error?.message ?? null,
      dataUpdatedAt: query.dataUpdatedAt,
    },
    now,
  );
  return (
    <section aria-labelledby="today-heading">
      <h1 id="today-heading" className="mb-4 text-xl font-semibold">
        Today
      </h1>
      <TodayView
        state={state}
        onRetry={() => {
          void query.refetch();
        }}
      />
    </section>
  );
}
