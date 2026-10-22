import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  qk,
  useCreate,
  useEvaluateNegotiation,
  useNegotiationRules,
  useRemove,
  useRooms,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  formatMoney,
  negotiationEvaluateSchema,
  negotiationRuleSchema,
  type NegotiationEvaluateForm,
  type NegotiationRuleForm,
} from "../lib/schemas";
import {
  ListState,
  NotAvailableNotice,
  PageHeader,
} from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";

export default function Negotiations() {
  const { hotelId } = useAuth();
  const [showRuleModal, setShowRuleModal] = useState(false);
  const [editingRule, setEditingRule] = useState<number | null>(null);

  const rulesQuery = useNegotiationRules(hotelId);
  const roomsQuery = useRooms(hotelId);
  const rooms = roomsQuery.data ?? [];
  const roomName = (id: number | null) =>
    id === null
      ? "All room types"
      : rooms.find((r) => r.id === id)?.room_type ?? `Room #${id}`;

  const remove = useRemove(
    (id) => `/negotiation-rules/${id}`,
    [qk.negotiationRules(hotelId)],
  );
  const [actionError, setActionError] = useState<string | null>(null);

  async function onDelete(id: number) {
    if (!window.confirm("Delete this negotiation rule?")) return;
    setActionError(null);
    try {
      await remove.mutateAsync(id);
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <PageHeader
        title="Negotiations"
        description="Price-negotiation rules and an offer simulator backed by the deterministic evaluation endpoint."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowRuleModal(true)}>
            New rule
          </button>
        }
      />

      <div className="mb-6">
        <NotAvailableNotice>
          <p>
            The staff API has no pending-approvals queue: there is no endpoint
            that lists guest offers waiting for a decision, and no accept/reject
            action. Negotiation outcomes come from the rules below plus{" "}
            <span className="font-mono">POST /negotiation/evaluate</span>, which
            the AI concierge calls during a chat. Use the simulator to see how a
            rule treats an offer.
          </p>
        </NotAvailableNotice>
      </div>

      <FormError error={actionError} />

      <section aria-label="Negotiation rules" className="mb-8">
        <h2 className="panel-title mb-3">Rules</h2>
        <ListState
          query={rulesQuery}
          emptyTitle="No negotiation rules"
          emptyHint="Without rules, every price offer falls back to the default evaluation."
          emptyAction={
            <button type="button" className="btn btn-primary" onClick={() => setShowRuleModal(true)}>
              New rule
            </button>
          }
          render={(rules) => (
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Applies to</th>
                    <th>Enabled</th>
                    <th>Minimum price</th>
                    <th>Max discount</th>
                    <th>Needs approval</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map((r) => (
                    <tr key={r.id}>
                      <td>{roomName(r.room_id)}</td>
                      <td>{r.is_enabled ? "Yes" : "No"}</td>
                      <td className="font-mono tabular-nums">{formatMoney(r.minimum_price)}</td>
                      <td className="font-mono tabular-nums">{r.maximum_discount_percent}%</td>
                      <td>{r.requires_approval ? "Yes" : "No"}</td>
                      <td>
                        <span
                          className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                            r.is_active
                              ? "bg-deep-teal text-white"
                              : "bg-ink/10 text-ink/70 border border-line"
                          }`}
                        >
                          {r.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td className="whitespace-nowrap">
                        <button
                          type="button"
                          className="mr-3 font-medium text-deep-teal underline"
                          onClick={() => {
                            setEditingRule(r.id);
                            setShowRuleModal(true);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="font-medium text-coral-deep underline"
                          onClick={() => onDelete(r.id)}
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
          )}
        />
      </section>

      <section aria-label="Offer simulator">
        <h2 className="panel-title mb-3">Offer simulator</h2>
        {hotelId && <EvaluateForm hotelId={hotelId} />}
      </section>

      {showRuleModal && hotelId && (
        <RuleModal
          hotelId={hotelId}
          ruleId={editingRule}
          onClose={() => {
            setShowRuleModal(false);
            setEditingRule(null);
          }}
        />
      )}
    </div>
  );
}

function RuleModal({
  hotelId,
  ruleId,
  onClose,
}: {
  hotelId: number;
  ruleId: number | null;
  onClose: () => void;
}) {
  const roomsQuery = useRooms(hotelId);
  const rulesQuery = useNegotiationRules(hotelId);
  const existing = (rulesQuery.data ?? []).find((r) => r.id === ruleId) ?? null;
  const create = useCreate("/negotiation-rules", [qk.negotiationRules(hotelId)]);
  const update = useUpdate((id) => `/negotiation-rules/${id}`, [
    qk.negotiationRules(hotelId),
  ]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<NegotiationRuleForm>({
    resolver: zodResolver(negotiationRuleSchema),
    defaultValues: existing
      ? {
          room_id: existing.room_id ?? undefined,
          is_enabled: existing.is_enabled,
          minimum_price: parseFloat(existing.minimum_price),
          maximum_discount_percent: parseFloat(existing.maximum_discount_percent),
          requires_approval: existing.requires_approval,
          is_active: existing.is_active,
        }
      : { is_enabled: true, requires_approval: false, is_active: true },
  });

  async function onSubmit(values: NegotiationRuleForm) {
    setServerError(null);
    const payload = {
      hotel_id: hotelId,
      room_id: values.room_id || null,
      is_enabled: values.is_enabled,
      minimum_price: values.minimum_price,
      maximum_discount_percent: values.maximum_discount_percent,
      requires_approval: values.requires_approval,
      is_active: values.is_active,
    };
    try {
      if (ruleId) await update.mutateAsync({ id: ruleId, data: payload });
      else await create.mutateAsync(payload);
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title={ruleId ? "Edit rule" : "New rule"} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Room type (blank = all)" htmlFor="nr-room">
          <select id="nr-room" className="input" {...register("room_id")}>
            <option value="">All room types</option>
            {(roomsQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.room_type}</option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Minimum price" htmlFor="nr-min" error={errors.minimum_price?.message}>
            <TextInput id="nr-min" name="minimum_price" register={register} inputMode="decimal" />
          </Field>
          <Field label="Max discount %" htmlFor="nr-disc" error={errors.maximum_discount_percent?.message}>
            <TextInput id="nr-disc" name="maximum_discount_percent" register={register} inputMode="decimal" />
          </Field>
        </div>
        {["is_enabled", "requires_approval", "is_active"].map((name) => (
          <label key={name} className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...register(name as "is_enabled")} className="h-4 w-4" />
            {name === "is_enabled" && "Rule is enabled"}
            {name === "requires_approval" && "Offers in the grey zone need staff approval"}
            {name === "is_active" && "Rule is active"}
          </label>
        ))}
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending || update.isPending}>
            {create.isPending || update.isPending ? "Saving…" : "Save rule"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function EvaluateForm({ hotelId }: { hotelId: number }) {
  const roomsQuery = useRooms(hotelId);
  const evaluate = useEvaluateNegotiation();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<NegotiationEvaluateForm>({
    resolver: zodResolver(negotiationEvaluateSchema),
  });

  async function onSubmit(values: NegotiationEvaluateForm) {
    setServerError(null);
    try {
      await evaluate.mutateAsync({ hotel_id: hotelId, ...values });
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  const result = evaluate.data;

  return (
    <div className="panel p-5">
      <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 md:grid-cols-2" noValidate>
        <Field label="Room type" htmlFor="ev-room" error={errors.room_id?.message}>
          <select id="ev-room" className="input" {...register("room_id")}>
            <option value="">Select…</option>
            {(roomsQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.room_type}</option>
            ))}
          </select>
        </Field>
        <Field label="Offered price" htmlFor="ev-price" error={errors.offered_price?.message}>
          <TextInput id="ev-price" name="offered_price" register={register} inputMode="decimal" />
        </Field>
        <Field label="Check-in" htmlFor="ev-in" error={errors.check_in?.message}>
          <TextInput id="ev-in" name="check_in" register={register} type="date" />
        </Field>
        <Field label="Check-out" htmlFor="ev-out" error={errors.check_out?.message}>
          <TextInput id="ev-out" name="check_out" register={register} type="date" />
        </Field>
        <div className="md:col-span-2">
          <button type="submit" className="btn btn-primary" disabled={evaluate.isPending}>
            {evaluate.isPending ? "Evaluating…" : "Evaluate offer"}
          </button>
        </div>
      </form>
      <FormError error={serverError} />
      {result && (
        <div className="mt-4 rounded-xl border border-line bg-paper p-4" aria-live="polite">
          <p className="font-semibold">
            {result.accepted ? (
              <span className="text-deep-teal">Offer accepted</span>
            ) : result.requires_approval ? (
              <span className="text-coral-deep">Needs staff approval</span>
            ) : (
              <span className="text-coral-deep">Offer declined</span>
            )}
          </p>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
            <div><dt className="text-ink/60">Base price</dt><dd className="font-mono">{formatMoney(result.base_price)}</dd></div>
            <div><dt className="text-ink/60">Offered</dt><dd className="font-mono">{formatMoney(result.offered_price)}</dd></div>
            <div><dt className="text-ink/60">Minimum acceptable</dt><dd className="font-mono">{formatMoney(result.minimum_acceptable_price)}</dd></div>
            <div><dt className="text-ink/60">Max discount</dt><dd className="font-mono">{result.maximum_discount_percent}%</dd></div>
          </dl>
          <p className="mt-2 text-sm text-ink/70">{result.reason}</p>
        </div>
      )}
    </div>
  );
}
