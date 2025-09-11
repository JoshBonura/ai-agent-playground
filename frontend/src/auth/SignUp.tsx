import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { localRegister, localLogin } from "./localAuth";
import { useAuth } from "./AuthContext";

export default function SignUp() {
  const { refreshMe } = useAuth();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const em = email.trim().toLowerCase();
    if (!em) return setErr("Email is required");
    if (pw.length < 6) return setErr("Password must be at least 6 characters");
    if (pw !== confirmPw) return setErr("Passwords do not match");
    setSubmitting(true);
    try {
      await localRegister(em, pw);
      await localLogin(em, pw);
      await refreshMe();
    } catch (e: any) {
      setErr(e?.message || "Sign up failed");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h1 className="text-xl font-semibold text-center">Create account</h1>

      <div className="space-y-1">
        <label className="block text-sm text-gray-700">Email</label>
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          type="email"
          inputMode="email"
          autoComplete="email"
          required
          className="w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:ring-2 focus:ring-black"
          placeholder="you@example.com"
        />
      </div>

      <div className="space-y-1">
        <label className="block text-sm text-gray-700">Password</label>
        <div className="relative">
          <input
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            type={showPw ? "text" : "password"}
            autoComplete="new-password"
            minLength={6}
            required
            className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 outline-none focus:ring-2 focus:ring-black"
            placeholder="At least 6 characters"
          />
          <button
            type="button"
            onClick={() => setShowPw((s) => !s)}
            className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-500"
            aria-label={showPw ? "Hide password" : "Show password"}
          >
            {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
      </div>

      <div className="space-y-1">
        <label className="block text-sm text-gray-700">Confirm Password</label>
        <div className="relative">
          <input
            value={confirmPw}
            onChange={(e) => setConfirmPw(e.target.value)}
            type={showConfirm ? "text" : "password"}
            autoComplete="new-password"
            minLength={6}
            required
            className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 outline-none focus:ring-2 focus:ring-black"
            placeholder="Re-enter password"
          />
          <button
            type="button"
            onClick={() => setShowConfirm((s) => !s)}
            className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-500"
            aria-label={
              showConfirm ? "Hide confirm password" : "Show confirm password"
            }
          >
            {showConfirm ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
      </div>

      {err && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {err}
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-lg bg-black text-white py-2.5 font-medium disabled:opacity-60"
      >
        {submitting ? "Creating…" : "Create account"}
      </button>
    </form>
  );
}
