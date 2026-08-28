import { useCallback, useEffect, useState } from "react";

import { fetchMe, login, logout, register } from "../api/authApi";
import { ApiClientError } from "../api/http";
import type { AuthUser, LoginRequest, RegistrationRequest } from "../types/auth";

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

  const submitLogin = useCallback(
    async (payload: LoginRequest) => {
      setBusy(true);
      try {
        const response = await login(payload);
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

  const submitRegistration = useCallback(async (payload: RegistrationRequest) => {
    setBusy(true);
    try {
      await register(payload);
      setUser(null);
      setStatus("anonymous");
      setError(null);
    } catch (error) {
      setError(error instanceof ApiClientError ? error.message : "Ошибка регистрации.");
    } finally {
      setBusy(false);
    }
  }, []);

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
    login: submitLogin,
    register: submitRegistration,
    signOut,
  } as const;
}
