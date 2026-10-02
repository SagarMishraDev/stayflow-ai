import {
  QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { api } from "./api";
import type {
  AuditLog,
  Availability,
  AvailabilityNight,
  Booking,
  BookingQuote,
  ChatMessage,
  Conversation,
  Faq,
  Guest,
  Hotel,
  HotelRoom,
  HotelUser,
  KnowledgeDocument,
  MenuItem,
  NegotiationEvaluation,
  NegotiationRule,
  Notification,
  Offer,
  Policy,
  Rate,
  Room,
  Service,
  ServiceRequest,
} from "./types";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

type Params = Record<string, string | number | boolean | undefined | null>;

function cleanParams(params?: Params): Params {
  const out: Params = {};
  if (params)
    for (const [k, v] of Object.entries(params))
      if (v !== undefined && v !== null && v !== "") out[k] = v;
  return out;
}

/** GET collection. */
export function useList<T>(
  key: (string | number)[],
  path: string,
  params?: Params,
  options?: Omit<UseQueryOptions<T[], Error>, "queryKey" | "queryFn">,
) {
  return useQuery<T[], Error>({
    queryKey: key,
    queryFn: async () => {
      const { data } = await api.get<T[]>(path, { params: cleanParams(params) });
      return data;
    },
    ...options,
  });
}

/** GET single resource. */
export function useDetail<T>(
  key: (string | number)[],
  path: string | null,
  options?: Omit<UseQueryOptions<T, Error>, "queryKey" | "queryFn">,
) {
  return useQuery<T, Error>({
    queryKey: key,
    queryFn: async () => {
      const { data } = await api.get<T>(path as string);
      return data;
    },
    enabled: path !== null,
    ...options,
  });
}

interface MutationOpts {
  invalidate: (string | number)[][];
  onSuccessExtra?: () => void;
}

function useApiMutation<TData, TVariables>(
  fn: (vars: TVariables) => Promise<TData>,
  { invalidate, onSuccessExtra }: MutationOpts,
) {
  const qc = useQueryClient();
  return useMutation<TData, Error, TVariables>({
    mutationFn: fn,
    onSuccess: () => {
      for (const key of invalidate) void qc.invalidateQueries({ queryKey: key });
      onSuccessExtra?.();
    },
  });
}

export function useCreate<TInput>(
  path: string,
  invalidate: (string | number)[][],
) {
  return useApiMutation<unknown, TInput>(
    async (input) => (await api.post(path, input)).data,
    { invalidate },
  );
}

export function useUpdate<TInput>(
  pathFor: (id: number) => string,
  invalidate: (string | number)[][],
) {
  return useApiMutation<unknown, { id: number } & { data: TInput }>(
    async ({ id, data }) => (await api.patch(pathFor(id), data)).data,
    { invalidate },
  );
}

export function useRemove(
  pathFor: (id: number) => string,
  invalidate: (string | number)[][],
) {
  return useApiMutation<unknown, number>(
    async (id) => (await api.delete(pathFor(id))).data,
    { invalidate },
  );
}

/* ------------------------------------------------------------------ */
/* Resource-specific hooks (query keys carry the hotel scope)          */
/* ------------------------------------------------------------------ */

export const qk = {
  hotels: ["hotels"] as (string | number)[],
  hotelUsers: (hotelId: number | null) => ["hotel-users", hotelId ?? "all"],
  rooms: (hotelId: number | null) => ["rooms", hotelId ?? "all"],
  rates: (roomId?: number | null) => ["rates", roomId ?? "all"],
  availability: (roomId?: number | null) => ["availability", roomId ?? "all"],
  policies: (hotelId: number | null) => ["policies", hotelId ?? "all"],
  faqs: (hotelId: number | null) => ["faqs", hotelId ?? "all"],
  services: (hotelId: number | null) => ["services", hotelId ?? "all"],
  offers: (hotelId: number | null) => ["offers", hotelId ?? "all"],
  negotiationRules: (hotelId: number | null) => [
    "negotiation-rules",
    hotelId ?? "all",
  ],
  guests: (hotelId: number | null) => ["guests", hotelId ?? "all"],
  bookings: (hotelId: number | null) => ["bookings", hotelId ?? "all"],
  menuItems: (hotelId: number | null) => ["menu-items", hotelId ?? "all"],
  hotelRooms: (hotelId: number | null) => ["hotel-rooms", hotelId ?? "all"],
  serviceRequests: (hotelId: number | null) => [
    "service-requests",
    hotelId ?? "all",
  ],
  conversations: (hotelId: number | null) => [
    "conversations",
    hotelId ?? "all",
  ],
  auditLogs: (hotelId: number | null) => ["audit-logs", hotelId ?? "all"],
  notifications: (hotelId: number | null) => [
    "notifications",
    hotelId ?? "all",
  ],
  documents: (hotelId: number | null) => ["documents", hotelId ?? "all"],
};

export function useHotels() {
  return useList<Hotel>(qk.hotels, "/hotels");
}
export function useHotel(id: number | null) {
  return useDetail<Hotel>(["hotel", id ?? "none"], id ? `/hotels/${id}` : null);
}

export function useHotelUsers(hotelId: number | null) {
  return useList<HotelUser>(qk.hotelUsers(hotelId), "/hotel-users", {
    hotel_id: hotelId ?? undefined,
  });
}

export function useRooms(hotelId: number | null) {
  return useList<Room>(qk.rooms(hotelId), "/rooms", {
    hotel_id: hotelId ?? undefined,
  });
}

export function useRates(roomId?: number | null) {
  return useList<Rate>(qk.rates(roomId), "/rates", {
    room_id: roomId ?? undefined,
  });
}

export function useAvailabilityRows(roomId?: number | null) {
  return useList<Availability>(qk.availability(roomId), "/availability", {
    room_id: roomId ?? undefined,
  });
}

export function usePolicies(hotelId: number | null) {
  return useList<Policy>(qk.policies(hotelId), "/policies", {
    hotel_id: hotelId ?? undefined,
  });
}

export function useFaqs(hotelId: number | null) {
  return useList<Faq>(qk.faqs(hotelId), "/faqs", {
    hotel_id: hotelId ?? undefined,
  });
}

export function useServices(hotelId: number | null) {
  return useList<Service>(qk.services(hotelId), "/services", {
    hotel_id: hotelId ?? undefined,
  });
}

export function useOffers(hotelId: number | null) {
  return useList<Offer>(qk.offers(hotelId), "/offers", {
    hotel_id: hotelId ?? undefined,
  });
}

export function useNegotiationRules(hotelId: number | null) {
  return useList<NegotiationRule>(
    qk.negotiationRules(hotelId),
    "/negotiation-rules",
    { hotel_id: hotelId ?? undefined },
  );
}

export function useGuests(hotelId: number | null) {
  return useList<Guest>(qk.guests(hotelId), "/guests", {
    hotel_id: hotelId ?? undefined,
  });
}
export function useGuest(id: number | null) {
  return useDetail<Guest>(["guest", id ?? "none"], id ? `/guests/${id}` : null);
}

export function useBookings(hotelId: number | null, guestId?: number | null) {
  return useList<Booking>([...qk.bookings(hotelId), guestId ?? "all"], "/bookings", {
    hotel_id: hotelId ?? undefined,
    guest_id: guestId ?? undefined,
  });
}
export function useBooking(id: number | null) {
  return useDetail<Booking>(
    ["booking", id ?? "none"],
    id ? `/bookings/${id}` : null,
  );
}

/** Deterministic price quote used for the booking detail breakdown. */
export function useBookingQuote(args: {
  hotel_id: number;
  room_id: number;
  check_in: string;
  check_out: string;
  number_of_guests: number;
} | null) {
  return useQuery<BookingQuote, Error>({
    queryKey: ["booking-quote", args],
    queryFn: async () => (await api.post<BookingQuote>("/bookings/quote", args)).data,
    enabled: args !== null,
  });
}

/** Per-night availability for a room type over a range. */
export function useAvailabilityCheck(
  roomId: number | null,
  checkIn: string | null,
  checkOut: string | null,
) {
  return useQuery<{ nights: AvailabilityNight[]; fully_available: boolean }, Error>({
    queryKey: ["availability-check", roomId, checkIn, checkOut],
    queryFn: async () =>
      (
        await api.get("/bookings/availability-check", {
          params: { room_id: roomId, check_in: checkIn, check_out: checkOut },
        })
      ).data,
    enabled: roomId !== null && checkIn !== null && checkOut !== null,
  });
}

export function useCancelBooking(hotelId: number | null) {
  return useApiMutation<Booking, { id: number; reason?: string }>(
    async ({ id, reason }) =>
      (
        await api.post<Booking>(
          `/bookings/${id}/cancel`,
          null,
          { params: reason ? { reason } : {} },
        )
      ).data,
    { invalidate: [qk.bookings(hotelId), ["booking"]] },
  );
}

export function useEvaluateNegotiation() {
  return useMutation<NegotiationEvaluation, Error, {
    hotel_id: number;
    room_id: number;
    check_in: string;
    check_out: string;
    offered_price: number;
  }>({
    mutationFn: async (input) =>
      (await api.post<NegotiationEvaluation>("/negotiation/evaluate", input)).data,
  });
}

export function useMenuItems(hotelId: number | null) {
  return useList<MenuItem>(qk.menuItems(hotelId), "/menu-items", {
    hotel_id: hotelId ?? undefined,
  });
}

export function useHotelRooms(hotelId: number | null) {
  return useList<HotelRoom>(qk.hotelRooms(hotelId), "/hotel-rooms", {
    hotel_id: hotelId ?? undefined,
  });
}

export function useServiceRequests(hotelId: number | null) {
  return useList<ServiceRequest>(
    qk.serviceRequests(hotelId),
    "/service-requests",
    { hotel_id: hotelId ?? undefined },
  );
}

export function useConversations(hotelId: number | null) {
  return useList<Conversation>(qk.conversations(hotelId), "/conversations", {
    hotel_id: hotelId ?? undefined,
  });
}
export function useConversation(id: number | null) {
  return useDetail<Conversation>(
    ["conversation", id ?? "none"],
    id ? `/conversations/${id}` : null,
  );
}
export function useConversationMessages(id: number | null) {
  return useList<ChatMessage>(
    ["conversation-messages", id ?? "none"],
    id ? `/conversations/${id}/messages` : "",
    undefined,
    { enabled: id !== null },
  );
}
export function usePostStaffMessage(conversationId: number | null) {
  return useApiMutation<ChatMessage, { message: string }>(
    async (input) =>
      (
        await api.post<ChatMessage>(
          `/conversations/${conversationId}/messages`,
          { sender_type: "staff", message: input.message, message_type: "TEXT" },
        )
      ).data,
    { invalidate: [["conversation-messages", conversationId ?? "none"]] },
  );
}

export function useAuditLogs(hotelId: number | null, action?: string) {
  return useList<AuditLog>([...qk.auditLogs(hotelId), action ?? "all"], "/audit-logs", {
    hotel_id: hotelId ?? undefined,
    action: action || undefined,
    limit: 200,
  });
}

export function useNotifications(hotelId: number | null, unreadOnly = false) {
  return useList<Notification>(
    [...qk.notifications(hotelId), unreadOnly ? "unread" : "all"],
    "/notifications",
    { hotel_id: hotelId ?? undefined, unread_only: unreadOnly || undefined },
  );
}
export function useMarkNotificationRead(hotelId: number | null) {
  return useApiMutation<Notification, number>(
    async (id) => (await api.patch<Notification>(`/notifications/${id}/read`)).data,
    { invalidate: [qk.notifications(hotelId)] },
  );
}

export function useDocuments(hotelId: number | null) {
  return useList<KnowledgeDocument>(qk.documents(hotelId), "/knowledge/documents", {
    hotel_id: hotelId ?? undefined,
  });
}
export function useDocument(id: number | null) {
  return useDetail<KnowledgeDocument>(
    ["document", id ?? "none"],
    id ? `/knowledge/documents/${id}` : null,
    // Poll while ingestion is still processing.
    { refetchInterval: 5000 },
  );
}
export function useUploadDocument(hotelId: number | null) {
  return useCreate<{ hotel_id: number } & Record<string, unknown>>(
    "/knowledge/documents",
    [qk.documents(hotelId)],
  );
}
export function useDeleteDocument(hotelId: number | null) {
  return useRemove((id) => `/knowledge/documents/${id}`, [qk.documents(hotelId)]);
}
