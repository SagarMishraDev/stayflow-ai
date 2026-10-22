import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  qk,
  useGuests,
  useServiceRequests,
  useServices,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  formatDateTime,
  serviceRequestUpdateSchema,
  type ServiceRequestUpdateForm,
} from "../lib/schemas";
import { ListState, NotAvailableNotice, PageHeader } from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";
import type { ServiceRequest, ServiceRequestStatus } from "../lib/types";

const COLUMNS: ServiceRequestStatus[] = [
  "PENDING",
  "ACKNOWLEDGED",
  "IN_PROGRESS",
  "COMPLETED",
  "CANCELLED",
];

const NEXT_STATUS: Partial<Record<ServiceRequestStatus, ServiceRequestStatus[]>> = {
  PENDING: ["ACKNOWLEDGED", "CANCELLED"],
  ACKNOWLEDGED: ["IN_PROGRESS", "CANCELLED"],
  IN_PROGRESS: ["COMPLETED", "CANCELLED"],
};

export default function ServiceRequests() {
  const { hotelId } = useAuth();
  const [editingId, setEditingId] = useState<number | null>(null);

  const requestsQuery = useServiceRequests(hotelId);
  const guestsQuery = useGuests(hotelId);
  const servicesQuery = useServices(hotelId);

  const guestName = useMemo(() => {
    const map = new Map<number, string>();
    (guestsQuery.data ?? []).forEach((g) => map.set(g.id, g.name));
    return (id: number) => map.get(id) ?? `Guest #${id}`;
  }, [guestsQuery.data]);
  const serviceName = useMemo(() => {
    const map = new Map<number, string>();
    (servicesQuery.data ?? []).forEach((s) => map.set(s.id, s.name));
    return (id: number) => map.get(id) ?? `Service #${id}`;
  }, [servicesQuery.data]);

  const grouped = useMemo(() => {
    const g = new Map<ServiceRequestStatus, ServiceRequest[]>();
    COLUMNS.forEach((c) => g.set(c, []));
    (requestsQuery.data ?? []).forEach((r) => {
      const list = g.get(r.status);
      if (list) list.push(r);
      else g.get("PENDING")!.push(r);
    });
    return g;
  }, [requestsQuery.data]);

  return (
    <div>
      <PageHeader
        title="Service requests"
        description="Guest requests from every channel, grouped by status. Move a card to acknowledge, work on, or resolve it."
      />
      <div className="mb-6">
        <NotAvailableNotice>
          The staff API has no assignee field on service requests — there is no
          endpoint to assign a request to a staff member. Status changes below
          are the supported workflow.
        </NotAvailableNotice>
      </div>

      <ListState
        query={requestsQuery}
        emptyTitle="No service requests"
        emptyHint="Requests raised by guests through the concierge will appear here."
        skeletonRows={4}
        render={() => (
          <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
            {COLUMNS.map((col) => (
              <section
                key={col}
                aria-label={`${col.replace(/_/g, " ")} requests`}
                className="rounded-xl border border-line bg-mist/50 p-3"
              >
                <h2 className="mb-3 flex items-center justify-between px-1">
                  <span className="text-sm font-semibold">
                    {col.charAt(0) + col.slice(1).toLowerCase().replace(/_/g, " ")}
                  </span>
                  <span className="rounded-full bg-ink/10 px-2 py-0.5 font-mono text-xs font-semibold tabular-nums">
                    {(grouped.get(col) ?? []).length}
                  </span>
                </h2>
                <ul className="space-y-2">
                  {(grouped.get(col) ?? []).map((r) => (
                    <RequestCard
                      key={r.id}
                      request={r}
                      guest={guestName(r.guest_id)}
                      service={serviceName(r.service_id)}
                      onEdit={() => setEditingId(r.id)}
                    />
                  ))}
                  {(grouped.get(col) ?? []).length === 0 && (
                    <li className="rounded-lg border border-dashed border-line p-3 text-center text-xs text-ink/50">
                      Empty
                    </li>
                  )}
                </ul>
              </section>
            ))}
          </div>
        )}
      />

      {editingId !== null && (
        <EditRequestModal
          requestId={editingId}
          hotelId={hotelId}
          onClose={() => setEditingId(null)}
        />
      )}
    </div>
  );
}

function RequestCard({
  request,
  guest,
  service,
  onEdit,
}: {
  request: ServiceRequest;
  guest: string;
  service: string;
  onEdit: () => void;
}) {
  return (
    <li className="rounded-lg border border-line bg-paper p-3">
      <p className="text-sm font-semibold">
        <Link to={`/guests/${request.guest_id}`} className="text-deep-teal underline">
          {guest}
        </Link>
      </p>
      <p className="text-sm">{service}</p>
      {request.request_text && (
        <p className="mt-1 text-xs text-ink/70">{request.request_text}</p>
      )}
      <p className="mt-1 font-mono text-xs text-ink/50">
        #{request.id}
        {request.room_number ? ` · Room ${request.room_number}` : ""} ·{" "}
        {formatDateTime(request.created_at)}
      </p>
      <button
        type="button"
        onClick={onEdit}
        className="mt-2 text-xs font-semibold text-deep-teal underline"
      >
        Update status
      </button>
    </li>
  );
}

function EditRequestModal({
  requestId,
  hotelId,
  onClose,
}: {
  requestId: number;
  hotelId: number | null;
  onClose: () => void;
}) {
  const requestsQuery = useServiceRequests(hotelId);
  const existing = (requestsQuery.data ?? []).find((r) => r.id === requestId);
  const update = useUpdate((id) => `/service-requests/${id}`, [
    qk.serviceRequests(hotelId),
  ]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ServiceRequestUpdateForm>({
    resolver: zodResolver(serviceRequestUpdateSchema),
    defaultValues: existing
      ? {
          room_number: existing.room_number ?? "",
          request_text: existing.request_text ?? "",
          status: existing.status,
        }
      : undefined,
  });

  async function onSubmit(values: ServiceRequestUpdateForm) {
    setServerError(null);
    try {
      await update.mutateAsync({
        id: requestId,
        data: {
          room_number: values.room_number || null,
          request_text: values.request_text || null,
          status: values.status,
        },
      });
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  const quickMoves = existing ? NEXT_STATUS[existing.status] ?? [] : [];

  return (
    <Modal title={`Request #${requestId}`} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {quickMoves.length > 0 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Quick status moves">
            {quickMoves.map((s) => (
              <button
                key={s}
                type="button"
                className="btn btn-secondary !py-1.5 !text-xs"
                disabled={update.isPending}
                onClick={async () => {
                  setServerError(null);
                  try {
                    await update.mutateAsync({ id: requestId, data: { status: s } });
                    onClose();
                  } catch (e) {
                    setServerError(apiErrorMessage(e));
                  }
                }}
              >
                Mark {s.replace(/_/g, " ").toLowerCase()}
              </button>
            ))}
          </div>
        )}
        <Field label="Status" htmlFor="sr-status" error={errors.status?.message}>
          <select id="sr-status" className="input" {...register("status")}>
            {COLUMNS.map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
            ))}
          </select>
        </Field>
        <Field label="Room number" htmlFor="sr-room">
          <TextInput id="sr-room" name="room_number" register={register} />
        </Field>
        <Field label="Request text" htmlFor="sr-text">
          <textarea id="sr-text" className="input" rows={3} {...register("request_text")} />
        </Field>
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
