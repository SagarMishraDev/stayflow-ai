import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  qk,
  useCreate,
  useFaqs,
  useHotel,
  useOffers,
  usePolicies,
  useRemove,
  useUpdate,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  faqSchema,
  formatDate,
  formatMoney,
  hotelSchema,
  offerSchema,
  type FaqForm,
  type HotelForm,
  type OfferForm,
} from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";
import type { Faq, Offer, Policy } from "../lib/types";
import { policySchema, type PolicyForm } from "../lib/schemas";

type Tab = "profile" | "policies" | "faqs" | "offers";

export default function Settings() {
  const { hotelId } = useAuth();
  const [tab, setTab] = useState<Tab>("profile");

  const tabs: { id: Tab; label: string }[] = [
    { id: "profile", label: "Hotel profile" },
    { id: "policies", label: "Policies" },
    { id: "faqs", label: "FAQs" },
    { id: "offers", label: "Offers" },
  ];

  return (
    <div>
      <PageHeader
        title="Hotel settings"
        description="The details the concierge quotes to guests: profile, policies, FAQs, and offers."
      />
      <div className="mb-6 flex gap-1.5 border-b border-pine-950/15" role="tablist" aria-label="Settings sections">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-t-lg px-4 py-2.5 text-sm font-semibold ${
              tab === t.id
                ? "border-b-2 border-pine-950 text-pine-950"
                : "text-ink/60 hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "profile" && hotelId && <ProfileSection hotelId={hotelId} />}
      {tab === "policies" && hotelId && <PoliciesSection hotelId={hotelId} />}
      {tab === "faqs" && hotelId && <FaqsSection hotelId={hotelId} />}
      {tab === "offers" && hotelId && <OffersSection hotelId={hotelId} />}
    </div>
  );
}

/* ------------------------------ Profile ------------------------------ */

function ProfileSection({ hotelId }: { hotelId: number }) {
  const hotelQuery = useHotel(hotelId);
  const update = useUpdate((id) => `/hotels/${id}`, [[ "hotel", hotelId ], ["hotels"]]);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<HotelForm>({ resolver: zodResolver(hotelSchema) });

  const hotel = hotelQuery.data;
  if (hotelQuery.isLoading) {
    return (
      <div aria-busy="true" className="panel max-w-2xl space-y-3 p-6" aria-label="Loading hotel profile">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-10 animate-pulse rounded bg-pine-950/10" />
        ))}
        <span className="sr-only">Loading hotel profile…</span>
      </div>
    );
  }
  if (hotelQuery.isError || !hotel) {
    return (
      <div role="alert" className="panel max-w-2xl p-6 text-center">
        <p className="font-semibold">Couldn't load the hotel profile</p>
        <p className="mt-1 text-sm text-ink/70">{apiErrorMessage(hotelQuery.error)}</p>
        <button type="button" className="btn btn-secondary mt-4" onClick={() => hotelQuery.refetch()}>
          Try again
        </button>
      </div>
    );
  }

  const onSubmit = async (values: HotelForm) => {
    setServerError(null);
    setSaved(false);
    const keep = (v: string | undefined, current: string | null | undefined) =>
      v && v.trim() ? v.trim() : (current ?? null);
    try {
      await update.mutateAsync({
        id: hotelId,
        data: {
          name: values.name?.trim() || hotel.name,
          description: keep(values.description, hotel.description),
          city: values.city?.trim() || hotel.city,
          address: keep(values.address, hotel.address),
          phone: keep(values.phone, hotel.phone),
          email: keep(values.email, hotel.email),
          timezone: values.timezone?.trim() || hotel.timezone,
          currency: values.currency?.trim() || hotel.currency,
          is_active: values.is_active ?? hotel.is_active,
        },
      });
      setSaved(true);
      reset();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="panel max-w-2xl space-y-4 p-6" noValidate>
      <p className="text-sm text-ink/60">
        Fields you leave blank keep their current value. Current values are
        shown in the placeholders.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Hotel name" htmlFor="h-name" error={errors.name?.message}>
          <TextInput id="h-name" name="name" register={register} placeholder={hotel.name} />
        </Field>
        <Field label="City" htmlFor="h-city" error={errors.city?.message}>
          <TextInput id="h-city" name="city" register={register} placeholder={hotel.city} />
        </Field>
      </div>
      <Field label="Description" htmlFor="h-desc">
        <textarea id="h-desc" className="input" rows={3} placeholder={hotel.description ?? ""} {...register("description")} />
      </Field>
      <Field label="Address" htmlFor="h-addr">
        <TextInput id="h-addr" name="address" register={register} placeholder={hotel.address ?? ""} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Phone" htmlFor="h-phone" error={errors.phone?.message}>
          <TextInput id="h-phone" name="phone" register={register} placeholder={hotel.phone ?? ""} />
        </Field>
        <Field label="Email" htmlFor="h-email" error={errors.email?.message}>
          <TextInput id="h-email" name="email" register={register} type="email" placeholder={hotel.email ?? ""} />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Timezone" htmlFor="h-tz">
          <TextInput id="h-tz" name="timezone" register={register} placeholder={hotel.timezone} />
        </Field>
        <Field label="Currency" htmlFor="h-cur">
          <TextInput id="h-cur" name="currency" register={register} placeholder={hotel.currency} />
        </Field>
      </div>
      <FormError error={serverError} />
      {saved && (
        <p role="status" className="rounded-lg bg-pine-100 p-3 text-sm text-pine-950">
          Hotel profile saved.
        </p>
      )}
      <button type="submit" className="btn btn-primary" disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save changes"}
      </button>
    </form>
  );
}

