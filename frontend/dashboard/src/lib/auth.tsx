import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  apiErrorMessage,
  clearToken,
  getToken,
  setToken,
} from "./api";
import type { HotelUser, Role, TokenPayload } from "./types";

function decodePayload(token: string): TokenPayload | null {
  try {
    const [, body] = token.split(".");
    return JSON.parse(atob(body.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

interface AuthState {
  user: HotelUser | null;
  tokenPayload: TokenPayload | null;
  hotelId: number | null;
  role: Role | null;
  isSuperAdmin: boolean;
  isHotelAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  switchHotel: (id: number) => void;
  loading: boolean;
}

/** Active hotel for data scoping. super_admin may switch hotels; everyone
 *  else is pinned to their own hotel (backend enforces this regardless). */
const HOTEL_KEY = "stayflow_hotel_id";

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [user, setUser] = useState<HotelUser | null>(null);
  const [payload, setPayload] = useState<TokenPayload | null>(() => {
    const t = getToken();
    return t ? decodePayload(t) : null;
  });
  const [hotelId, setHotelId] = useState<number | null>(() => {
    const raw = localStorage.getItem(HOTEL_KEY);
    const id = raw ? parseInt(raw, 10) : NaN;
    return Number.isInteger(id) ? id : null;
  });
  const [loading, setLoading] = useState<boolean>(!!getToken());

  const fetchMe = useCallback(async () => {
    const token = getToken();
    const p = token ? decodePayload(token) : null;
    if (!p) {
      setUser(null);
      setPayload(null);
      setLoading(false);
      return;
    }
    try {
      const { data } = await api.get<HotelUser>(
        `/hotel-users/${p.hotel_user_id}`,
      );
      setUser(data);
      setPayload(p);
      setHotelId((prev) => {
        const next = prev ?? data.hotel_id;
        localStorage.setItem(HOTEL_KEY, String(next));
        return next;
      });
    } catch {
      // 401 interceptor clears the token and redirects.
      setUser(null);
      setPayload(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (getToken()) void fetchMe();
  }, [fetchMe]);

  const login = useCallback(
    async (email: string, password: string) => {
      const { data } = await api.post<{ access_token: string }>("/auth/login", {
        email,
        password,
      });
      setToken(data.access_token);
      const p = decodePayload(data.access_token);
      setPayload(p);
      setLoading(true);
      try {
        const { data: me } = await api.get<HotelUser>(
          `/hotel-users/${p?.hotel_user_id}`,
        );
        setUser(me);
        const next = me.hotel_id;
        setHotelId(next);
        localStorage.setItem(HOTEL_KEY, String(next));
      } catch (e) {
        throw new Error(apiErrorMessage(e));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const switchHotel = useCallback((id: number) => {
    setHotelId(id);
    localStorage.setItem(HOTEL_KEY, String(id));
  }, []);

  const logout = useCallback(() => {
    clearToken();
    localStorage.removeItem(HOTEL_KEY);
    setUser(null);
    setPayload(null);
    setHotelId(null);
    navigate("/login");
  }, [navigate]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      tokenPayload: payload,
      hotelId,
      role: (payload?.role as Role) ?? null,
      isSuperAdmin: payload?.role === "super_admin",
      isHotelAdmin:
        payload?.role === "hotel_admin" || payload?.role === "super_admin",
      login,
      logout,
      switchHotel,
      loading,
    }),
    [user, payload, hotelId, login, logout, switchHotel, loading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
