/** The six sources with colors in docs/design/tokens.json. The id is the data-source value tokens use. */
export const SOURCES = [
  { id: "cal", name: "Calendar" },
  { id: "canvas", name: "Canvas" },
  { id: "ls", name: "LearningSuite" },
  { id: "gmail", name: "Gmail" },
  { id: "wx", name: "Weather" },
  { id: "manual", name: "My tasks" },
] as const;

export type SourceId = (typeof SOURCES)[number]["id"];
