/* TypeScript mirrors of backend/app/schemas/*.py.
 * Field names and optionality are copied from the pydantic models; do not
 * add fields the API does not return. */

export type Role = "super_admin" | "hotel_admin" | "staff";

export interface Hotel {
  id: number;
  name: string;
  description: string | null;
  city: string;
  address: string | null;
  phone: string | null;
  email: string | null;
  timezone: string;
  currency: string;
  is_active: boolean;
  public_id: string | null;
  check_in_time: string | null;
  check_out_time: string | null;
}

export interface HotelUser {
  id: number;
  hotel_id: number;
  name: string;
  email: string;
  phone: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface Room {
  id: number;
  hotel_id: number;
  room_type: string;
  description: string | null;
  capacity: number;
  total_rooms: number;
  amenities: string | null;
  is_active: boolean;
}

export interface Rate {
  id: number;
  room_id: number;
  date: string; // ISO date
  price: string; // Decimal serialized as string
  currency: string;
  is_active: boolean;
}

export interface Availability {
  id: number;
  room_id: number;
  date: string;
  available_rooms: number;
  is_active: boolean;
}

export interface Policy {
  id: number;
  hotel_id: number;
  policy_type: string;
  title: string;
  description: string;
  is_active: boolean;
}

export interface Faq {
  id: number;
  hotel_id: number;
  question: string;
  answer: string;
  category: string | null;
  is_active: boolean;
}

export interface Service {
  id: number;
  hotel_id: number;
  name: string;
  description: string | null;
  price: string | null;
  category: string | null;
  is_active: boolean;
}

export interface Offer {
  id: number;
  hotel_id: number;
  name: string;
  description: string | null;
  discount_type: string;
  discount_value: string;
  valid_from: string;
  valid_until: string;
  is_active: boolean;
}

export interface NegotiationRule {
  id: number;
  hotel_id: number;
  room_id: number | null;
  is_enabled: boolean;
  minimum_price: string;
  maximum_discount_percent: string;
  requires_approval: boolean;
  is_active: boolean;
}

export interface NegotiationEvaluation {
  accepted: boolean;
  requires_approval: boolean;
  base_price: string;
  offered_price: string;
  minimum_acceptable_price: string;
  maximum_discount_percent: string;
  reason: string;
}

export interface Guest {
  id: number;
  hotel_id: number;
  name: string;
  phone: string | null;
  email: string | null;
  nationality: string | null;
  telegram_chat_id: string | null;
  whatsapp_number: string | null;
  preferences: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
}

export type BookingStatus =
  | "PENDING"
  | "CONFIRMED"
  | "CHECKED_IN"
  | "CHECKED_OUT"
  | "CANCELLED";

export interface Booking {
  id: number;
  hotel_id: number;
  guest_id: number;
  room_id: number;
  check_in: string;
  check_out: string;
  number_of_guests: number;
  final_price: string;
  booking_status: BookingStatus;
  created_at: string;
}

export interface NightQuote {
  date: string;
  price: string | null;
}

export interface BookingQuote {
  room_id: number;
  check_in: string;
  check_out: string;
  currency: string;
  nights: NightQuote[];
  total: string;
  missing_dates: string[];
  fully_priced: boolean;
}

export interface AvailabilityNight {
  date: string;
  capacity: number;
  booked: number;
  available: number;
}

export type OrderStatus =
  | "PENDING"
  | "CONFIRMED"
  | "PREPARING"
  | "READY"
  | "DELIVERED"
  | "CANCELLED";

export type OrderType = "DINE_IN" | "ROOM_SERVICE" | "TAKEAWAY";

export interface Order {
  id: number;
  hotel_id: number;
  guest_id: number;
  room_id: number | null;
  order_type: OrderType;
  table_number: number | null;
  status: OrderStatus;
  total_amount: string; // Decimal serialized as string
  created_at: string;
  is_active: boolean;
}

export interface OrderItem {
  id: number;
  order_id: number;
  menu_item_id: number;
  quantity: number;
  unit_price: string; // Decimal serialized as string
  customization: string | null;
  subtotal: string; // Decimal serialized as string
}

export interface MenuItem {
  id: number;
  hotel_id: number;
  name: string;
  description: string | null;
  category: string | null;
  price: string;
  is_available: boolean;
  is_active: boolean;
}

export interface HotelRoom {
  id: number;
  hotel_id: number;
  room_id: number;
  room_number: string;
  is_active: boolean;
}

export type ServiceRequestStatus =
  | "PENDING"
  | "ACKNOWLEDGED"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "CANCELLED";

export interface ServiceRequest {
  id: number;
  hotel_id: number;
  guest_id: number;
  service_id: number;
  room_number: string | null;
  request_text: string | null;
  status: ServiceRequestStatus;
  created_at: string;
}

export interface Conversation {
  id: number;
  hotel_id: number;
  guest_id: number | null;
  channel: string;
  status: string;
  is_active: boolean;
  created_at: string;
}

export type SenderType = "guest" | "agent" | "staff" | "system";

export interface ChatMessage {
  id: number;
  conversation_id: number;
  sender_type: SenderType;
  message: string;
  message_type: string;
  created_at: string;
}

export interface AuditLog {
  id: number;
  hotel_id: number;
  actor_type: string;
  actor_id: number | null;
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  details: string | null;
  created_at: string;
}

export interface Notification {
  id: number;
  hotel_id: number;
  user_id: number;
  type: string;
  title: string;
  message: string;
  reference_type: string | null;
  reference_id: number | null;
  is_read: boolean;
  created_at: string;
}

export type DocumentStatus = "processing" | "ready" | "failed";

export interface KnowledgeDocument {
  id: number;
  hotel_id: number;
  title: string;
  source: string;
  status: string; // "processing" | "ready" | "failed"
  error: string | null;
  created_at: string;
}

/** Mirrors IntegrationSettingsResponse in backend/app/api/integrations.py.
 * Secrets are never included — only presence flags and a fingerprint. */
export interface IntegrationSettings {
  hotel_id: number;
  public_id: string;
  has_integration_secret: boolean;
  integration_secret_fingerprint: string | null;
  integration_configured: boolean;
  integration_webhook_url: string | null;
  has_webhook_secret: boolean;
  widget_base_url: string;
}

export interface SecretRotateResponse {
  integration_secret: string;
  integration_secret_fingerprint: string;
}

export interface WebhookSecretRotateResponse {
  integration_webhook_secret: string;
}

export interface TokenPayload {
  sub: string;
  hotel_user_id: number;
  hotel_id: number;
  role: string;
  exp: number;
  iat: number;
}
