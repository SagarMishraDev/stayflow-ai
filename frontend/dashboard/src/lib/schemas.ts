import { z } from "zod";

/* Client-side mirrors of the backend pydantic constraints
 * (backend/app/schemas/*.py). Keep in sync when the API changes. */

const isoDate = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, "Use YYYY-MM-DD");

const priceString = z
  .string()
  .regex(/^\d+(\.\d{1,2})?$/, "Enter a valid amount");

export const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});
export type LoginForm = z.input<typeof loginSchema>;

export const bookingCreateSchema = z
  .object({
    guest_id: z.coerce.number().int().positive("Choose a guest"),
    room_id: z.coerce.number().int().positive("Choose a room type"),
    check_in: isoDate,
    check_out: isoDate,
    number_of_guests: z.coerce.number().int().gt(0, "At least 1 guest"),
    final_price: z
      .union([z.literal(""), priceString])
      .optional()
      .transform((v) => (v === "" || v === undefined ? undefined : v)),
    booking_status: z.enum([
      "PENDING",
      "CONFIRMED",
      "CHECKED_IN",
      "CHECKED_OUT",
      "CANCELLED",
    ]),
  })
  .refine((v) => v.check_out > v.check_in, {
    message: "Check-out must be after check-in",
    path: ["check_out"],
  });
export type BookingCreateForm = z.input<typeof bookingCreateSchema>;

export const bookingUpdateSchema = z
  .object({
    check_in: isoDate.optional(),
    check_out: isoDate.optional(),
    number_of_guests: z.coerce.number().int().gt(0).optional(),
    final_price: priceString.optional(),
    booking_status: z
      .enum(["PENDING", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"])
      .optional(),
  })
  .refine(
    (v) =>
      !v.check_in || !v.check_out || v.check_out > v.check_in,
    { message: "Check-out must be after check-in", path: ["check_out"] },
  );
export type BookingUpdateForm = z.input<typeof bookingUpdateSchema>;

export const guestSchema = z.object({
  name: z.string().min(1, "Name is required").max(200),
  phone: z.string().max(50).optional().or(z.literal("")),
  email: z.string().email("Enter a valid email").optional().or(z.literal("")),
  nationality: z.string().max(100).optional().or(z.literal("")),
  telegram_chat_id: z.string().max(100).optional().or(z.literal("")),
  whatsapp_number: z.string().max(50).optional().or(z.literal("")),
  preferences: z.string().optional().or(z.literal("")),
  notes: z.string().optional().or(z.literal("")),
  is_active: z.boolean().default(true),
});
export type GuestForm = z.input<typeof guestSchema>;

export const roomSchema = z.object({
  room_type: z.string().min(1, "Room type is required").max(200),
  description: z.string().optional().or(z.literal("")),
  capacity: z.coerce.number().int().min(1, "Capacity must be at least 1"),
  total_rooms: z.coerce.number().int().min(1, "At least 1 physical room"),
  amenities: z.string().optional().or(z.literal("")),
  is_active: z.boolean().default(true),
});
export type RoomForm = z.input<typeof roomSchema>;

/** Backend: RateCreate.price = Field(gt=0). */
export const rateSchema = z.object({
  room_id: z.coerce.number().int().positive("Choose a room type"),
  date: isoDate,
  price: z.coerce.number().gt(0, "Price must be greater than 0"),
  currency: z.string().min(1).max(10).default("INR"),
  is_active: z.boolean().default(true),
});
export type RateForm = z.input<typeof rateSchema>;

/** Bulk rate entry: one price across a date range for one room type. */
export const bulkRateSchema = z
  .object({
    room_id: z.coerce.number().int().positive("Choose a room type"),
    start_date: isoDate,
    end_date: isoDate,
    price: z.coerce.number().gt(0, "Price must be greater than 0"),
    currency: z.string().min(1).max(10).default("INR"),
  })
  .refine((v) => v.end_date >= v.start_date, {
    message: "End date must be on or after the start date",
    path: ["end_date"],
  });
export type BulkRateForm = z.input<typeof bulkRateSchema>;

export const availabilitySchema = z.object({
  room_id: z.coerce.number().int().positive("Choose a room type"),
  date: isoDate,
  available_rooms: z.coerce.number().int().min(0, "Cannot be negative"),
  is_active: z.boolean().default(true),
});
export type AvailabilityForm = z.input<typeof availabilitySchema>;

export const hotelSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional().or(z.literal("")),
  city: z.string().min(1, "City is required"),
  address: z.string().optional().or(z.literal("")),
  phone: z.string().max(50).optional().or(z.literal("")),
  email: z.string().email("Enter a valid email").optional().or(z.literal("")),
  timezone: z.string().min(1).default("Asia/Kolkata"),
  currency: z.string().min(1).max(10).default("INR"),
  is_active: z.boolean().default(true),
});
export type HotelForm = z.input<typeof hotelSchema>;

