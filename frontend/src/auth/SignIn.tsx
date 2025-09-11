import { useState } from "react";
import { localLogin, localRegister } from "./localAuth";
import { useAuth } from "./AuthContext";

export default function SignIn() {
  const { refreshMe } = useAuth();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const em = email.trim().toLowerCase();
      if (!em) throw new Error("Email is required");
      if (mode === "signup") {
        if (pw.length < 6)
          throw new Error("Password must be at least 6 characters");
        await localRegister(em, pw);
      }
      await localLogin(em, pw);
      await refreshMe();
    } catch (e: any) {
      setErr(e?.message || "Auth failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <h1 className="text-lg font-semibold">
        {mode === "signin" ? "Sign in" : "Create account"}
      </h1>
      <input
        className="w-full border rounded px-3 py-2"
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <input
        className="w-full border rounded px-3 py-2"
        placeholder="Password"
        type="password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
      />
      {err && <div className="text-sm text-red-600">{err}</div>}
      <button
        disabled={busy}
        className="w-full rounded bg-black text-white py-2"
      >
        {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Sign up"}
      </button>
      <div className="text-sm text-center">
        {mode === "signin" ? (
          <button
            type="button"
            className="underline"
            onClick={() => setMode("signup")}
          >
            Create account
          </button>
        ) : (
          <button
            type="button"
            className="underline"
            onClick={() => setMode("signin")}
          >
            Have an account? Sign in
          </button>
        )}
      </div>
    </form>
  );
}
