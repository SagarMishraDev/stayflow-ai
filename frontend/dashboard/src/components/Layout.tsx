import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { useHotels, useNotifications } from "../lib/queries";

const NAV: { to: string; label: string; roles?: ("staff" | "hotel_admin" | "super_admin")[] }[] = [
  { to: "/", label: "Home" },
  { to: "/bookings", label: "Bookings" },
  { to: "/rooms", label: "Rooms & rates" },
  { to: "/availability", label: "Availability" },
  { to: "/negotiations", label: "Negotiations" },
  { to: "/service-requests", label: "Service requests" },
  { to: "/conversations", label: "Guest chats" },
  { to: "/guests", label: "Guests" },
  { to: "/menu", label: "Menu" },
  { to: "/orders", label: "Food orders" },
  { to: "/services", label: "Hotel services" },
  { to: "/knowledge", label: "Knowledge base" },
  { to: "/notifications", label: "Notifications" },
  { to: "/settings", label: "Hotel settings" },
  { to: "/staff", label: "Staff & roles", roles: ["hotel_admin", "super_admin"] },
  { to: "/audit-log", label: "Audit log", roles: ["super_admin"] },
];

function linkClass(active: boolean): string {
  return active
    ? "block rounded-full bg-sun px-3.5 py-2 text-sm font-extrabold text-ink shadow-card"
    : "block rounded-full px-3.5 py-2 text-sm font-semibold text-white/85 hover:bg-white/10 hover:text-white";
}

export default function Layout() {
  const { user, role, hotelId, isSuperAdmin, logout, switchHotel } = useAuth();
  const { data: hotels } = useHotels();
  const { data: notifications } = useNotifications(hotelId, true);
  const navigate = useNavigate();
  const location = useLocation();

  const unread = notifications?.length ?? 0;
  const visibleNav = NAV.filter(
    (item) => !item.roles || (role && item.roles.includes(role as "staff")),
  );

  return (
    <div className="min-h-screen md:flex">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-white focus:p-2"
      >
        Skip to content
      </a>
      {/* Sidebar */}
      <aside className="bg-deep-teal text-white md:w-60 md:shrink-0 md:min-h-screen">
        <div className="flex items-center justify-between px-4 py-4">
          <Link to="/" className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="grid h-9 w-9 place-items-center rounded-xl bg-sun font-display text-xl font-bold text-ink ring-2 ring-inset ring-ink"
            >
              S
            </span>
            <span className="leading-tight">
              <span className="block font-display text-[1.4rem] font-bold uppercase leading-none tracking-wide">
                StayFlow Ops
              </span>
              <span className="block text-xs text-white/70">Staff console</span>
            </span>
          </Link>
        </div>
        <nav aria-label="Primary" className="px-3 pb-4">
          <ul className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
            {visibleNav.map((item) => (
              <li key={item.to} className="shrink-0">
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) => linkClass(isActive)}
                >
                  {item.label}
                  {item.to === "/notifications" && unread > 0 && (
                    <span className="ml-2 rounded-full bg-coral-deep px-2 py-0.5 text-xs font-bold text-white">
                      {unread}
                    </span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="hidden px-4 py-4 text-xs text-white/60 md:block">
          <p className="font-semibold text-white/80">{user?.name}</p>
          <p className="font-mono">{role}</p>
          <button
            type="button"
            onClick={logout}
            className="mt-2 rounded-full border border-white/25 px-3.5 py-1.5 text-xs font-bold text-white hover:bg-white/10"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main column */}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 border-b border-line bg-paper/95 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-3 md:px-8">
            <div className="min-w-0 flex-1">
              {isSuperAdmin && hotels && hotels.length > 1 ? (
                <label className="flex max-w-xs items-center gap-2 text-sm">
                  <span className="shrink-0 font-medium text-ink/70">Hotel</span>
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
                <p className="truncate text-sm font-semibold">
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
                <span className="absolute -right-1 -top-1 rounded-full bg-coral-deep px-1.5 text-[11px] font-bold text-white">
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
