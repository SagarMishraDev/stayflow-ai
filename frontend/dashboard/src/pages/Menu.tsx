import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  qk,
  useCreate,
  useMenuItems,
  useRemove,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  formatMoney,
  menuItemSchema,
  type MenuItemForm,
} from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";
import type { MenuItem } from "../lib/types";

export default function Menu() {
  const { hotelId } = useAuth();
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<MenuItem | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("ALL");

  const itemsQuery = useMenuItems(hotelId);
  const remove = useRemove((id) => `/menu-items/${id}`, [qk.menuItems(hotelId)]);
  const update = useUpdate((id) => `/menu-items/${id}`, [qk.menuItems(hotelId)]);
  const [actionError, setActionError] = useState<string | null>(null);

  const categories = useMemo(() => {
    const set = new Set<string>();
    (itemsQuery.data ?? []).forEach((i) => {
      if (i.category) set.add(i.category);
    });
    return ["ALL", ...[...set].sort()];
  }, [itemsQuery.data]);

  const filtered = useMemo(() => {
    const items = itemsQuery.data ?? [];
    const list =
      categoryFilter === "ALL"
        ? items
        : items.filter((i) => i.category === categoryFilter);
    return [...list].sort((a, b) => a.name.localeCompare(b.name));
  }, [itemsQuery.data, categoryFilter]);

  async function toggleAvailable(item: MenuItem) {
    setActionError(null);
    try {
      await update.mutateAsync({
        id: item.id,
        data: { is_available: !item.is_available },
      });
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  async function onDelete(item: MenuItem) {
    if (!window.confirm(`Delete "${item.name}" from the menu?`)) return;
    setActionError(null);
    try {
      await remove.mutateAsync(item.id);
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Menu"
        description="Food and beverage items guests can order through the concierge."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
            Add item
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
        query={itemsQuery}
        emptyTitle="The menu is empty"
        emptyHint="Add items so guests can order food and drinks through the concierge."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
            Add item
          </button>
        }
        render={() =>
          filtered.length === 0 ? (
            <div className="panel p-8 text-center">
              <p className="font-semibold">No items in this category</p>
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
                    <th>Available</th>
                    <th>Active</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((item) => (
                    <tr key={item.id} className={!item.is_active ? "opacity-60" : ""}>
                      <td>
                        <p className="font-medium">{item.name}</p>
                        {item.description && (
                          <p className="text-xs text-ink/60">{item.description}</p>
                        )}
                      </td>
                      <td>{item.category ?? "—"}</td>
                      <td className="font-mono tabular-nums">{formatMoney(item.price)}</td>
                      <td>
                        <button
                          type="button"
                          onClick={() => toggleAvailable(item)}
                          disabled={update.isPending}
                          className="font-medium text-deep-teal underline"
                          aria-label={`${item.is_available ? "Mark unavailable" : "Mark available"}: ${item.name}`}
                        >
                          {item.is_available ? "Yes" : "No"}
                        </button>
                      </td>
                      <td>{item.is_active ? "Yes" : "No"}</td>
                      <td className="whitespace-nowrap">
                        <button
                          type="button"
                          className="mr-3 font-medium text-deep-teal underline"
                          onClick={() => {
                            setEditing(item);
                            setShowModal(true);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="font-medium text-coral-deep underline"
                          onClick={() => onDelete(item)}
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
        <ItemModal
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

function ItemModal({
  hotelId,
  existing,
  onClose,
}: {
  hotelId: number;
  existing: MenuItem | null;
  onClose: () => void;
}) {
  const create = useCreate("/menu-items", [qk.menuItems(hotelId)]);
  const update = useUpdate((id) => `/menu-items/${id}`, [qk.menuItems(hotelId)]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<MenuItemForm>({
    resolver: zodResolver(menuItemSchema),
    defaultValues: existing
      ? {
          name: existing.name,
          description: existing.description ?? "",
          category: existing.category ?? "",
          price: parseFloat(existing.price),
          is_available: existing.is_available,
          is_active: existing.is_active,
        }
      : { is_available: true, is_active: true },
  });

  async function onSubmit(values: MenuItemForm) {
    setServerError(null);
    const payload = {
      hotel_id: hotelId,
      name: values.name.trim(),
      description: values.description?.trim() || null,
      category: values.category?.trim() || null,
      price: values.price,
      is_available: values.is_available,
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
    <Modal title={existing ? `Edit ${existing.name}` : "Add menu item"} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Name" htmlFor="mi-name" error={errors.name?.message}>
          <TextInput id="mi-name" name="name" register={register} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Category" htmlFor="mi-cat">
            <TextInput id="mi-cat" name="category" register={register} placeholder="Breakfast, Mains…" />
          </Field>
          <Field label="Price" htmlFor="mi-price" error={errors.price?.message}>
            <TextInput id="mi-price" name="price" register={register} inputMode="decimal" />
          </Field>
        </div>
        <Field label="Description" htmlFor="mi-desc">
          <textarea id="mi-desc" className="input" rows={2} {...register("description")} />
        </Field>
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...register("is_available")} className="h-4 w-4" />
            Available to order
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...register("is_active")} className="h-4 w-4" />
            Active
          </label>
        </div>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending || update.isPending}>
            {create.isPending || update.isPending ? "Saving…" : existing ? "Save changes" : "Add item"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
