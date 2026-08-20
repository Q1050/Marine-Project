import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  if (user) return <Navigate to={location.state?.from || (user.is_platform_admin ? "/admin" : "/region/caribbean/jamaica/overview")} replace />;

  async function submit(event) {
    event.preventDefault(); setSubmitting(true); setError(null);
    try { const authenticated = await signIn(email, password); navigate(location.state?.from || (authenticated.is_platform_admin ? "/admin" : "/region/caribbean/jamaica/overview"), { replace: true }); }
    catch (requestError) { setError(requestError.message); }
    finally { setSubmitting(false); }
  }

  return <main className="grid min-h-screen place-items-center bg-slate-50 p-5"><section className="w-full max-w-md rounded-2xl border border-app-border bg-white p-8 shadow-xl shadow-slate-900/5"><span className="grid h-11 w-11 place-items-center rounded-xl bg-ocean-900 text-xl text-white">≋</span><p className="mt-6 text-xs font-bold uppercase tracking-[.16em] text-teal-700">Authorized monitoring partners</p><h1 className="mt-2 text-2xl font-bold">Marine Invasive Species Intelligence Platform</h1><p className="mt-2 text-sm leading-6 text-app-muted">Sign in with a trusted organization or platform-administrator account.</p><form onSubmit={submit} className="mt-6 space-y-4"><label className="block text-sm font-semibold">Email<input type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-lg border border-app-border px-3 py-2.5 font-normal" /></label><label className="block text-sm font-semibold">Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-lg border border-app-border px-3 py-2.5 font-normal" /></label>{error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}<button disabled={submitting} className="w-full rounded-lg bg-teal-700 px-4 py-3 text-sm font-bold text-white disabled:opacity-60">{submitting ? "Signing in…" : "Sign in"}</button></form><p className="mt-5 text-center text-xs text-app-muted">Public sighting submission does not require an account.</p></section></main>;
}
