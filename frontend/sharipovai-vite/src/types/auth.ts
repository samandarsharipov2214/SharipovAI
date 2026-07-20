export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
}

export interface AuthResponse {
  status: string;
  authenticated: boolean;
  user: AuthUser | null;
}

export interface AuthRequest {
  email: string;
  password: string;
  display_name?: string;
}
