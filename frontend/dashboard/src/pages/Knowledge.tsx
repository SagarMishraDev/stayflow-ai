import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "../lib/auth";
import {
  useDeleteDocument,
  useDocument,
  useDocuments,
  useUploadDocument,
} from "../lib/queries";
import { apiErrorMessage } from "../lib/api";
import {
  documentSchema,
  formatDateTime,
  type DocumentForm,
} from "../lib/schemas";
import { ListState, PageHeader } from "../components/DataStates";
import { Field, FormError, Modal, TextInput } from "../components/Form";
import StatusBadge from "../components/StatusBadge";

export default function Knowledge() {
  const { hotelId } = useAuth();
  const [showUpload, setShowUpload] = useState(false);
  const [watchingId, setWatchingId] = useState<number | null>(null);

  const docsQuery = useDocuments(hotelId);
  const watchingQuery = useDocument(watchingId);
  const remove = useDeleteDocument(hotelId);
  const [actionError, setActionError] = useState<string | null>(null);

  async function onDelete(id: number, title: string) {
    if (!window.confirm(`Delete the document "${title}" and its chunks?`)) return;
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
        title="Knowledge base"
        description="Documents the concierge searches when answering guest questions. Ingestion runs in the background."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowUpload(true)}>
            Upload document
          </button>
        }
      />
      <FormError error={actionError} />
      <ListState
        query={docsQuery}
        emptyTitle="No knowledge documents"
        emptyHint="Upload hotel information — policies, dining hours, local guides — and the concierge will use it in answers."
        emptyAction={
          <button type="button" className="btn btn-primary" onClick={() => setShowUpload(true)}>
            Upload document
          </button>
        }
        render={(docs) => (
          <div className="panel overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Added</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id}>
                    <td className="font-medium">{d.title}</td>
                    <td className="font-mono text-xs">{d.source}</td>
                    <td>
                      <StatusBadge status={d.status} />
                      {d.status === "processing" && (
                        <button
                          type="button"
                          className="ml-2 text-xs font-medium text-pine-700 underline"
                          onClick={() => setWatchingId(d.id)}
                        >
                          Watch
                        </button>
                      )}
                    </td>
                    <td className="whitespace-nowrap">{formatDateTime(d.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="font-medium text-brick-600 underline"
                        onClick={() => onDelete(d.id, d.title)}
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

      {showUpload && hotelId && (
        <UploadModal hotelId={hotelId} onClose={() => setShowUpload(false)} />
      )}
      {watchingId !== null && (
        <WatchModal
          docId={watchingId}
          live={watchingQuery.data}
          onClose={() => setWatchingId(null)}
        />
      )}
    </div>
  );
}

function UploadModal({ hotelId, onClose }: { hotelId: number; onClose: () => void }) {
  const upload = useUploadDocument(hotelId);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<DocumentForm>({
    resolver: zodResolver(documentSchema),
    defaultValues: { source: "manual", chunk_size: 120, overlap: 20 },
  });

  async function onSubmit(values: DocumentForm) {
    setServerError(null);
    try {
      await upload.mutateAsync({
        hotel_id: hotelId,
        title: values.title,
        content: values.content,
        source: values.source,
        chunk_size: values.chunk_size,
        overlap: values.overlap,
      });
      onClose();
    } catch (e) {
      setServerError(apiErrorMessage(e));
    }
  }

  return (
    <Modal title="Upload document" onClose={onClose}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Title" htmlFor="doc-title" error={errors.title?.message}>
          <TextInput id="doc-title" name="title" register={register} placeholder="Pool & spa hours" />
        </Field>
        <Field label="Content" htmlFor="doc-content" error={errors.content?.message}>
          <textarea
            id="doc-content"
            className="input font-mono text-xs"
            rows={10}
            placeholder="Paste the document text…"
            {...register("content")}
          />
        </Field>
        <div className="grid grid-cols-3 gap-4">
          <Field label="Source" htmlFor="doc-source">
            <TextInput id="doc-source" name="source" register={register} />
          </Field>
          <Field label="Chunk size" htmlFor="doc-chunk" error={errors.chunk_size?.message}>
            <TextInput id="doc-chunk" name="chunk_size" register={register} type="number" min={1} max={2000} />
          </Field>
          <Field label="Overlap" htmlFor="doc-overlap" error={errors.overlap?.message}>
            <TextInput id="doc-overlap" name="overlap" register={register} type="number" min={0} max={1999} />
          </Field>
        </div>
        <p className="text-xs text-ink/60">
          The document is saved with status "processing" and embedded in the
          background; it becomes searchable once it flips to "ready".
        </p>
        <FormError error={serverError} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={upload.isPending}>
            {upload.isPending ? "Uploading…" : "Upload"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function WatchModal({
  docId,
  live,
  onClose,
}: {
  docId: number;
  live: { status: string; error: string | null } | undefined;
  onClose: () => void;
}) {
  return (
    <Modal title={`Ingestion — document #${docId}`} onClose={onClose}>
      <div aria-live="polite">
        <p className="text-sm">
          Status:{" "}
          {live ? (
            <StatusBadge status={live.status} />
          ) : (
            <span className="text-ink/60">loading…</span>
          )}
        </p>
        {live?.status === "failed" && live.error && (
          <p role="alert" className="mt-2 rounded-lg border border-brick-600/40 bg-brick-100 p-3 text-sm text-brick-700">
            {live.error}
          </p>
        )}
        {live?.status === "ready" && (
          <p className="mt-2 text-sm text-ink/70">
            The document is chunked, embedded, and searchable by the concierge.
          </p>
        )}
        {(!live || live.status === "processing") && (
          <p className="mt-2 text-sm text-ink/70">
            Still processing — this view refreshes every few seconds.
          </p>
        )}
      </div>
      <div className="mt-4 flex justify-end">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}
