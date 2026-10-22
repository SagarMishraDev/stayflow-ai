import type { ReactNode } from "react";
import { apiErrorMessage } from "../lib/api";

/**
 * One wrapper for every list page: skeleton rows while loading, an empty
 * state with a next action, and an error state with retry. No bare spinners.
 */
export function ListState<T>({
  query,
  emptyTitle,
  emptyHint,
  emptyAction,
  render,
  skeletonRows = 5,
}: {
  query: {
    isLoading: boolean;
    isError: boolean;
    error: unknown;
    data: T[] | undefined;
    refetch: () => void;
  };
  emptyTitle: string;
  emptyHint: string;
  emptyAction?: ReactNode;
  render: (items: T[]) => ReactNode;
  skeletonRows?: number;
}) {
  if (query.isLoading) {
    return (
      <div aria-busy="true" aria-label="Loading" className="space-y-2">
        {Array.from({ length: skeletonRows }).map((_, i) => (
          <div
            key={i}
            className="h-14 animate-pulse rounded-xl border border-line bg-mist"
          />
        ))}
        <span className="sr-only">Loading…</span>
      </div>
    );
  }
  if (query.isError) {
    return (
      <div role="alert" className="panel p-6 text-center">
        <p className="font-semibold">Couldn't load this list</p>
        <p className="mt-1 text-sm text-ink/70">{apiErrorMessage(query.error)}</p>
        <button
          type="button"
          className="btn btn-secondary mt-4"
          onClick={() => query.refetch()}
        >
          Try again
        </button>
      </div>
    );
  }
  const items = query.data ?? [];
  if (items.length === 0) {
    return (
      <div className="panel p-8 text-center">
        <p className="font-semibold">{emptyTitle}</p>
        <p className="mt-1 text-sm text-ink/70">{emptyHint}</p>
        {emptyAction && <div className="mt-4">{emptyAction}</div>}
      </div>
    );
  }
  return <>{render(items)}</>;
}

export function DetailState({
  isLoading,
  isError,
  error,
  onRetry,
  notFound,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  notFound?: boolean;
  children: ReactNode;
}) {
  if (isLoading) {
    return (
      <div aria-busy="true" aria-label="Loading" className="space-y-3">
        <div className="h-8 w-1/3 animate-pulse rounded bg-ink/10" />
        <div className="h-48 animate-pulse rounded-xl border border-line bg-mist" />
        <span className="sr-only">Loading…</span>
      </div>
    );
  }
  if (isError || notFound) {
    return (
      <div role="alert" className="panel p-6 text-center">
        <p className="font-semibold">
          {notFound ? "Not found" : "Couldn't load this record"}
        </p>
        <p className="mt-1 text-sm text-ink/70">
          {notFound
            ? "It may have been deleted, or it belongs to another hotel."
            : apiErrorMessage(error)}
        </p>
        {!notFound && (
          <button type="button" className="btn btn-secondary mt-4" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    );
  }
  return <>{children}</>;
}

/** Inline banner used where the backend has no endpoint for a capability. */
export function NotAvailableNotice({ children }: { children: ReactNode }) {
  return (
    <div
      role="note"
      aria-label="Feature not available"
      className="rounded-xl border border-sun bg-sun/15 p-4 text-sm"
    >
      <p className="font-semibold">Not available in the staff API</p>
      <div className="mt-1 text-ink/80">{children}</div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-3xl font-bold leading-none">{title}</h1>
        {description && <p className="mt-1 text-sm text-ink/70">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
