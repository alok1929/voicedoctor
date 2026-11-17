"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Stethoscope, Mail, Lock, User, AlertCircle } from "lucide-react";

const BACKEND = process.env.NEXT_PUBLIC_EVALRA_API || "http://localhost:8100";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 6) { setError("Password must be at least 6 characters"); return; }
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || "Signup failed"); return; }
      localStorage.setItem("evalra_token", data.token);
      localStorage.setItem("evalra_user", JSON.stringify({ email: data.email, name: data.name }));
      document.cookie = `evalra_token=${data.token}; path=/; max-age=${30 * 24 * 3600}`;
      router.push("/dashboard");
    } catch {
      setError("Cannot reach the server — is evalra_backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-logo">
          <Stethoscope size={22} strokeWidth={2.5} />
          <span>Voice Doctor</span>
        </div>
        <h1 className="auth-title">Create your account</h1>
        <p className="auth-sub">Start evaluating your voice agents</p>

        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div className="auth-field">
            <label className="auth-label">Full name</label>
            <div className="auth-input-wrap">
              <input
                type="text" required autoComplete="name"
                value={name} onChange={(e) => setName(e.target.value)}
                className="auth-input" placeholder="Jane Smith"
              />
            </div>
          </div>

          <div className="auth-field">
            <label className="auth-label">Email</label>
            <div className="auth-input-wrap">
              <input
                type="email" required autoComplete="email"
                value={email} onChange={(e) => setEmail(e.target.value)}
                className="auth-input" placeholder="you@company.com"
              />
            </div>
          </div>

          <div className="auth-field">
            <label className="auth-label">Password</label>
            <div className="auth-input-wrap">
              <input
                type="password" required autoComplete="new-password"
                value={password} onChange={(e) => setPassword(e.target.value)}
                className="auth-input" placeholder="min. 6 characters"
              />
            </div>
          </div>

          {error && (
            <div className="auth-error">
              <AlertCircle size={14} />
              {error}
            </div>
          )}

          <button type="submit" disabled={loading} className="auth-btn">
            {loading ? <span className="spinner" /> : null}
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="auth-footer">
          Already have an account?{" "}
          <Link href="/login" className="auth-link">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
