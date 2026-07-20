import { requestJson } from "./http";
import type { AuthRequest, AuthResponse } from "../types/auth";

export function fetchMe(): Promise<AuthResponse> {
  return requestJson<AuthResponse>("/api/auth/me");
}

export function login(payload: AuthRequest): Promise<AuthResponse> {
  return requestJson<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function register(payload: AuthRequest): Promise<AuthResponse> {
  return requestJson<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function logout(): Promise<{ status: string }> {
  return requestJson<{ status: string }>("/api/auth/logout", {
    method: "POST",
  });
}
