"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  Stethoscope, Mail, Lock, AlertCircle, Activity, ShieldCheck, Gauge,
} from "lucide-react";
import styles from "./login.module.css";

const BACKEND = process.env.NEXT_PUBLIC_EVALRA_API || "http://localhost:8100";

const FEATURES = [
  {
    Icon: Activity,
    title: "Recurring pulse checks",
    desc: "Schedule automated calls that check up on your agent around the clock.",
  },
  {
    Icon: Gauge,
    title: "Stress-test real conditions",
    desc: "Noise, interruptions, and language switches — before customers hit them.",
  },
  {
    Icon: ShieldCheck,
    title: "Catch failures early",
    desc: "Full transcripts, latency, and CSAT scores for every call, in one place.",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || "Login failed"); return; }
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
    <div className={styles.page}>
      <div className={styles.left}>
        <div className={styles.grid} />
        <div className={styles.glow} />

        <motion.div
          className={styles.pulseOrb}
          animate={{ scale: [1, 1.18, 1], opacity: [0.6, 1, 0.6] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
        >
          <Activity size={20} strokeWidth={2} />
        </motion.div>

        <div className={styles.content}>
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className={styles.badge}><Stethoscope size={11} /> Voice Doctor</div>
            <h1 className={styles.heading}>A check-up for your voice agents</h1>
            <p className={styles.sub}>
              Voice Doctor calls your AI agent like a real customer would — surfacing failures
              here, on your terms, instead of on a live call.
            </p>
          </motion.div>

          <motion.ul
            className={styles.features}
            initial="hidden"
            animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.12, delayChildren: 0.2 } } }}
          >
            {FEATURES.map(({ Icon, title, desc }) => (
              <motion.li
                key={title}
                className={styles.feature}
                variants={{
                  hidden: { opacity: 0, x: -14 },
                  show: { opacity: 1, x: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] } },
                }}
              >
                <span className={styles.featureIcon}><Icon size={16} strokeWidth={1.8} /></span>
                <span className={styles.featureText}>
                  <strong>{title}</strong>
                  <span>{desc}</span>
                </span>
              </motion.li>
            ))}
          </motion.ul>
        </div>

        <div className={styles.brand}>
          by <strong>Framewise</strong>
        </div>
      </div>

      <div className={styles.right}>
        <div className="auth-card">
          <div className="auth-logo">
            <Stethoscope size={22} strokeWidth={2.5} />
            <span>Voice Doctor</span>
          </div>
          <h1 className="auth-title">Welcome back</h1>
          <p className="auth-sub">Sign in to your account</p>

          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
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
                  type="password" required autoComplete="current-password"
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  className="auth-input" placeholder="••••••••"
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
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="auth-footer">
            Don&apos;t have an account?{" "}
            <Link href="/signup" className="auth-link">Create one</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
