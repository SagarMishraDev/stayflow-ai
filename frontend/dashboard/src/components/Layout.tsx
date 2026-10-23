import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { useHotels, useNotifications } from "../lib/queries";

import { roleLabel, type RoleName } from "../lib/roles";

const ALL: RoleName[] = [
  "super_admin",
  "hotel_admin",
  "manager",
  "staff",
  "receptionist",
  "kitchen",
  "housekeeping",
  "accountant",
  "maintenance",
];
const OPS: RoleName[] = ["super_admin", "hotel_admin", "manager", "staff", "receptionist"];

/** Compact stroke icons (24×24, feather-style) per nav destination. */
const ICONS: Record<string, ReactNode> = {
  "/": (
    <>
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <path d="M9 22V12h6v10" />
    </>
  ),
  "/analytics": (
    <>
      <line x1="12" y1="20" x2="12" y2="10" />
      <line x1="18" y1="20" x2="18" y2="4" />
      <line x1="6" y1="20" x2="6" y2="16" />
    </>
  ),
  "/bookings": (
    <>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </>
  ),
  "/rooms": (
    <>
      <path d="M3 18v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5" />
      <path d="M3 18h18" />
      <path d="M5 11V7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v4" />
      <path d="M3 21v-3M21 21v-3" />
    </>
  ),
  "/availability": (
    <>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
      <path d="m9 16 2 2 4-4" />
    </>
  ),
  "/negotiations": (
    <>
      <path d="M17 1l4 4-4 4" />
      <path d="M3 11V9a4 4 0 0 1 4-4h14" />
      <path d="M7 23l-4-4 4-4" />
      <path d="M21 13v2a4 4 0 0 1-4 4H3" />
    </>
  ),
  "/service-requests": (
    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
  ),
  "/conversations": (
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  ),
  "/guests": (
    <>
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
  "/menu": (
    <>
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </>
  ),
  "/orders": (
    <>
      <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
      <path d="M3 6h18" />
      <path d="M16 10a4 4 0 0 1-8 0" />
    </>
  ),
  "/services": (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  "/knowledge": (
    <>
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </>
  ),
  "/notifications": (
    <>
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </>
  ),
  "/settings": (
    <>
      <line x1="4" y1="21" x2="4" y2="14" />
      <line x1="4" y1="10" x2="4" y2="3" />
      <line x1="12" y1="21" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12" y2="3" />
      <line x1="20" y1="21" x2="20" y2="16" />
      <line x1="20" y1="12" x2="20" y2="3" />
      <line x1="1" y1="14" x2="7" y2="14" />
      <line x1="9" y1="8" x2="15" y2="8" />
      <line x1="17" y1="16" x2="23" y2="16" />
    </>
  ),
  "/staff": (
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  ),
  "/audit-log": (
    <>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M16 13H8" />
      <path d="M16 17H8" />
    </>
  ),
};

function NavIcon({ to }: { to: string }) {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
    >
      {ICONS[to] ?? ICONS["/"]}
    </svg>
  );
}

const NAV: { to: string; label: string; roles?: RoleName[] }[] = [
  { to: "/", label: "Home" },
  {
    to: "/analytics",
    label: "Analytics",
    roles: ["super_admin", "hotel_admin", "manager", "accountant"],
  },
  { to: "/bookings", label: "Bookings", roles: [...OPS, "accountant", "housekeeping"] },
  { to: "/rooms", label: "Rooms & rates", roles: ALL },
  { to: "/availability", label: "Availability", roles: [...OPS, "housekeeping"] },
  { to: "/negotiations", label: "Negotiations", roles: OPS },
  {
    to: "/service-requests",
    label: "Service requests",
    roles: [...OPS, "housekeeping", "maintenance"],
  },
  { to: "/conversations", label: "Guest chats", roles: OPS },
  { to: "/guests", label: "Guests", roles: OPS },
  { to: "/menu", label: "Menu", roles: [...OPS, "kitchen"] },
  { to: "/orders", label: "Food orders", roles: [...OPS, "kitchen"] },
  { to: "/services", label: "Hotel services", roles: [...OPS, "housekeeping", "maintenance"] },
  { to: "/knowledge", label: "Knowledge base", roles: OPS },
  { to: "/notifications", label: "Notifications" },
  { to: "/settings", label: "Hotel settings", roles: OPS },
  { to: "/staff", label: "Staff & roles", roles: ["hotel_admin", "super_admin", "manager"] },
  {
    to: "/audit-log",
    label: "Audit log",
    roles: ["hotel_admin", "super_admin", "manager", "accountant"],
  },
];

function linkClass(active: boolean): string {
  return active
    ? "relative flex items-center gap-2.5 rounded-[10px] bg-sidebar-active px-3 py-2 text-[13.5px] font-semibold text-white"
    : "relative flex items-center gap-2.5 rounded-[10px] px-3 py-2 text-[13.5px] font-medium text-[#B9CBD2] hover:bg-white/5 hover:text-white";
}

export default function Layout() {
  const { user, role, hotelId, isSuperAdmin, logout, switchHotel } = useAuth();
  const { data: hotels } = useHotels();
  const { data: notifications } = useNotifications(hotelId, true);
  const navigate = useNavigate();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  const unread = notifications?.length ?? 0;
  const visibleNav = NAV.filter(
    (item) => !item.roles || (role && item.roles.includes(role as RoleName)),
  );

  return (
    <div className="min-h-screen md:flex">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-white focus:p-2"
      >
        Skip to content
      </a>
      {/* Sidebar — View 2 navy/teal gradient shell */}
      <aside className="bg-[linear-gradient(180deg,#062F33_0%,#041F25_100%)] text-white md:sticky md:top-0 md:flex md:h-screen md:w-[200px] md:shrink-0 md:flex-col">
        <div className="flex items-center justify-between px-4 py-4">
          <Link to="/" className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="grid h-9 w-9 place-items-center rounded-[10px] bg-teal text-white"
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16" />
                <path d="M16 9h3a2 2 0 0 1 2 2v10" />
                <path d="M2 21h20" />
                <path d="M9 7h2M9 11h2M9 15h2" />
              </svg>
            </span>
            <span className="leading-tight">
              <span className="block text-[17px] font-bold leading-none tracking-tight">
                StayFlow
              </span>
              <span className="mt-0.5 block text-[11px] font-medium text-white/60">
                Grand Hotel
              </span>
            </span>
          </Link>
          <button
            type="button"
            className="rounded-lg border border-white/20 px-2.5 py-1.5 text-xs font-semibold text-white md:hidden"
            aria-expanded={navOpen}
            aria-label="Toggle navigation menu"
            onClick={() => setNavOpen((v) => !v)}
          >
            Menu
          </button>
        </div>
        <nav
          aria-label="Primary"
          className={`${navOpen ? "block" : "hidden"} px-3 pb-4 md:block md:flex-1 md:overflow-y-auto`}
        >
          <ul className="flex flex-col gap-0.5">
            {visibleNav.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) => linkClass(isActive)}
                >
                  {({ isActive }) => (
                    <>
                      {isActive ? (
                        <span
                          aria-hidden
                          className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-bright-teal"
                        />
                      ) : null}
                      <NavIcon to={item.to} />
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      {item.to === "/notifications" && unread > 0 && (
                        <span className="rounded-full bg-coral px-2 py-0.5 text-[11px] font-bold text-white">
                          {unread}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="hidden px-4 py-4 md:block">
          <div className="border-t border-white/10 pt-4">
            <p className="truncate text-[13px] font-semibold text-white">{user?.name}</p>
            <p className="mt-0.5 text-xs text-white/55">{role ? roleLabel(role) : ""}</p>
            <button
              type="button"
              onClick={logout}
              className="mt-3 rounded-lg border border-white/20 px-3 py-1.5 text-xs font-semibold text-white hover:bg-white/10"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-3 md:px-8">
            <div className="min-w-0 flex-1">
              {isSuperAdmin && hotels && hotels.length > 1 ? (
                <label className="flex max-w-xs items-center gap-2 text-sm">
                  <span className="shrink-0 font-medium text-ink-soft">Hotel</span>
                  <select
                    aria-label="Active hotel"
                    className="input"
                    value={hotelId ?? ""}
                    onChange={(e) => {
                      switchHotel(parseInt(e.target.value, 10));
                      navigate(location.pathname);
                    }}
                  >
                    {hotels.map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <p className="truncate text-sm font-semibold text-ink">
                  {hotels?.find((h) => h.id === hotelId)?.name ?? "StayFlow"}
                </p>
              )}
            </div>
            <Link
              to="/notifications"
              className="btn btn-secondary relative !px-3"
              aria-label={`Notifications${unread > 0 ? `, ${unread} unread` : ""}`}
            >
              <svg
                aria-hidden="true"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
              </svg>
              {unread > 0 && (
                <span className="absolute -right-1 -top-1 rounded-full bg-coral px-1.5 text-[11px] font-bold text-white">
                  {unread}
                </span>
              )}
            </Link>
            <button
              type="button"
              onClick={logout}
              className="btn btn-secondary !px-3 md:hidden"
            >
              Sign out
            </button>
          </div>
        </header>
        <main id="main-content" className="px-4 py-6 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
