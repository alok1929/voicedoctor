"""Post-call LLM judge: one structured call scoring the selected metrics + advice.

Mirrors efficientAI's typed-judge idea (boolean / rating / enum / count metrics with
a rationale) over Cekura's metric taxonomy. Returns plain dicts the report renders.
"""

import json

from loguru import logger

from app import config


def _intent_understanding_instructions(
    test_scenario, expected_understanding, metric_specs, deterministic_summary, transcript_text
):
    return (
        "You are a QA evaluator reviewing a recorded phone call.\n\n"
        "ROLES IN THE TRANSCRIPT:\n"
        "  TESTER  — automated QA caller placing the call\n"
        "  VOICERA — the production voice agent being tested\n\n"
        "Primary evaluation goal:\n"
        "  Determine whether VOICERA correctly understood what the TESTER was asking "
        "or trying to accomplish — NOT whether VOICERA knew the answer or had backend access.\n\n"
        f"Test scenario: {test_scenario}\n"
        f"Expected understanding behavior: {expected_understanding}\n\n"
        "Important:\n"
        "  Success means intent recognition and appropriate handling of the request.\n"
        "  VOICERA should PASS if it clearly demonstrates understanding, even when it:\n"
        "    - does not know the answer,\n"
        "    - lacks access to backend data, or\n"
        "    - cannot complete the requested action.\n"
        "  Inability to answer does NOT imply failure.\n"
        "  Factual correctness of any information provided is secondary and optional.\n\n"
        f"Deterministic call metrics:\n{json.dumps(deterministic_summary, indent=2)}\n\n"
        f"Full transcript:\n{transcript_text}\n\n"
        "Read the ENTIRE transcript carefully before scoring.\n\n"
        "For the 'expected_outcome' metric, use ONLY these definitions:\n"
        "  pass            — VOICERA clearly understood the TESTER's question or intent "
        "and responded appropriately to that request, even if it could not provide the "
        "information or complete the action.\n"
        "  review_required — VOICERA appeared to partially understand the request, asked "
        "clarifying questions, or responded in a way that suggests uncertainty about the intent.\n"
        "  failed          — VOICERA misunderstood the request, answered a different "
        "question, responded irrelevantly, or never demonstrated understanding of what "
        "the TESTER was asking.\n\n"
        "Examples:\n"
        "  TESTER: 'What crops should I grow in Thane?'\n"
        "  VOICERA: 'I understand you're asking for crop recommendations for Thane, but I "
        "currently don't have access to agricultural recommendations for that region.' "
        "-> PASS (understood the request)\n\n"
        "  TESTER: 'What crops should I grow in Thane?'\n"
        "  VOICERA: 'Your order is currently being processed.' "
        "-> FAILED (misunderstood intent)\n\n"
        "  TESTER: 'What crops should I grow in Thane?'\n"
        "  VOICERA: 'Are you asking about farming advice or market prices?' "
        "-> REVIEW_REQUIRED (identified the topic but needed clarification)\n\n"
        "Score ONLY these metrics:\n"
        f"{metric_specs}\n\n"
        "Respond with a JSON object of this exact shape:\n"
        '{\n'
        '  "metrics": { "<metric_key>": {"value": <value>, "reason": "<one sentence quoting or citing what VOICERA said>"}, ... },\n'
        '  "recommendations": ["<concrete improvement for VOICERA>", ...],\n'
        '  "overall": "<2-3 sentences describing whether VOICERA understood the TESTER\'s intent and how well it handled the interaction>"\n'
        "}\n\n"
        "Every reason MUST cite something VOICERA actually said (or failed to say). "
        "Use only what is in the transcript — do not infer or assume."
    )


def _factual_answer_instructions(
    test_scenario, expected_understanding, metric_specs, deterministic_summary, transcript_text
):
    return (
        "You are a QA evaluator reviewing a recorded phone call.\n\n"
        "ROLES IN THE TRANSCRIPT:\n"
        "  TESTER  — automated QA caller placing the call\n"
        "  VOICERA — the production voice agent being tested\n\n"
        "Primary evaluation goal:\n"
        "  Determine whether VOICERA provided the correct factual information or "
        "completed the expected action.\n\n"
        f"Test objective (question to answer): {test_scenario}\n"
        f"Expected correct answer/outcome: {expected_understanding}\n\n"
        f"Deterministic call metrics:\n{json.dumps(deterministic_summary, indent=2)}\n\n"
        f"Full transcript:\n{transcript_text}\n\n"
        "Read the ENTIRE transcript carefully before scoring.\n\n"
        "For the 'expected_outcome' metric, use ONLY these definitions:\n"
        "  pass            — VOICERA provided the correct information or achieved the "
        "expected outcome.\n"
        "  review_required — VOICERA partially addressed the request or the answer "
        "was ambiguous/incomplete relative to the expected outcome.\n"
        "  failed          — VOICERA gave incorrect information, failed to address the "
        "question, or did not achieve the expected outcome.\n\n"
        "Score ONLY these metrics:\n"
        f"{metric_specs}\n\n"
        "Respond with a JSON object of this exact shape:\n"
        '{\n'
        '  "metrics": { "<metric_key>": {"value": <value>, "reason": "<one sentence quoting or citing what VOICERA said>"}, ... },\n'
        '  "recommendations": ["<concrete improvement for VOICERA>", ...],\n'
        '  "overall": "<2-3 sentences describing whether VOICERA met the factual objective>"\n'
        "}\n\n"
        "Every reason MUST cite something VOICERA actually said (or failed to say). "
        "Use only what is in the transcript — do not infer or assume."
    )


