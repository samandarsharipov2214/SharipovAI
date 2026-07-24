import { useCallback, useEffect, useState } from "react";

import { fetchMe, login, logout, register } from "../api/authApi";
import { ApiClientError } from "../api/http";
import type { AuthRequest, AuthUser } from "../types/auth";

type Status = "loading" | "anonymous" | "authenticated";

export function useAuth() {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetchMe();
      setUser(response.user);
      setStatus(response.authenticated ? "authenticated" : "anonymous");
      setError(null);
    } catch {
      setUser(null);
      setStatus("anonymous");
      setError(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const submit = useCallback(
    async (mode: "login" | "register", payload: AuthRequest) => {
      setBusy(true);
      try {
        const response = mode === "login" ? await login(payload) : await register(payload);
        setUser(response.user);
        setStatus("authenticated");
        setError(null);
      } catch (error) {
        setError(error instanceof ApiClientError ? error.message : "Ошибка авторизации.");
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const signOut = useCallback(async () => {
    setBusy(true);
    try {
      await logout();
    } finally {
      setUser(null);
      setStatus("anonymous");
      setBusy(false);
    }
  }, []);

  return {
    status,
    user,
    error,
    busy,
    refresh,
    login: (payload: AuthRequest) => submit("login", payload),
    register: (payload: AuthRequest) => submit("register", payload),
    signOut,
  } as const;
}
