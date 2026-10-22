import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  qk,
  useCreate,
  useHotelUsers,
  useHotels,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  formatDateTime,
  hotelUserCreateSchema,
  hotelUserUpdateSchema,
  type HotelUserCreateForm,
  type HotelUserUpdateForm,
} from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";
import type { HotelUser } from "../lib/types";

export default function Staff() {
  const { hotelId, isSuperAdmin, role } = useAuth();
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<HotelUser | null>(null);

  const usersQuery = useHotelUsers(hotelId);
  const updateUser = useUpdate((id) => `/hotel-users/${id}`, [
    qk.hotelUsers(hotelId),
  ]);
  const [actionError, setActionError] = useState<string | null>(null);

  async function onDeactivate(u: HotelUser) {
    if (!window.confirm(`${u.is_active ? "Deactivate" : "Reactivate"} ${u.name} (${u.email})?`))
      return;
    setActionError(null);
    try {
      await updateUser.mutateAsync({
        id: u.id,
        data: { is_active: !u.is_active },
      });
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Staff & roles"
        description="Hotel staff accounts. Only hotel admins and super admins can manage them."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            Add staff member
          </button>
        }
      />
      <FormError error={actionError} />
      <ListState
        query={usersQuery}
        emptyTitle="No staff accounts"
        emptyHint="Add the first staff member for this hotel."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            Add staff member
          </button>
        }
        render={(users) => (
          <div className="panel overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Phone</th>
                  <th>Role</th>
                  <th>Active</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className={!u.is_active ? "opacity-60" : ""}>
                    <td className="font-medium">{u.name}</td>
                    <td>{u.email}</td>
                    <td className="font-mono">{u.phone ?? "—"}</td>
                    <td>
                      <RoleBadge role={u.role} />
                    </td>
                    <td>{u.is_active ? "Yes" : "No"}</td>
                    <td>{formatDateTime(u.created_at)}</td>
                    <td className="whitespace-nowrap">
                      <button
                        type="button"
                        className="mr-3 font-medium text-deep-teal underline"
                        onClick={() => setEditing(u)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="font-medium text-coral-deep underline"
                        onClick={() => onDeactivate(u)}
                      >
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      />
      <p className="mt-3 text-xs text-ink/60">
        Signed in as {role}. Only a super admin can grant the super_admin role
        or create users in another hotel; the backend rejects anything else.
      </p>

      {showCreate && hotelId && (
        <CreateUserModal
          hotelId={hotelId}
          isSuperAdmin={isSuperAdmin}
          onClose={() => setShowCreate(false)}
        />
      )}
      {editing && (
        <EditUserModal
          user={editing}
          isSuperAdmin={isSuperAdmin}
          hotelId={hotelId}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const style =
    role === "super_admin"
      ? "bg-ink text-white"
      : role === "hotel_admin"
        ? "bg-deep-teal text-white"
        : "bg-mist text-ink/70 border border-line";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${style}`}>
      {role.replace(/_/g, " ")}
    </span>
  );
}

const ROLE_OPTIONS = ["staff", "hotel_admin"] as const;

function CreateUserModal({
  hotelId,
  isSuperAdmin,
  onClose,
}: {
  hotelId: number;
  isSuperAdmin: boolean;
  onClose: () => void;
}) {
  const hotelsQuery = useHotels();
  const create = useCreate("/hotel-users", [[ "hotel-users", hotelId ]]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<HotelUserCreateForm>({
    resolver: zodResolver(hotelUserCreateSchema),
    defaultValues: { role: "staff" },
  });

  async function onSubmit(values: HotelUserCreateForm) {
    setServerError(null);
    try {
      await create.mutateAsync({
        name: values.name,
        email: values.email,
        phone: values.phone || null,
        role: values.role,
        password: values.password,
        hotel_id: isSuperAdmin && values.hotel_id ? values.hotel_id : undefined,
      });
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title="Add staff member" onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Name" htmlFor="su-name" error={errors.name?.message}>
            <TextInput id="su-name" name="name" register={register} autoComplete="off" />
          </Field>
          <Field label="Email" htmlFor="su-email" error={errors.email?.message}>
            <TextInput id="su-email" name="email" register={register} type="email" autoComplete="off" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Phone" htmlFor="su-phone" error={errors.phone?.message}>
            <TextInput id="su-phone" name="phone" register={register} autoComplete="off" />
          </Field>
          <Field label="Role" htmlFor="su-role" error={errors.role?.message}>
            <select id="su-role" className="input" {...register("role")}>
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>{r.replace(/_/g, " ")}</option>
              ))}
              {isSuperAdmin && <option value="super_admin">super admin</option>}
            </select>
          </Field>
        </div>
        <Field label="Temporary password" htmlFor="su-pass" error={errors.password?.message}>
          <TextInput id="su-pass" name="password" register={register} type="password" autoComplete="new-password" />
        </Field>
        {isSuperAdmin && (
          <Field label="Hotel (super admin only)" htmlFor="su-hotel">
            <select id="su-hotel" className="input" {...register("hotel_id")}>
              <option value="">This hotel</option>
              {(hotelsQuery.data ?? []).map((h) => (
                <option key={h.id} value={h.id}>{h.name}</option>
              ))}
            </select>
          </Field>
        )}
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create account"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function EditUserModal({
  user,
  isSuperAdmin,
  hotelId,
  onClose,
}: {
  user: HotelUser;
  isSuperAdmin: boolean;
  hotelId: number | null;
  onClose: () => void;
}) {
  const update = useUpdate((id) => `/hotel-users/${id}`, [
    qk.hotelUsers(hotelId),
  ]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<HotelUserUpdateForm>({
    resolver: zodResolver(hotelUserUpdateSchema),
    defaultValues: {
      name: user.name,
      phone: user.phone ?? "",
      role: user.role as "staff" | "hotel_admin" | "super_admin",
      is_active: user.is_active,
    },
  });

  async function onSubmit(values: HotelUserUpdateForm) {
    setServerError(null);
    try {
      await update.mutateAsync({
        id: user.id,
        data: {
          name: values.name || undefined,
          phone: values.phone || null,
          role: values.role,
          is_active: values.is_active,
          password: values.password || undefined,
        },
      });
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title={`Edit ${user.name}`} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Name" htmlFor="eu-name" error={errors.name?.message}>
          <TextInput id="eu-name" name="name" register={register} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Phone" htmlFor="eu-phone">
            <TextInput id="eu-phone" name="phone" register={register} />
          </Field>
          <Field label="Role" htmlFor="eu-role" error={errors.role?.message}>
            <select id="eu-role" className="input" {...register("role")}>
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>{r.replace(/_/g, " ")}</option>
              ))}
              {isSuperAdmin && <option value="super_admin">super admin</option>}
            </select>
          </Field>
        </div>
        <Field label="New password (leave blank to keep)" htmlFor="eu-pass" error={errors.password?.message}>
          <TextInput id="eu-pass" name="password" register={register} type="password" autoComplete="new-password" />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...register("is_active")} className="h-4 w-4" />
          Account is active
        </label>
        <p className="font-mono text-xs text-ink/50">{user.email}</p>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={update.isPending}>
            {update.isPending ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
