"use client";

import { motion, useInView } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Volume2, MessageSquare, VolumeX, Users, Languages, Target, Gauge, FileText,
  ArrowRight, Stethoscope, Zap, ShieldCheck,
} from "lucide-react";
import MorphingWord from "./MorphingWord";
import InstantDiagnostic from "./InstantDiagnostic";
import styles from "./landing.module.css";

const CATEGORIES = [
  { Icon: Volume2, title: "Background Noise", desc: "Inject cafés, offices, traffic, factories, and crowded environments." },
  { Icon: MessageSquare, title: "Interruptions", desc: "Measure recovery when users speak over the AI." },
  { Icon: VolumeX, title: "Silence Handling", desc: "Measure awkward pauses and dead air." },
  { Icon: Users, title: "Persona Simulation", desc: "Run calls as angry, elderly, impatient, confused, and expert users." },
  { Icon: Languages, title: "Language Switching", desc: "Switch languages mid-call and measure recovery." },
  { Icon: Target, title: "Objective Completion", desc: "Verify that the intended task was actually completed." },
  { Icon: Gauge, title: "Latency Analysis", desc: "Measure TTFT, end-to-end latency, and response delays." },
  { Icon: FileText, title: "Transcript Review", desc: "Compare expected behavior against actual outcomes." },
];

const STORY = [
  "Production is where failures happen.",
  "Voice Doctor finds those failures first.",
  "Fix them before customers ever notice.",
];

function useCountUp(target: number, active: boolean, duration = 1600) {
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (!active) return;
    let raf: number;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(Math.round(eased * target));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, target, duration]);
  return val;
}

function StatCell({ value, suffix, label }: { value: number; suffix: string; label: string }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const n = useCountUp(value, inView);
  return (
    <div ref={ref} className={styles.statCell}>
      <div className={styles.statValue}>{n.toLocaleString()}{suffix}</div>
      <div className={styles.statLabel}>{label}</div>
    </div>
  );
}

function FadeUp({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.55, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}

export default function LandingPage() {
  const heroRef = useRef<HTMLElement>(null);
  const [heroVisible, setHeroVisible] = useState(true);

  useEffect(() => {
    const el = heroRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => setHeroVisible(entry.isIntersecting),
      { threshold: 0, rootMargin: "-58px 0px 0px 0px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  return (
    <div className={styles.page}>

      {/* ── Nav ── */}
      <nav className={`${styles.nav} ${heroVisible ? styles.navHero : ""}`}>
        <div className={styles.navInner}>
          <div className={styles.navLogo}>
            <Stethoscope size={17} strokeWidth={2.4} />
            <span>Voice Doctor</span>
            <span className={styles.navBy}>by Evalsra</span>
          </div>
          <div className={styles.navLinks}>
            <a href="#tests">What we test</a>
            <a href="#diagnose">Try it</a>
            <Link href="/login" className={styles.navCta}>Sign in</Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section ref={heroRef} className={styles.hero}>
        <div className={styles.heroGrid} />
        <div className={styles.heroGlow} />
        <div className={styles.heroCenter}>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className={styles.heroBadge}><Zap size={11} /> Built for production voice AI</div>
            <h1 className={styles.heroTitle}>
              Voice <MorphingWord />
            </h1>
            <p className={styles.heroSub}>
              A check-up for the AI voice agents you've already put in front of customers —
              so failures surface here, not on a live call.
            </p>
            <div className={styles.heroCtas}>
              <a href="#diagnose" className={styles.ctaPrimary}>
                Run a free diagnostic <ArrowRight size={15} />
              </a>
              <a href="#tests" className={styles.ctaSecondary}>What we test</a>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── Instant diagnostic ── */}
      <section id="diagnose" className={styles.section}>
        <FadeUp><InstantDiagnostic /></FadeUp>
      </section>

      {/* ── Story flow ── */}
      <section className={styles.storySection}>
        <div className={styles.storyInner}>
          {STORY.map((line, i) => (
            <FadeUp key={line} delay={i * 0.06}>
              <p className={i === STORY.length - 1 ? styles.storyLineFinal : styles.storyLine}>{line}</p>
            </FadeUp>
          ))}
        </div>
      </section>

      {/* ── What we test ── */}
      <section id="tests" className={styles.section}>
        <FadeUp>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>What Voice Doctor tests</h2>
            <p className={styles.sectionSub}>A full diagnostic panel for every condition production traffic will throw at your agent.</p>
          </div>
        </FadeUp>
        <div className={styles.catGrid}>
          {CATEGORIES.map(({ Icon, title, desc }, i) => (
            <FadeUp key={title} delay={(i % 4) * 0.06}>
              <div className={styles.catCard}>
                <div className={styles.catIcon}><Icon size={16} strokeWidth={1.8} /></div>
                <div className={styles.catTitle}>{title}</div>
                <div className={styles.catDesc}>{desc}</div>
              </div>
            </FadeUp>
          ))}
        </div>
      </section>

      {/* ── Trust strip ── */}
      <section className={styles.trustSection}>
        <FadeUp>
          <div className={styles.trustRow}>
            <ShieldCheck size={14} />
            <span>Fully on-premise · Encrypted call recordings · No customer PII retained beyond the test window</span>
          </div>
        </FadeUp>
      </section>

      {/* ── Final CTA ── */}
      <section className={styles.finalSection}>
        <FadeUp>
          <h2 className={styles.finalTitle}>Your customers will discover your bugs eventually.</h2>
          <h2 className={styles.finalTitleAccent}>Your Doctor should find them first.</h2>
          <a href="#diagnose" className={styles.finalCta}>
            Get Your Agent Diagnosed <ArrowRight size={15} />
          </a>
        </FadeUp>
      </section>

      <footer className={styles.footer}>
        <span>© {new Date().getFullYear()} Evalsra</span>
        <span>Voice Doctor — diagnostics for conversational AI</span>
      </footer>
    </div>
  );
}
