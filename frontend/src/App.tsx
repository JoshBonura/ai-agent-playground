import AgentRunner from "./pages/AgentRunner";
import { useAuth } from "./auth/AuthContext";
import SignIn from "./auth/SignIn";
import SignUp from "./auth/SignUp";
import ForgotPassword from "./auth/ForgotPassword";
import { useState } from "react";

export default function App() {
  const { user, loading } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup" | "forgot">("signin");

  // BYPASS: render app even if not signed in
  if (import.meta.env.VITE_BYPASS_AUTH === "true") {
    return (
      <main className="bg-gray-50 h-screen overflow-hidden">
        <AgentRunner />
      </main>
    );
  }

  if (loading) {
    return (
      <main className="min-h-screen grid place-items-center">Loading…</main>
    );
  }

  if (!user) {
    return (
      <main className="min-h-screen grid place-items-center bg-gray-50 px-4">
        <div className="w-full max-w-sm bg-white p-6 rounded-2xl shadow">
          {mode === "signin" && <SignIn />}
          {mode === "signup" && <SignUp />}
          {mode === "forgot" && <ForgotPassword />}

          <div className="mt-4 text-sm text-center text-gray-700">
            {mode !== "signin" && (
              <button
                onClick={() => setMode("signin")}
                className="underline mx-2"
              >
                Sign in
              </button>
            )}
            {mode !== "signup" && (
              <button
                onClick={() => setMode("signup")}
                className="underline mx-2"
              >
                Create account
              </button>
            )}
            {mode !== "forgot" && (
              <button
                onClick={() => setMode("forgot")}
                className="underline mx-2"
              >
                Forgot password
              </button>
            )}
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="bg-gray-50 h-screen overflow-hidden">
      <AgentRunner />
    </main>
  );
}
