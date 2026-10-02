import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "./lib/auth";
import { getToken } from "./lib/api";
import { queryClient } from "./lib/queries";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Home from "./pages/Home";
import Bookings from "./pages/Bookings";
import BookingDetail from "./pages/BookingDetail";
import RoomsRates from "./pages/RoomsRates";
import AvailabilityCalendar from "./pages/AvailabilityCalendar";
import Negotiations from "./pages/Negotiations";
import ServiceRequests from "./pages/ServiceRequests";
import { Conversations, ConversationDetail } from "./pages/Conversations";
import { Guests, GuestDetail } from "./pages/Guests";
import Menu from "./pages/Menu";
import Services from "./pages/Services";
import Knowledge from "./pages/Knowledge";
import Notifications from "./pages/Notifications";
import Settings from "./pages/Settings";
import Staff from "./pages/Staff";
import AuditLog from "./pages/AuditLog";
import type { ReactNode } from "react";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper">
        <div aria-busy="true" className="h-10 w-64 animate-pulse rounded-xl bg-pine-950/10" aria-label="Loading session" />
        <span className="sr-only">Loading session…</span>
      </div>
    );
  }
  if (!user || !getToken()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

/** Role gate for UI hiding only — the backend enforces the real RBAC. */
function RequireRole({ roles, children }: { roles: string[]; children: ReactNode }) {
  const { role } = useAuth();
  if (!role || !roles.includes(role)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route index element={<Home />} />
              <Route path="bookings" element={<Bookings />} />
              <Route path="bookings/:id" element={<BookingDetail />} />
              <Route path="rooms" element={<RoomsRates />} />
              <Route path="availability" element={<AvailabilityCalendar />} />
              <Route path="negotiations" element={<Negotiations />} />
              <Route path="service-requests" element={<ServiceRequests />} />
              <Route path="conversations" element={<Conversations />} />
              <Route path="conversations/:id" element={<ConversationDetail />} />
              <Route path="guests" element={<Guests />} />
              <Route path="guests/:id" element={<GuestDetail />} />
              <Route path="menu" element={<Menu />} />
              <Route path="services" element={<Services />} />
              <Route path="knowledge" element={<Knowledge />} />
              <Route path="notifications" element={<Notifications />} />
              <Route path="settings" element={<Settings />} />
              <Route
                path="staff"
                element={
                  <RequireRole roles={["hotel_admin", "super_admin"]}>
                    <Staff />
                  </RequireRole>
                }
              />
              <Route
                path="audit-log"
                element={
                  <RequireRole roles={["super_admin"]}>
                    <AuditLog />
                  </RequireRole>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