export const hotelUserCreateSchema = z.object({
  name: z.string().min(1, "Name is required"),
  email: z.string().email("Enter a valid email address"),
  phone: z.string().max(50).optional().or(z.literal("")),
  role: z.enum(["super_admin", "hotel_admin", "staff"], {
    errorMap: () => ({ message: "Choose a role" }),
  }),
  password: z.string().min(8, "Password must be at least 8 characters"),
  hotel_id: z.coerce.number().int().positive().optional(),
});
export type HotelUserCreateForm = z.input<typeof hotelUserCreateSchema>;

export const hotelUserUpdateSchema = z.object({
  name: z.string().min(1).optional().or(z.literal("")),
  phone: z.string().max(50).optional().or(z.literal("")),
  role: z.enum(["super_admin", "hotel_admin", "staff"]).optional(),
  is_active: z.boolean().optional(),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .optional()
    .or(z.literal("")),
});
export type HotelUserUpdateForm = z.input<typeof hotelUserUpdateSchema>;

export const policySchema = z.object({
  policy_type: z.string().min(1, "Policy type is required"),
  title: z.string().min(1, "Title is required"),
  description: z.string().min(1, "Description is required"),
  is_active: z.boolean().default(true),
});
export type PolicyForm = z.input<typeof policySchema>;

export const faqSchema = z.object({
  question: z.string().min(1, "Question is required"),
  answer: z.string().min(1, "Answer is required"),
  category: z.string().optional().or(z.literal("")),
  is_active: z.boolean().default(true),
});
export type FaqForm = z.input<typeof faqSchema>;

export const serviceSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional().or(z.literal("")),
  price: z
    .union([z.literal(""), priceString])
    .optional()
    .transform((v) => (v === "" || v === undefined ? undefined : v)),
  category: z.string().optional().or(z.literal("")),
  is_active: z.boolean().default(true),
});
export type ServiceForm = z.input<typeof serviceSchema>;

export const offerSchema = z
  .object({
    name: z.string().min(1, "Name is required"),
    description: z.string().optional().or(z.literal("")),
    discount_type: z.string().min(1, "Discount type is required"),
    discount_value: z.coerce.number().min(0, "Cannot be negative"),
    valid_from: isoDate,
    valid_until: isoDate,
    is_active: z.boolean().default(true),
  })
  .refine((v) => v.valid_until >= v.valid_from, {
    message: "Valid-until must be on or after valid-from",
    path: ["valid_until"],
  });
export type OfferForm = z.input<typeof offerSchema>;

/** Backend: maximum_discount_percent = Field(ge=0, le=100). */
export const negotiationRuleSchema = z.object({
  room_id: z.coerce.number().int().positive().optional(),
  is_enabled: z.boolean().default(true),
  minimum_price: z.coerce.number().min(0, "Cannot be negative"),
  maximum_discount_percent: z.coerce
    .number()
    .min(0, "Cannot be negative")
    .max(100, "Cannot exceed 100%"),
  requires_approval: z.boolean().default(false),
  is_active: z.boolean().default(true),
});
export type NegotiationRuleForm = z.input<typeof negotiationRuleSchema>;

export const negotiationEvaluateSchema = z
  .object({
    room_id: z.coerce.number().int().positive("Choose a room type"),
    check_in: isoDate,
    check_out: isoDate,
    offered_price: z.coerce.number().gt(0, "Offered price must be positive"),
  })
  .refine((v) => v.check_out > v.check_in, {
    message: "Check-out must be after check-in",
    path: ["check_out"],
  });
export type NegotiationEvaluateForm = z.input<typeof negotiationEvaluateSchema>;

export const menuItemSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional().or(z.literal("")),
  category: z.string().optional().or(z.literal("")),
  price: z.coerce.number().min(0, "Cannot be negative"),
  is_available: z.boolean().default(true),
  is_active: z.boolean().default(true),
});
export type MenuItemForm = z.input<typeof menuItemSchema>;

export const hotelRoomSchema = z.object({
  room_id: z.coerce.number().int().positive("Choose a room type"),
  room_number: z.string().min(1, "Room number is required"),
  is_active: z.boolean().default(true),
});
export type HotelRoomForm = z.input<typeof hotelRoomSchema>;

export const serviceRequestUpdateSchema = z.object({
  room_number: z.string().max(50).optional().or(z.literal("")),
  request_text: z.string().optional().or(z.literal("")),
  status: z.enum([
    "PENDING",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
  ]),
});
export type ServiceRequestUpdateForm = z.input<typeof serviceRequestUpdateSchema>;

export const documentSchema = z.object({
  title: z.string().min(1, "Title is required").max(255),
  content: z.string().min(1, "Content is required"),
  source: z.string().max(100).default("manual"),
  chunk_size: z.coerce.number().int().min(1).max(2000).default(120),
  overlap: z.coerce.number().int().min(0).max(1999).default(20),
});
export type DocumentForm = z.input<typeof documentSchema>;

export const staffMessageSchema = z.object({
  message: z.string().min(1, "Message is required").max(4000),
});
export type StaffMessageForm = z.input<typeof staffMessageSchema>;

/** Money from the API arrives as a Decimal string; format for display. */
export function formatMoney(value: string | number | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "—";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return `${currency} ${n.toFixed(2)}`;
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value.length <= 10 ? value + "T00:00:00" : value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}
