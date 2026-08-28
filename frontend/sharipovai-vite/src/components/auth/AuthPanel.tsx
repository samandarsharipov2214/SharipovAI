import { useState, type FormEvent } from "react";
import { LockKeyhole, LogIn, UserPlus } from "lucide-react";

interface AuthPanelProps {
  busy: boolean;
  error: string | null;
  onLogin: (payload: { email: string; password: string }) => Promise<void>;
  onRegister: (payload: {
    email: string;
    password: string;
    name: string;
    contact: string;
    password_confirmation: string;
    reason: string;
  }) => Promise<void>;
}

export function AuthPanel({ busy, error, onLogin, onRegister }: AuthPanelProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [contact, setContact] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (mode === "login") {
      await onLogin({ email, password });
      return;
    }
    await onRegister({
      email,
      password,
      name: displayName,
      contact,
      password_confirmation: passwordConfirmation,
      reason: "",
    });
  };

  return (
    <section className="surface-card max-w-xl" aria-labelledby="auth-title">
      <div className="flex items-center gap-3 text-cyan-300">
        <LockKeyhole className="size-5" aria-hidden="true" />
        <h2 id="auth-title" className="text-lg font-semibold text-white">
          Авторизация для protected AI chat
        </h2>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-400">
        Зарегистрируйтесь или войдите. JWT хранится только в HttpOnly cookie на том же origin.
      </p>
      <div className="mt-5 flex gap-2">
        <button className={mode === "login" ? "primary-button" : "secondary-button"} type="button" onClick={() => setMode("login")}>
          <LogIn className="size-4" aria-hidden="true" />
          Вход
        </button>
        <button className={mode === "register" ? "primary-button" : "secondary-button"} type="button" onClick={() => setMode("register")}>
          <UserPlus className="size-4" aria-hidden="true" />
          Регистрация
        </button>
      </div>
      <form className="mt-5 space-y-4" onSubmit={submit}>
        {mode === "register" && (
          <>
          <label className="block text-sm text-slate-300">
            <span className="mb-2 block">Имя</span>
            <input
              className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-white outline-none focus:border-cyan-300"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              maxLength={120}
            />
          </label>
          <label className="block text-sm text-slate-300">
            <span className="mb-2 block">Контакт</span>
            <input
              className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-white outline-none focus:border-cyan-300"
              value={contact}
              onChange={(event) => setContact(event.target.value)}
              maxLength={320}
              required
            />
          </label>
          </>
        )}
        <label className="block text-sm text-slate-300">
          <span className="mb-2 block">Email</span>
          <input
            className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-white outline-none focus:border-cyan-300"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        {mode === "register" && (
          <label className="block text-sm text-slate-300">
            <span className="mb-2 block">Повторите пароль</span>
            <input
              className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-white outline-none focus:border-cyan-300"
              type="password"
              value={passwordConfirmation}
              onChange={(event) => setPasswordConfirmation(event.target.value)}
              minLength={12}
              required
            />
          </label>
        )}
        <label className="block text-sm text-slate-300">
          <span className="mb-2 block">Пароль</span>
          <input
            className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-white outline-none focus:border-cyan-300"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={12}
            required
          />
        </label>
        {error && <p className="text-sm text-rose-300">{error}</p>}
        <button className="primary-button" type="submit" disabled={busy}>
          {mode === "login" ? "Войти" : "Создать аккаунт"}
        </button>
      </form>
    </section>
  );
}
