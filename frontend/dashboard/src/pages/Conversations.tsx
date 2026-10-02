import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  useConversation,
  useConversationMessages,
  useConversations,
  useGuests,
  usePostStaffMessage,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  formatDateTime,
  staffMessageSchema,
  type StaffMessageForm,
} from "../lib/schemas";
import {
  DetailState,
  ListState,
  NotAvailableNotice,
  PageHeader,
} from "../components/DataStates";
import { Field, FormError } from "../components/Form";
import type { ChatMessage } from "../lib/types";

const SENDER_STYLE: Record<string, string> = {
  guest: "bg-pine-950 text-white self-end",
  agent: "bg-parchment border border-pine-950/15 self-start",
  staff: "bg-pine-100 border border-pine-700/40 self-start",
  system: "bg-transparent text-ink/60 self-center text-sm",
};

export function Conversations() {
  const { hotelId } = useAuth();
  const conversationsQuery = useConversations(hotelId);
  const guestsQuery = useGuests(hotelId);

  const guestName = useMemo(() => {
    const map = new Map<number, string>();
    (guestsQuery.data ?? []).forEach((g) => map.set(g.id, g.name));
    return (id: number | null) =>
      id === null ? "Anonymous" : map.get(id) ?? `Guest #${id}`;
  }, [guestsQuery.data]);

  return (
    <div>
      <PageHeader
        title="Guest chats"
        description="Read-only transcripts of concierge conversations across web, Telegram, and WhatsApp."
      />
      <div className="mb-6">
        <NotAvailableNotice>
          The staff API exposes transcripts and lets staff post a reply into a
          conversation, but it has no escalation or flag workflow — there is no
          endpoint to flag a chat for review or assign it to a person.
        </NotAvailableNotice>
      </div>
      <ListState
        query={conversationsQuery}
        emptyTitle="No conversations yet"
        emptyHint="Guest chats through any channel will appear here."
        render={(items) => (
          <div className="panel overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Guest</th>
                  <th>Channel</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.id}>
                    <td className="font-mono">#{c.id}</td>
                    <td>{guestName(c.guest_id)}</td>
                    <td>{c.channel}</td>
                    <td>
                      {c.is_active ? c.status : "Inactive"}
                    </td>
                    <td>{formatDateTime(c.created_at)}</td>
                    <td>
                      <Link
                        to={`/conversations/${c.id}`}
                        className="font-medium text-pine-700 underline"
                      >
                        Read
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      />
    </div>
  );
}

export function ConversationDetail() {
  const { id } = useParams<{ id: string }>();
  const conversationId = id ? parseInt(id, 10) : null;
  const { hotelId } = useAuth();

  const conversationQuery = useConversation(conversationId);
  const messagesQuery = useConversationMessages(conversationId);
  const guestsQuery = useGuests(hotelId);
  const postMessage = usePostStaffMessage(conversationId);
  const [serverError, setServerError] = useState<string | null>(null);

  const guestName = useMemo(() => {
    const map = new Map<number, string>();
    (guestsQuery.data ?? []).forEach((g) => map.set(g.id, g.name));
    return (gid: number | null) =>
      gid === null ? "Anonymous" : map.get(gid) ?? `Guest #${gid}`;
  }, [guestsQuery.data]);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<StaffMessageForm>({ resolver: zodResolver(staffMessageSchema) });

  async function onSubmit(values: StaffMessageForm) {
    setServerError(null);
    try {
      await postMessage.mutateAsync({ message: values.message });
      reset();
      await messagesQuery.refetch();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  const conversation = conversationQuery.data;

  return (
    <div>
      <PageHeader
        title={conversation ? `Chat #${conversation.id}` : "Chat"}
        description={
          conversation
            ? `${guestName(conversation.guest_id)} · ${conversation.channel} · ${conversation.status}`
            : undefined
        }
        actions={
          <Link to="/conversations" className="btn btn-secondary">
            Back to chats
          </Link>
        }
      />
      <DetailState
        isLoading={conversationQuery.isLoading}
        isError={conversationQuery.isError}
        error={conversationQuery.error}
        onRetry={() => conversationQuery.refetch()}
      >
        {conversation && (
          <div className="grid gap-6 lg:grid-cols-3">
            <section
              aria-label="Transcript"
              className="panel flex max-h-[70vh] flex-col p-4 lg:col-span-2"
            >
              {messagesQuery.isLoading ? (
                <div aria-busy="true" className="space-y-2 p-2" aria-label="Loading transcript">
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="h-12 animate-pulse rounded-xl bg-pine-950/10" />
                  ))}
                  <span className="sr-only">Loading transcript…</span>
                </div>
              ) : messagesQuery.isError ? (
                <div role="alert" className="p-4 text-center">
                  <p className="font-semibold">Couldn't load the transcript</p>
                  <p className="mt-1 text-sm text-ink/70">
                    {apiErrorMessage(messagesQuery.error)}
                  </p>
                  <button
                    type="button"
                    className="btn btn-secondary mt-3"
                    onClick={() => messagesQuery.refetch()}
                  >
                    Try again
                  </button>
                </div>
              ) : (messagesQuery.data ?? []).length === 0 ? (
                <p className="p-4 text-center text-sm text-ink/60">
                  No messages in this conversation yet.
                </p>
              ) : (
                <ol className="flex flex-1 flex-col gap-2 overflow-y-auto p-1">
                  {(messagesQuery.data ?? []).map((m: ChatMessage) => (
                    <li
                      key={m.id}
                      className={`max-w-[85%] rounded-xl px-3 py-2 ${SENDER_STYLE[m.sender_type] ?? SENDER_STYLE.system}`}
                    >
                      <p className="text-sm whitespace-pre-wrap">{m.message}</p>
                      <p
                        className={`mt-1 font-mono text-[11px] ${
                          m.sender_type === "guest" ? "text-white/60" : "text-ink/50"
                        }`}
                      >
                        {m.sender_type} · {formatDateTime(m.created_at)}
                      </p>
                    </li>
                  ))}
                </ol>
              )}

              <form onSubmit={handleSubmit(onSubmit)} className="mt-3 border-t border-pine-950/10 pt-3" noValidate>
                <Field label="Reply as staff" htmlFor="staff-reply" error={errors.message?.message}>
                  <div className="flex gap-2">
                    <textarea
                      id="staff-reply"
                      className="input"
                      rows={2}
                      placeholder="Type a staff reply…"
                      {...register("message")}
                    />
                    <button
                      type="submit"
                      className="btn btn-primary shrink-0 self-start"
                      disabled={postMessage.isPending}
                    >
                      {postMessage.isPending ? "Sending…" : "Send reply"}
                    </button>
                  </div>
                </Field>
                <FormError error={serverError} />
                <p className="mt-1 text-xs text-ink/50">
                  Posted into the conversation as a staff message via the API.
                </p>
              </form>
            </section>

            <aside aria-label="Conversation details" className="space-y-4">
              <div className="panel p-4">
                <h2 className="panel-title mb-2">Details</h2>
                <dl className="space-y-1.5 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-ink/60">Guest</dt>
                    <dd>
                      {conversation.guest_id ? (
                        <Link
                          to={`/guests/${conversation.guest_id}`}
                          className="font-medium text-pine-700 underline"
                        >
                          {guestName(conversation.guest_id)}
                        </Link>
                      ) : (
                        "Anonymous"
                      )}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink/60">Channel</dt>
                    <dd>{conversation.channel}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink/60">Status</dt>
                    <dd>{conversation.status}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink/60">Started</dt>
                    <dd>{formatDateTime(conversation.created_at)}</dd>
                  </div>
                </dl>
              </div>
              <NotAvailableNotice>
                Flagging or escalating this chat is not supported by the staff
                API.
              </NotAvailableNotice>
            </aside>
          </div>
        )}
      </DetailState>
    </div>
  );
}
