import { useEffect, useState } from "react";

/** The current time in epoch ms, refreshed every minute so "today", "Now" and the date window move on their own.
 *  One hook for every widget that groups by the clock. */
export const NOW_TICK_MS = 60_000;

export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, NOW_TICK_MS);
    return () => {
      clearInterval(timer);
    };
  }, []);
  return now;
}
