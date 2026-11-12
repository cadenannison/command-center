import { useEffect, useState, type RefObject } from "react";
import { columnsForWidth } from "../../layout";

export interface GridSize {
  /** Width of the grid's container in px (0 until measured). */
  readonly width: number;
  /** 12, 8 or 4, from the window width (decision 0350). */
  readonly cols: 12 | 8 | 4;
}

const read = (el: HTMLElement | null): GridSize => ({
  width: el ? el.getBoundingClientRect().width : 0,
  cols: columnsForWidth(window.innerWidth),
});

/** Container width and the column count, kept current with a ResizeObserver on the container and the page. */
export function useGridSize(ref: RefObject<HTMLElement | null>): GridSize {
  const [size, setSize] = useState<GridSize>({
    width: 0,
    cols: columnsForWidth(window.innerWidth),
  });
  useEffect(() => {
    const el = ref.current;
    const update = () => {
      const next = read(el);
      setSize((old) => (old.width === next.width && old.cols === next.cols ? old : next));
    };
    update();
    const observer = new ResizeObserver(update);
    if (el) observer.observe(el);
    observer.observe(document.documentElement);
    return () => {
      observer.disconnect();
    };
  }, [ref]);
  return size;
}
