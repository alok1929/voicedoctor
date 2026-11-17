"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { X } from "lucide-react";
import { Button } from "../../../components/ui";

export default function ObjectiveEditorModal({
  value,
  onChange,
  onClose,
}: {
  value: string;
  onChange: (value: string) => void;
  onClose: () => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    const len = el.value.length;
    el.setSelectionRange(len, len);
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  return (
    <motion.div
      className="objective-modal-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className="objective-modal"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 12 }}
        transition={{ type: "tween", duration: 0.2 }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="objective-modal-title"
      >
        <div className="objective-modal__head">
          <div>
            <h2 id="objective-modal-title" className="objective-modal__title">
              Objective
            </h2>
            <p className="objective-modal__sub">
              What the simulated caller is trying to achieve on this call
            </p>
          </div>
          <button type="button" className="cds-iconbtn" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="objective-modal__body">
          <textarea
            ref={textareaRef}
            className="objective-modal__textarea"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="e.g. Find out the weather in Mumbai. Ask follow-ups until you get a specific temperature."
            spellCheck
          />
        </div>

        <div className="objective-modal__foot">
          <span className="objective-modal__hint text-caption">Esc to close · changes save as you type</span>
          <Button type="button" onClick={onClose}>
            Done
          </Button>
        </div>
      </motion.div>
    </motion.div>
  );
}