def _speech_probe_instructions(deterministic_summary):
    return (
        "SPEECH-PROBE SIMULATION (deterministic metrics already measured):\n"
        "The TESTER ran a scripted probe sequence to test Voicera's handling of "
        "stop/start voice commands vs ignorable filler sounds:\n"
        "  1. After the objective question, while Voicera was answering, the tester said "
        '"stop stop" — Voicera SHOULD stop or yield.\n'
        "  2. On Voicera's next speaking turn, the tester said "
        '"start start" — Voicera SHOULD stop or react appropriately.\n'
        "  3. While Voicera was still speaking, the tester repeated filler phrases "
        '("hmm hmm", "ho ho", "ha ha") — Voicera should IGNORE these and keep talking.\n'
        "  4. A cough sound clip was played — Voicera should IGNORE it and keep talking.\n\n"
        "Key deterministic fields in the metrics below:\n"
        "  - speech_probe_stop_response_latency_s / speech_probe_start_response_latency_s: "
        "seconds from command inject to Voicera stopping\n"
        "  - speech_probe_stop_correct / speech_probe_start_correct: whether Voicera yielded\n"
        "  - speech_probe_filler_false_stops / speech_probe_filler_false_stop_rate: "
        "fillers that wrongly stopped Voicera\n"
        "  - speech_probe_cough_false_stop: whether the cough wrongly stopped Voicera\n"
        "  - speech_probe_accuracy: overall probe pass rate\n\n"
        f"Speech-probe metrics for this call:\n{json.dumps(deterministic_summary, indent=2)}\n\n"
    )


def run_judge(
    test_scenario,
    expected_understanding,
    metric_keys,
    deterministic_summary,
    transcript_lines,
    evaluation_mode=config.DEFAULT_EVALUATION_MODE,
    barge_in_style=None,
):
    """Score `metric_keys` via one OpenAI JSON call.

    Returns: {"metrics": {key: {"value":..., "reason":...}}, "recommendations": [...],
              "overall": "..."}  (best-effort; empty/partial on failure).
    """
    if not config.OPENAI_API_KEY:
        return {"metrics": {}, "recommendations": [], "overall": "(no OpenAI key configured)"}

    metric_specs = "\n".join(
        f"- {key} ({config.LLM_JUDGE_METRICS[key][1]}): return {config.LLM_JUDGE_METRICS[key][2]}"
        for key in metric_keys
        if key in config.LLM_JUDGE_METRICS
    )
    # Relabel roles so the judge cannot confuse tester and agent.
    transcript_text = "\n".join(
        line.replace("assistant:", "TESTER:", 1).replace("user:", "VOICERA:", 1)
        for line in transcript_lines
    )

    if evaluation_mode == config.EVAL_MODE_FACTUAL:
        instructions = _factual_answer_instructions(
            test_scenario, expected_understanding, metric_specs, deterministic_summary, transcript_text
        )
    else:
        instructions = _intent_understanding_instructions(
            test_scenario, expected_understanding, metric_specs, deterministic_summary, transcript_text
        )

    if (barge_in_style or "").strip().lower() == "speech_probes":
        probe_keys = [
            k for k in deterministic_summary
            if k.startswith("speech_probe_") and deterministic_summary[k] is not None
        ]
        probe_summary = {k: deterministic_summary[k] for k in probe_keys}
        if probe_summary:
            instructions = _speech_probe_instructions(probe_summary) + instructions

    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{"role": "user", "content": instructions}],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=45,
        )
        parsed = json.loads(resp.choices[0].message.content or "{}")
        return {
            "metrics": parsed.get("metrics", {}) or {},
            "recommendations": parsed.get("recommendations", []) or [],
            "overall": parsed.get("overall", "") or "",
        }
    except Exception as e:
        logger.error(f"LLM judge call failed: {e}")
        return {"metrics": {}, "recommendations": [], "overall": f"(judge failed: {e})"}