/* ------------------------------ Policies ------------------------------ */

function PoliciesSection({ hotelId }: { hotelId: number }) {
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<Policy | null>(null);
  const policiesQuery = usePolicies(hotelId);
  const remove = useRemove((id) => `/policies/${id}`, [qk.policies(hotelId)]);
  const [actionError, setActionError] = useState<string | null>(null);

  async function onDelete(p: Policy) {
    if (!window.confirm(`Delete the policy "${p.title}"?`)) return;
    setActionError(null);
    try {
      await remove.mutateAsync(p.id);
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
          Add policy
        </button>
      </div>
      <FormError error={actionError} />
      <ListState
        query={policiesQuery}
        emptyTitle="No policies yet"
        emptyHint="Policies (check-in time, cancellation, pets) are quoted by the concierge."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
            Add policy
          </button>
        }
        render={(policies) => (
          <ul className="space-y-3">
            {policies.map((p) => (
              <li key={p.id} className={`panel p-4 ${p.is_active ? "" : "opacity-60"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold">
                      {p.title}{" "}
                      <span className="font-mono text-xs font-normal text-ink/50">
                        {p.policy_type}
                      </span>
                    </p>
                    <p className="mt-1 text-sm text-ink/75 whitespace-pre-wrap">{p.description}</p>
                  </div>
                  <div className="flex shrink-0 gap-3 text-sm">
                    <button type="button" className="font-medium text-pine-700 underline" onClick={() => { setEditing(p); setShowModal(true); }}>
                      Edit
                    </button>
                    <button type="button" className="font-medium text-brick-600 underline" onClick={() => onDelete(p)} disabled={remove.isPending}>
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      />
      {showModal && (
        <PolicyModal
          hotelId={hotelId}
          existing={editing}
          onClose={() => { setShowModal(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function PolicyModal({
  hotelId,
  existing,
  onClose,
}: {
  hotelId: number;
  existing: Policy | null;
  onClose: () => void;
}) {
  const create = useCreate("/policies", [qk.policies(hotelId)]);
  const update = useUpdate((id) => `/policies/${id}`, [qk.policies(hotelId)]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<PolicyForm>({
    resolver: zodResolver(policySchema),
    defaultValues: existing
      ? {
          policy_type: existing.policy_type,
          title: existing.title,
          description: existing.description,
          is_active: existing.is_active,
        }
      : { is_active: true },
  });

  async function onSubmit(values: PolicyForm) {
    setServerError(null);
    const payload = {
      hotel_id: hotelId,
      policy_type: values.policy_type.trim(),
      title: values.title.trim(),
      description: values.description.trim(),
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
    <Modal title={existing ? `Edit ${existing.title}` : "Add policy"} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Policy type" htmlFor="pl-type" error={errors.policy_type?.message}>
            <TextInput id="pl-type" name="policy_type" register={register} placeholder="check_in, cancellation…" />
          </Field>
          <Field label="Title" htmlFor="pl-title" error={errors.title?.message}>
            <TextInput id="pl-title" name="title" register={register} />
          </Field>
        </div>
        <Field label="Description" htmlFor="pl-desc" error={errors.description?.message}>
          <textarea id="pl-desc" className="input" rows={4} {...register("description")} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...register("is_active")} className="h-4 w-4" />
          Active
        </label>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending || update.isPending}>
            {create.isPending || update.isPending ? "Saving…" : existing ? "Save changes" : "Add policy"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* -------------------------------- FAQs -------------------------------- */

function FaqsSection({ hotelId }: { hotelId: number }) {
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<Faq | null>(null);
  const faqsQuery = useFaqs(hotelId);
  const remove = useRemove((id) => `/faqs/${id}`, [qk.faqs(hotelId)]);
  const [actionError, setActionError] = useState<string | null>(null);

  async function onDelete(f: Faq) {
    if (!window.confirm("Delete this FAQ?")) return;
    setActionError(null);
    try {
      await remove.mutateAsync(f.id);
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
          Add FAQ
        </button>
      </div>
      <FormError error={actionError} />
      <ListState
        query={faqsQuery}
        emptyTitle="No FAQs yet"
        emptyHint="FAQs feed the concierge's answers to common guest questions."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
            Add FAQ
          </button>
        }
        render={(faqs) => (
          <ul className="space-y-3">
            {faqs.map((f) => (
              <li key={f.id} className={`panel p-4 ${f.is_active ? "" : "opacity-60"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold">{f.question}</p>
                    <p className="mt-1 text-sm text-ink/75 whitespace-pre-wrap">{f.answer}</p>
                    {f.category && (
                      <p className="mt-1 font-mono text-xs text-ink/50">{f.category}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-3 text-sm">
                    <button type="button" className="font-medium text-pine-700 underline" onClick={() => { setEditing(f); setShowModal(true); }}>
                      Edit
                    </button>
                    <button type="button" className="font-medium text-brick-600 underline" onClick={() => onDelete(f)} disabled={remove.isPending}>
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      />
      {showModal && (
        <FaqModal
          hotelId={hotelId}
          existing={editing}
          onClose={() => { setShowModal(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function FaqModal({
  hotelId,
  existing,
  onClose,
}: {
  hotelId: number;
  existing: Faq | null;
  onClose: () => void;
}) {
  const create = useCreate("/faqs", [qk.faqs(hotelId)]);
  const update = useUpdate((id) => `/faqs/${id}`, [qk.faqs(hotelId)]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FaqForm>({
    resolver: zodResolver(faqSchema),
    defaultValues: existing
      ? {
          question: existing.question,
          answer: existing.answer,
          category: existing.category ?? "",
          is_active: existing.is_active,
        }
      : { is_active: true },
  });

  async function onSubmit(values: FaqForm) {
    setServerError(null);
    const payload = {
      hotel_id: hotelId,
      question: values.question.trim(),
      answer: values.answer.trim(),
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
    <Modal title={existing ? "Edit FAQ" : "Add FAQ"} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Question" htmlFor="fq-q" error={errors.question?.message}>
          <TextInput id="fq-q" name="question" register={register} />
        </Field>
        <Field label="Answer" htmlFor="fq-a" error={errors.answer?.message}>
          <textarea id="fq-a" className="input" rows={4} {...register("answer")} />
        </Field>
        <Field label="Category" htmlFor="fq-c">
          <TextInput id="fq-c" name="category" register={register} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...register("is_active")} className="h-4 w-4" />
          Active
        </label>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending || update.isPending}>
            {create.isPending || update.isPending ? "Saving…" : existing ? "Save changes" : "Add FAQ"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------- Offers ------------------------------- */

function OffersSection({ hotelId }: { hotelId: number }) {
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<Offer | null>(null);
  const offersQuery = useOffers(hotelId);
  const remove = useRemove((id) => `/offers/${id}`, [qk.offers(hotelId)]);
  const [actionError, setActionError] = useState<string | null>(null);

  async function onDelete(o: Offer) {
    if (!window.confirm(`Delete the offer "${o.name}"?`)) return;
    setActionError(null);
    try {
      await remove.mutateAsync(o.id);
    } catch (e) {
      setActionError(apiErrorMessage(e));
    }
  }

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
          Add offer
        </button>
      </div>
      <FormError error={actionError} />
      <ListState
        query={offersQuery}
        emptyTitle="No offers yet"
        emptyHint="Offers (discounts, packages) are quoted by the concierge when they apply."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowModal(true)}>
            Add offer
          </button>
        }
        render={(offers) => (
          <div className="panel overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Discount</th>
                  <th>Valid</th>
                  <th>Active</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {offers.map((o) => (
                  <tr key={o.id} className={!o.is_active ? "opacity-60" : ""}>
                    <td>
                      <p className="font-medium">{o.name}</p>
                      {o.description && (
                        <p className="text-xs text-ink/60">{o.description}</p>
                      )}
                    </td>
                    <td className="font-mono tabular-nums">
                      {o.discount_type.toLowerCase().includes("percent")
                        ? `${o.discount_value}%`
                        : formatMoney(o.discount_value)}
                    </td>
                    <td className="whitespace-nowrap">
                      {formatDate(o.valid_from)} → {formatDate(o.valid_until)}
                    </td>
                    <td>{o.is_active ? "Yes" : "No"}</td>
                    <td className="whitespace-nowrap">
                      <button type="button" className="mr-3 font-medium text-pine-700 underline" onClick={() => { setEditing(o); setShowModal(true); }}>
                        Edit
                      </button>
                      <button type="button" className="font-medium text-brick-600 underline" onClick={() => onDelete(o)} disabled={remove.isPending}>
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
      {showModal && (
        <OfferModal
          hotelId={hotelId}
          existing={editing}
          onClose={() => { setShowModal(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function OfferModal({
  hotelId,
  existing,
  onClose,
}: {
  hotelId: number;
  existing: Offer | null;
  onClose: () => void;
}) {
  const create = useCreate("/offers", [qk.offers(hotelId)]);
  const update = useUpdate((id) => `/offers/${id}`, [qk.offers(hotelId)]);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<OfferForm>({
    resolver: zodResolver(offerSchema),
    defaultValues: existing
      ? {
          name: existing.name,
          description: existing.description ?? "",
          discount_type: existing.discount_type,
          discount_value: parseFloat(existing.discount_value),
          valid_from: existing.valid_from,
          valid_until: existing.valid_until,
          is_active: existing.is_active,
        }
      : { is_active: true },
  });

  async function onSubmit(values: OfferForm) {
    setServerError(null);
    const payload = {
      hotel_id: hotelId,
      name: values.name.trim(),
      description: values.description?.trim() || null,
      discount_type: values.discount_type.trim(),
      discount_value: values.discount_value,
      valid_from: values.valid_from,
      valid_until: values.valid_until,
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
    <Modal title={existing ? `Edit ${existing.name}` : "Add offer"} onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Name" htmlFor="of-name" error={errors.name?.message}>
          <TextInput id="of-name" name="name" register={register} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Discount type" htmlFor="of-type" error={errors.discount_type?.message}>
            <TextInput id="of-type" name="discount_type" register={register} placeholder="percent, flat…" />
          </Field>
          <Field label="Discount value" htmlFor="of-val" error={errors.discount_value?.message}>
            <TextInput id="of-val" name="discount_value" register={register} inputMode="decimal" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Valid from" htmlFor="of-from" error={errors.valid_from?.message}>
            <TextInput id="of-from" name="valid_from" register={register} type="date" />
          </Field>
          <Field label="Valid until" htmlFor="of-until" error={errors.valid_until?.message}>
            <TextInput id="of-until" name="valid_until" register={register} type="date" />
          </Field>
        </div>
        <Field label="Description" htmlFor="of-desc">
          <textarea id="of-desc" className="input" rows={2} {...register("description")} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...register("is_active")} className="h-4 w-4" />
          Active
        </label>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending || update.isPending}>
            {create.isPending || update.isPending ? "Saving…" : existing ? "Save changes" : "Add offer"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
