/**
 * Client-side wake-phrase matching.
 *
 * PAIRED WITH `backend/voice/wake.py` — the two must stay in sync. The rules are
 * intentionally implemented twice because they run in two different places for
 * two different reasons:
 *
 *   - Here, against the browser's on-device speech recogniser, so that idle
 *     listening never uploads audio. This is the hot path: it runs continuously.
 *   - On the server, against Whisper, to strip a wake word the user said in the
 *     same breath as their question ("Finzo, how much did I spend on food").
 *
 * Same three guards as the Python version: an explicit deny list, edit-distance
 * matching rather than substring matching, and position anchoring. Substring
 * matching is what would make "financial" trigger the assistant.
 */

export const WAKE_WORD = "finzo";

/** Greetings permitted before the wake word. */
const LEAD_INS = new Set(["hey", "hi", "hello", "ok", "okay", "yo", "hay", "hei"]);

/** How deep into an utterance the wake word may appear. */
const MAX_LEAD_TOKENS = 3;

/**
 * Real words close enough to "finzo" to be caught by fuzzy matching but far too
 * common in financial conversation to accept.
 */
const DENY = new Set([
  "fin", "fins", "fine", "fined", "finer", "final", "finale", "finally",
  "finance", "financed", "finances", "financial", "financially",
  "finish", "finished", "finishing", "fernando", "fernanda",
  "info", "inzo", "zero", "window", "windows", "five", "font",
]);

/** One character of slop. At 2, "fins" and "into" would both match. */
const MAX_EDIT_DISTANCE = 1;

const STOP_PHRASES = new Set([
  "stop", "stop it", "wait", "hold on", "cancel", "quiet", "shut up",
  "never mind", "nevermind", "enough", "shush", "pause",
]);

/** Lowercase, strip punctuation, collapse whitespace. */
export function normalize(text: string): string {
  if (!text) return "";
  return text
    .toLowerCase()
    .replace(/-/g, " ")
    // Unicode-aware: keep letters/digits/whitespace, drop the rest.
    .replace(/[^\p{L}\p{N}\s]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Levenshtein distance, abandoned early once it exceeds `cap`. */
function editDistance(a: string, b: string, cap: number): number {
  if (a === b) return 0;
  if (Math.abs(a.length - b.length) > cap) return cap + 1;

  let previous = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    let rowMin = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      const value = Math.min(
        previous[j] + 1,
        current[j - 1] + 1,
        previous[j - 1] + cost
      );
      current.push(value);
      if (value < rowMin) rowMin = value;
    }
    if (rowMin > cap) return cap + 1;
    previous = current;
  }
  return previous[b.length];
}

function tokenIsWake(token: string): { isWake: boolean; exact: boolean } {
  if (!token || DENY.has(token)) return { isWake: false, exact: false };
  if (token === WAKE_WORD) return { isWake: true, exact: true };
  if (editDistance(token, WAKE_WORD, MAX_EDIT_DISTANCE) <= MAX_EDIT_DISTANCE) {
    return { isWake: true, exact: false };
  }
  return { isWake: false, exact: false };
}

export interface WakeMatch {
  matched: boolean;
  matchedToken: string | null;
  /** Anything said after the wake word in the same breath. */
  query: string;
  kind: "exact" | "fuzzy" | "";
}

const NO_MATCH: WakeMatch = { matched: false, matchedToken: null, query: "", kind: "" };

/**
 * Test an utterance for the wake phrase.
 *
 * Accepts "Finzo", "Hey Finzo", "Okay Finzo!" with or without a trailing query.
 * Rejects "financial", "finance", "fins", "Fernando", and any mid-sentence
 * mention.
 */
export function matchWakeWord(text: string): WakeMatch {
  const normalized = normalize(text);
  if (!normalized) return NO_MATCH;

  const tokens = normalized.split(" ");
  const limit = Math.min(tokens.length, MAX_LEAD_TOKENS);

  for (let index = 0; index < limit; index++) {
    // Only a greeting may sit in front of the wake word; anything else means the
    // user is talking about something, not addressing the assistant.
    if (index > 0 && tokens.slice(0, index).some((t) => !LEAD_INS.has(t))) break;

    const { isWake, exact } = tokenIsWake(tokens[index]);
    if (!isWake) continue;

    return {
      matched: true,
      matchedToken: tokens[index],
      query: tokens.slice(index + 1).join(" ").trim(),
      kind: exact ? "exact" : "fuzzy",
    };
  }
  return NO_MATCH;
}

/**
 * True when the user is interrupting to stop playback.
 *
 * Whole-utterance matching on purpose: "stop" alone is an interruption, but
 * "how do I stop overspending" is a question and must not cut the answer off.
 */
export function isStopCommand(text: string): boolean {
  const normalized = normalize(text);
  if (!normalized) return false;
  if (STOP_PHRASES.has(normalized)) return true;
  const match = matchWakeWord(normalized);
  return match.matched && STOP_PHRASES.has(match.query);
}
