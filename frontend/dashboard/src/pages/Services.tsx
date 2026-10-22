import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  qk,
  useCreate,
  useRemove,
  useServices,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  formatMoney,
  serviceSchema,
  type ServiceForm,
} from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";
import type { Service } from "../lib/types";

export default function Services() {
  const { hotelId } = useAuth();
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<Service | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("ALL");

  const servicesQuery = useServices(hotelId);
  const remove = useRemove((id) => `/services/${id}`, [qk.services(hotelId)]);
  const [actionError, setActionError] = useState<string | null>(null);

  const categories = useMemo(() => {
    const set = new Set<string>();
    (servicesQuery.data ?? []).forEach((s) => {
      if (s.category) set.add(s.category);
    });
    return ["ALL", ...[...set].sort()];
  }, [servicesQuery.data]);

  const filtered = useMemo(() => {
    const items = servicesQuery.data ?? [];
    const list =
      categoryFilter === "ALL"
        ? items
        : items.filter((s) => s.category === categoryFilter);
    return [...list].sort((a, b) => a.name.localeCompare(b.name));
  }, [servicesQuery.data, categoryFilter]);

  async function onDelete(s: Service) {
    if (!window.confirm(`Delete the service "${s.name}"?`)) return;
    setActionError(null);
    try {
      await remove.mutateAsync(s.id);
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Hotel services"
        description="Chargeable and on-request services guests can ask the concierge about — spa, laundry, transfers, and the like."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
            Add service
          </button>
        }
      />
      <FormError error={actionError} />
      {categories.length > 2 && (
        <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Filter by category">
          {categories.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setCategoryFilter(c)}
              aria-pressed={categoryFilter === c}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                categoryFilter === c
                  ? "bg-deep-teal text-white"
                  : "border border-line bg-paper hover:bg-mist"
              }`}
            >
              {c === "ALL" ? "All" : c}
            </button>
          ))}
        </div>
      )}
      <ListState
        query={servicesQuery}
        emptyTitle="No services yet"
        emptyHint="Add the services your hotel offers so the concierge can describe and book them."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
            Add service
          </button>
        }
        render={() =>
          filtered.length === 0 ? (
            <div className="panel p-8 text-center">
              <p className="font-semibold">No services in this category</p>
              <p className="mt-1 text-sm text-ink/70">Try another category.</p>
            </div>
          ) : (
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Category</th>
                    <th>Price</th>
                    <th>Active</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((s) => (
                    <tr key={s.id} className={!s.is_active ? "opacity-60" : ""}>
                      <td>
                        <p className="font-medium">{s.name}</p>
                        {s.description && (
                          <p className="text-xs text-ink/60">{s.description}</p>
                        )}
                      </td>
                      <td>{s.category ?? "—"}</td>
                      <td className="font-mono tabular-nums">
                        {s.price === null ? "On request" : formatMoney(s.price)}
                      </td>
                      <td>{s.is_active ? "Yes" : "No"}</td>
                      <td className="whitespace-nowrap">
                        <button
                          type="button"
                          className="mr-3 font-medium text-deep-teal underline"
                          onClick={() => {
                            setEditing(s);
                            setShowModal(true);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="font-medium text-coral-deep underline"
                          onClick={() => onDelete(s)}
                          disabled={remove.isPending}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      />

      {showModal && hotelId && (
        <ServiceModal
          hotelId={hotelId}
          existing={editing}
          onClose={() => {
            setShowModal(false);
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

function ServiceModal({
  hotelId,
  existing,
  onClose,
}: {
  hotelId: number;
  existing: Service | null;
  onClose: () => void;
}) {
  const create = useCreate("/services", [qk.services(hotelId)]);
  const update = useUpdate((id) => `/services/${id}`, [qk.services(hotelId)]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ServiceForm>({
    resolver: zodResolver(serviceSchema),
    defaultValues: existing
      ? {
          name: existing.name,
          description: existing.description ?? "",
          price: existing.price ?? "",
          category: existing.category ?? "",
          is_active: existing.is_active,
        }
      : { is_active: true },
  });

  async function onSubmit(values: ServiceForm) {
    setServerError(null);
    const payload = {
      hotel_id: hotelId,
      name: values.name.trim(),
      description: values.description?.trim() || null,
      price: values.price || null,
      category: values.category?.trim() || null,
      is_active: values.is_active,
    };
    try {
      if (existing) await update.mutateAsync({ id: existing.id, data: payload });
      else await create.mutateAsync(payload);
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title={existing ? `Edit ${existing.name}` : "Add service"} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Name" htmlFor="sv-name" error={errors.name?.message}>
          <TextInput id="sv-name" name="name" register={register} placeholder="Airport transfer" />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Category" htmlFor="sv-cat">
            <TextInput id="sv-cat" name="category" register={register} placeholder="Transport, Wellness…" />
          </Field>
          <Field label="Price (blank = on request)" htmlFor="sv-price" error={errors.price?.message}>
            <TextInput id="sv-price" name="price" register={register} inputMode="decimal" />
          </Field>
        </div>
        <Field label="Description" htmlFor="sv-desc">
          <textarea id="sv-desc" className="input" rows={2} {...register("description")} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...register("is_active")} className="h-4 w-4" />
          Active
        </label>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending || update.isPending}>
            {create.isPending || update.isPending ? "Saving…" : existing ? "Save changes" : "Add service"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
