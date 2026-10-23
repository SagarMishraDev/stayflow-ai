/* Role & capability definitions mirroring the backend.
 *
 * Backend is authoritative: app/core/roles.py (StaffRole) and
 * app/core/permissions.py (PERMISSIONS matrix). This file exists only
 * so the UI can hide navigation/actions a role cannot use — the API
 * still enforces every rule and returns 403 on violations.
 */

export const ALL_ROLES = [
  "super_admin",
  "hotel_admin",
  "manager",
  "staff",
  "receptionist",
  "kitchen",
  "housekeeping",
  "accountant",
  "maintenance",
] as const;

export type RoleName = (typeof ALL_ROLES)[number];

export const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  hotel_admin: "Hotel Admin (Owner)",
  manager: "Manager",
  staff: "Staff",
  receptionist: "Receptionist",
  kitchen: "Kitchen",
  housekeeping: "Housekeeping",
  accountant: "Accountant",
  maintenance: "Maintenance",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role.replace(/_/g, " ");
}

/** Roles a manager may create (backend MANAGER_CREATABLE_ROLES). */
export const MANAGER_CREATABLE_ROLES = [
  "receptionist",
  "kitchen",
  "housekeeping",
  "accountant",
  "maintenance",
  "staff",
] as const;

/** Roles an admin/super admin may create — everything except super_admin. */
export const ADMIN_CREATABLE_ROLES = [
  "hotel_admin",
  "manager",
  "receptionist",
  "kitchen",
  "housekeeping",
  "accountant",
  "maintenance",
  "staff",
] as const;

export function creatableRolesFor(currentRole: string | null): string[] {
  if (currentRole === "super_admin" || currentRole === "hotel_admin") {
    return [...ADMIN_CREATABLE_ROLES];
  }
  if (currentRole === "manager") return [...MANAGER_CREATABLE_ROLES];
  return [];
}

/** Capability -> roles, mirroring backend PERMISSIONS (UI hiding only). */
export const CAPABILITY_ROLES: Record<string, string[]> = {
  "analytics.view": ["super_admin", "hotel_admin", "manager", "accountant"],
  "analytics.finance": ["super_admin", "hotel_admin", "accountant"],
  "bookings.view": [
    "super_admin",
    "hotel_admin",
    "manager",
    "staff",
    "receptionist",
    "accountant",
    "housekeeping",
  ],
  "bookings.manage": ["super_admin", "hotel_admin", "manager", "staff", "receptionist"],
  "checkin.manage": ["super_admin", "hotel_admin", "manager", "staff", "receptionist"],
  "rooms.view": [...ALL_ROLES],
  "rooms.manage": ["super_admin", "hotel_admin", "manager", "staff"],
  "orders.view": ["super_admin", "hotel_admin", "manager", "staff", "receptionist", "kitchen"],
  "orders.manage": ["super_admin", "hotel_admin", "manager", "staff", "receptionist"],
  "orders.kitchen": ["super_admin", "hotel_admin", "manager", "staff", "kitchen"],
  "service_requests.view": [
    "super_admin",
    "hotel_admin",
    "manager",
    "staff",
    "receptionist",
    "housekeeping",
    "maintenance",
  ],
  "service_requests.manage": [
    "super_admin",
    "hotel_admin",
    "manager",
    "staff",
    "receptionist",
    "housekeeping",
    "maintenance",
  ],
  "housekeeping.manage": ["super_admin", "hotel_admin", "manager", "housekeeping"],
  "maintenance.manage": ["super_admin", "hotel_admin", "manager", "maintenance"],
  "menu.manage": ["super_admin", "hotel_admin", "manager", "kitchen"],
  "payments.view": ["super_admin", "hotel_admin", "manager", "staff", "receptionist", "accountant"],
  "payments.record": ["super_admin", "hotel_admin", "manager", "staff", "receptionist", "accountant"],
  "staff.view": [...ALL_ROLES],
  "staff.create_manager": ["super_admin", "hotel_admin"],
  "staff.create_staff": ["super_admin", "hotel_admin", "manager"],
  "staff.manage": ["super_admin", "hotel_admin", "manager"],
  "settings.manage": ["super_admin", "hotel_admin"],
  "audit.view": ["super_admin", "hotel_admin", "manager", "accountant"],
  "notifications.view": [...ALL_ROLES],
};

export function hasCapability(role: string | null, capability: string): boolean {
  if (!role) return false;
  return (CAPABILITY_ROLES[capability] ?? []).includes(role);
}
