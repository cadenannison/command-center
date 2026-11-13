import { Link } from "@tanstack/react-router";

/** A page that is not built yet: a heading and one line, nothing that looks like a working feature (decision 0395). */
export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="m-0 font-display text-xl font-semibold">{title}</h1>
      <p className="m-0 text-muted">{`${title} is coming soon.`}</p>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-start gap-2">
      <h1 className="m-0 font-display text-xl font-semibold">Page not found</h1>
      <p className="m-0 text-muted">There is nothing at this address.</p>
      <Link to="/dashboard" className="underline">
        Back to Today
      </Link>
    </div>
  );
}
