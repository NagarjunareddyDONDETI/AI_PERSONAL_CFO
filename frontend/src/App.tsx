import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AuthUser,
  Capabilities,
  DashboardData,
  fetchMe,
  getCapabilities,
  getDashboard,
  getHealth,
  getStoredUser,
  logout as clearStoredSession,
  onUnauthorized,
} from "./api";
import AuthScreen from "./components/AuthScreen";
import Dashboard from "./components/Dashboard";
import Header from "./components/Header";
import Landing from "./components/Landing";

type BackendState = "checking" | "online" | "offline";
/** "checking" until the stored token has been validated against the server. */
type AuthState = "checking" | "signed-out" | "signed-in";

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [backend, setBackend] = useState<BackendState>("checking");
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const signOut = useCallback((message?: string) => {
    clearStoredSession();
    setUser(null);
    setData(null);
    setAuthState("signed-out");
    setNotice(message ?? null);
  }, []);

  /** Pull the stored analysis for the signed-in user, if any. */
  const restoreDashboard = useCallback(async () => {
    try {
      setData(await getDashboard());
    } catch {
      setData(null); // 404 = nothing uploaded yet; anything else is non-fatal here
    }
  }, []);

  // Any 401 from any panel drops us back to the login screen rather than
  // leaving the dashboard half-loaded.
  useEffect(() => {
    onUnauthorized(() => signOut("Your session expired. Please sign in again."));
    return () => onUnauthorized(null);
  }, [signOut]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        await getHealth();
        if (cancelled) return;
        setBackend("online");
      } catch {
        if (cancelled) return;
        setBackend("offline");
        setAuthState("signed-out");
        return;
      }

      getCapabilities()
        .then((c) => !cancelled && setCapabilities(c))
        .catch(() => !cancelled && setCapabilities(null));

      // Optimistically show the cached profile, then confirm with the server so
      // a revoked or expired token cannot leave a stale signed-in shell.
      const cached = getStoredUser();
      if (cached) setUser(cached);
      const confirmed = await fetchMe();
      if (cancelled) return;
      if (!confirmed) {
        setUser(null);
        setAuthState("signed-out");
        return;
      }
      setUser(confirmed);
      // Restore the last analysis so a page refresh does not drop you back on
      // the upload screen — the server already has it. A 404 simply means this
      // account has not uploaded anything yet, which is not an error.
      await restoreDashboard();
      if (cancelled) return;
      setAuthState("signed-in");
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  if (backend === "offline") {
    return (
      <div className="ambient-bg flex min-h-screen flex-col items-center justify-center px-6 text-center">
        <div className="glass-strong max-w-md rounded-2xl p-8">
          <div className="mb-3 text-4xl">🔌</div>
          <h1 className="text-xl font-bold">Backend not reachable</h1>
          <p className="mt-2 text-sm text-slate-400">
            Start the FastAPI server, then reload:
          </p>
          <pre className="mt-3 rounded-lg bg-black/40 px-4 py-3 text-left text-xs text-teal-accent">
            cd backend{"\n"}uvicorn main:app --reload
          </pre>
          <button
            onClick={() => location.reload()}
            className="mt-4 rounded-xl bg-teal-accent px-4 py-2 text-sm font-semibold text-navy-900"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (backend === "checking" || authState === "checking") {
    return (
      <div className="ambient-bg flex min-h-screen items-center justify-center">
        <motion.div
          animate={{ opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 1.4, repeat: Infinity }}
          className="text-sm text-slate-400"
        >
          Starting your CFO…
        </motion.div>
      </div>
    );
  }

  if (authState === "signed-out" || !user) {
    return (
      <AuthScreen
        notice={notice}
        onAuthenticated={async (u) => {
          setUser(u);
          setNotice(null);
          // Signing in on a returning account should land on their dashboard,
          // not the upload screen.
          await restoreDashboard();
          setAuthState("signed-in");
        }}
      />
    );
  }

  return (
    <>
      <Header
        capabilities={capabilities}
        user={user}
        onSignOut={() => signOut()}
        showReset={!!data}
        onReset={() => setData(null)}
      />
      <AnimatePresence mode="wait">
        {!data ? (
          <motion.div
            key="landing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 1.02 }}
            transition={{ duration: 0.4 }}
          >
            <Landing onLoaded={setData} />
          </motion.div>
        ) : (
          <motion.div
            key="dashboard"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4 }}
          >
            <Dashboard data={data} capabilities={capabilities} />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
