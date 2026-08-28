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

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegistrationRequest extends LoginRequest {
  name: string;
  contact: string;
  password_confirmation: string;
  reason: string;
}
