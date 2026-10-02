import { useEffect, type ReactNode } from "react";
import type {
  FieldPath,
  FieldValues,
  UseFormRegister,
} from "react-hook-form";

export function Field({
  label,
  error,
  htmlFor,
  children,
}: {
  label: string;
  error?: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function TextInput<TFieldValues extends FieldValues>({
  id,
  register,
  name,
  ...rest
}: {
  id: string;
  register: UseFormRegister<TFieldValues>;
  name: FieldPath<TFieldValues>;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return <input id={id} className="input" {...register(name)} {...rest} />;
}

export function FormError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-lg border border-brick-600/40 bg-brick-100 p-3 text-sm text-brick-700">
      {error}
    </p>
  );
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  // Keyboard dismissal: Escape closes the dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-pine-950/50 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="panel max-h-[90vh] w-full max-w-lg overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="panel-title">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-secondary !px-3 !py-1.5"
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
