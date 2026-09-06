import { useState } from "react";
import { motion } from "framer-motion";
import { AuthUser, login, register } from "../api";

type Mode = "login" | "register";

const MIN_PASSWORD = 8;

interface Props {
  onAuthenticated: (user: AuthUser) => void;
  /** Shown when the previous session expired rather than on a fresh visit. */
  notice?: string | null;
}

const FIELD =
  "w-full rounded-xl border border-white/10 bg-black/25 px-4 py-2.5 text-sm text-slate-100 outline-none transition-colors placeholder:text-slate-500 focus:border-teal-accent/50 disabled:opacity-50";

export default function AuthScreen({ onAuthenticated, notice }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const isRegister = mode === "register";

  function switchMode(next: Mode) {
    setMode(next);
    setError("");
    setPassword("");
    setConfirm("");
  }

  // Client-side checks mirror the server's, purely so mistakes surface without
  // a round trip. The server validates independently and is the real gate.
  function localProblem(): string | null {
    if (!email.trim()) return "Enter your email address.";
    if (!/^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$/.test(email.trim()))
      return "Enter a valid email address.";
    if (password.length < MIN_PASSWORD)
      return `Password must be at least ${MIN_PASSWORD} characters.`;
    if (isRegister && password !== confirm) return "Passwords do not match.";
    return null;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const problem = localProblem();
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const session = isRegister
        ? await register({ email: email.trim(), password, name: name.trim() })
        : await login({ email: email.trim(), password });
      onAuthenticated(session.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ambient-bg flex min-h-screen items-center justify-center px-4 py-10">
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="glass-strong w-full max-w-md rounded-2xl p-7"
      >
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-violet-accent to-teal-accent text-lg font-extrabold text-navy-900">
            ₹
          </div>
          <div>
            <h1 className="text-lg font-bold leading-tight">AI Personal CFO</h1>
            <p className="text-[11px] leading-tight text-slate-400">
              {isRegister
                ? "Create an account to analyse your statements."
                : "Sign in to your finances."}
            </p>
          </div>
        </div>

        {notice && (
          <p
            role="status"
            className="mb-4 rounded-xl bg-amber-500/10 px-3 py-2 text-[12px] text-amber-200"
          >
            {notice}
          </p>
        )}

        {/* Mode toggle */}
        <div
          role="tablist"
          aria-label="Authentication mode"
          className="mb-5 grid grid-cols-2 gap-1 rounded-xl bg-black/25 p-1"
        >
          {(["login", "register"] as Mode[]).map((m) => (
            <button
              key={m}
              role="tab"
              type="button"
              aria-selected={mode === m}
              onClick={() => switchMode(m)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                mode === m
                  ? "bg-white/10 text-slate-100"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {m === "login" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-3">
          {isRegister && (
            <div>
              <label htmlFor="auth-name" className="mb-1 block text-[11px] text-slate-400">
                Name <span className="text-slate-600">(optional)</span>
              </label>
              <input
                id="auth-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                disabled={busy}
                className={FIELD}
                placeholder="Ada Lovelace"
              />
            </div>
          )}

          <div>
            <label htmlFor="auth-email" className="mb-1 block text-[11px] text-slate-400">
              Email
            </label>
            <input
              id="auth-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              disabled={busy}
              className={FIELD}
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label
              htmlFor="auth-password"
              className="mb-1 block text-[11px] text-slate-400"
            >
              Password
            </label>
            <div className="relative">
              <input
                id="auth-password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={isRegister ? "new-password" : "current-password"}
                required
                disabled={busy}
                className={`${FIELD} pr-16`}
                placeholder={isRegister ? `At least ${MIN_PASSWORD} characters` : "••••••••"}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-2 py-1 text-[11px] text-slate-400 hover:text-slate-200"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
          </div>

          {isRegister && (
            <div>
              <label
                htmlFor="auth-confirm"
                className="mb-1 block text-[11px] text-slate-400"
              >
                Confirm password
              </label>
              <input
                id="auth-confirm"
                type={showPassword ? "text" : "password"}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
                disabled={busy}
                className={FIELD}
                placeholder="••••••••"
              />
            </div>
          )}

          {error && (
            <p role="alert" className="rounded-xl bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-xl bg-gradient-to-r from-teal-accent to-violet-accent px-4 py-2.5 text-sm font-semibold text-navy-900 transition-opacity disabled:opacity-50"
          >
            {busy
              ? isRegister
                ? "Creating account…"
                : "Signing in…"
              : isRegister
                ? "Create account"
                : "Sign in"}
          </button>
        </form>

        <p className="mt-5 text-center text-[11px] leading-relaxed text-slate-500">
          Your statements are analysed on your own server and stored against your
          account only. Passwords are salted and hashed — never stored in plain text.
        </p>
      </motion.div>
    </div>
  );
}
