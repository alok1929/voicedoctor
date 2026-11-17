"use client";

import { useEffect, useState } from "react";
import styles from "./landing.module.css";

// Indian languages only — native script for "Doctor"
const WORDS = [
  "Doctor",       // English
  "डॉक्टर",        // Hindi
  "ডাক্তার",        // Bengali
  "డాక్టర్",        // Telugu
  "மருத்துவர்",     // Tamil
  "ડૉક્ટર",        // Gujarati
  "ವೈದ್ಯರು",       // Kannada
  "ഡോക്ടർ",       // Malayalam
  "ਡਾਕਟਰ",         // Punjabi
  "ଡାକ୍ତର",        // Odia
  "ডাক্তৰ",        // Assamese
  "ڈاکٹر",         // Urdu
  "वैद्य",          // Marathi
  "चिकित्सक",       // Maithili
  "वैद्यः",         // Sanskrit
];

const TYPE_SPEED = 90;
const DELETE_SPEED = 45;
const PAUSE_AFTER_TYPE = 1100;
const PAUSE_AFTER_DELETE = 200;

function useTypewriterCycle(words: string[]) {
  const [wordIndex, setWordIndex] = useState(0);
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<"typing" | "deleting">("typing");

  useEffect(() => {
    const word = words[wordIndex];
    let timeout: ReturnType<typeof setTimeout>;

    if (phase === "typing") {
      if (text.length < word.length) {
        timeout = setTimeout(() => setText(word.slice(0, text.length + 1)), TYPE_SPEED);
      } else {
        timeout = setTimeout(() => setPhase("deleting"), PAUSE_AFTER_TYPE);
      }
    } else {
      if (text.length > 0) {
        timeout = setTimeout(() => setText(text.slice(0, -1)), DELETE_SPEED);
      } else {
        timeout = setTimeout(() => {
          setWordIndex((i) => (i + 1) % words.length);
          setPhase("typing");
        }, PAUSE_AFTER_DELETE);
      }
    }
    return () => clearTimeout(timeout);
  }, [text, phase, wordIndex, words]);

  return text;
}

export default function MorphingWord() {
  const text = useTypewriterCycle(WORDS);

  return (
    <span className={styles.morphWrap}>
      {text}
      <span className={styles.morphCursor} />
    </span>
  );
}
