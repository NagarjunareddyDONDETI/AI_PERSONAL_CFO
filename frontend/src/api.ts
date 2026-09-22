// API client + shared types for the AI Personal CFO frontend.
// In dev, requests go through the Vite proxy at /api -> http://localhost:8000.
// In production, set VITE_API_BASE to the backend URL (e.g. https://api.example.com)
// at build time; otherwise it falls back to "/api" (expects a reverse proxy).
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "/api";

// ---------- Session ----------
// The token lives in localStorage so a refresh keeps you signed in. That trades
// a little XSS exposure for usability; an httpOnly cookie would be stricter but
// needs same-site hosting or a CSRF token, neither of which this split
// frontend/backend deployment has today.
const TOKEN_KEY = "cfo.access_token";
const USER_KEY = "cfo.user";

export interface AuthUser {
  user_id: string;
  email: string;
  name: string;
  created_at?: string;
  last_login_at?: string | null;
}

export interface Session {
  access_token: string;
  token_type: string;
  expires_at: number;
  user: AuthUser;
}

let unauthorizedHandler: (() => void) | null = null;

/** Register a callback invoked when the API rejects our token (401). */
export function onUnauthorized(fn: (() => void) | null): void {
  unauthorizedHandler = fn;
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // private mode / storage disabled
  }
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

function storeSession(session: Session): Session {
  try {
    localStorage.setItem(TOKEN_KEY, session.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(session.user));
  } catch {
    /* non-fatal: the session just won't survive a reload */
  }
  return session;
}

export function clearSession(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

// ---------- Types (mirror the backend response shapes) ----------
export interface Transaction {
  date: string;
  description: string;
  amount: number;
  category: string;
}

export interface MonthlySummary {
  months: string[];
  by_month_category: Record<string, Record<string, number>>;
  monthly_income: Record<string, number>;
  monthly_expenses: Record<string, number>;
  category_totals: Record<string, number>;
}

export interface Anomaly {
  type: "category_spike" | "large_transaction";
  month?: string;
  date?: string;
  category: string;
  description?: string;
  amount: number;
  expected: number;
  severity: "high" | "medium";
  message: string;
}

export interface Forecast {
  next_month: string;
  total_expense_forecast: number;
  category_forecast: Record<string, number>;
  history: { months: string[]; expenses: number[] };
}

export interface HealthScore {
  score: number;
  savings_rate: number;
  income: number;
  expenses: number;
  anomalies_count: number;
  emergency_fund_months: number;
  active_emis: number;
  reference_month: string;
  rating: string;
}

export interface SavingsSuggestion {
  category: string;
  title: string;
  detail: string;
  monthly_savings: number;
}

export interface DashboardData {
  user_id: string;
  transactions: Transaction[];
  monthly_summary: MonthlySummary;
  anomalies: Anomaly[];
  forecast: Forecast;
  health_score: HealthScore;
  savings_suggestions: SavingsSuggestion[];
}

export interface Capabilities {
  llm_configured: boolean;
  llm_providers?: string[];
  rag_available: boolean;
  langgraph: boolean;
  whisper: boolean;
  gtts: boolean;
  voice?: {
    stt_providers: string[];
    tts_providers: string[];
  };
}

export interface ChatResponse {
  response: string;
  intent: string;
  retrieved_context: string[];
  llm_used: boolean;
  llm_error?: string | null;
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
  intent?: string | null;
  llm_used?: boolean | null;
  created_at?: string;
}

export interface DebateOpinion {
  agent: string;
  key: string;
  focus: string;
  stance: string;
  confidence: number;
  opinion: string;
  reasoning_summary: string;
  llm_used: boolean;
  error?: string | null;
}

export interface DebateDecision {
  agent: string;
  recommendation: string;
  overall_confidence: number;
  llm_used: boolean;
  error?: string | null;
}

export interface DebateResponse {
  question: string;
  opinions: DebateOpinion[];
  decision: DebateDecision;
  meta: { agent_count: number; langgraph: boolean; llm_configured: boolean };
}

export interface ScenarioFull {
  label: string;
  new_savings: number;
  emergency_fund_months: number;
  monthly_outflow: number;
  savings_rate: number;
  health_score: number;
  affordable: boolean;
}

export interface ScenarioEmi {
  label: string;
  emi_monthly: number;
  total_paid: number;
  interest_paid: number;
  emergency_fund_months: number;
  monthly_outflow: number;
  savings_rate: number;
  health_score: number;
}

export interface Simulation {
  purchase_amount: number;
  tenure_months: number;
  current_savings: number;
  monthly_expenses: number;
  pay_full: ScenarioFull;
  emi: ScenarioEmi;
  recommendation: "pay_full" | "emi";
}

export interface WhatIfResponse {
  simulation: Simulation;
  explanation: ChatResponse | null;
}

// ---------- Helpers ----------
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    // Our token is gone or no longer valid — drop it and let the app show login
    // rather than leaving every panel spinning on repeated 401s.
    if (res.status === 401) {
      clearSession();
      unauthorizedHandler?.();
    }
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      res.status
    );
  }
  return res.json() as Promise<T>;
}

/** Headers for an authenticated request, merged with any extras. */
function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : { ...extra };
}

/** GET an authenticated endpoint. */
async function authGet<T>(path: string): Promise<T> {
  return handle(await fetch(`${BASE}${path}`, { headers: authHeaders() }));
}

/** Send JSON to an authenticated endpoint. */
async function authSend<T>(
  path: string,
  method: "POST" | "DELETE" | "PUT",
  body?: unknown
): Promise<T> {
  return handle(
    await fetch(`${BASE}${path}`, {
      method,
      headers: authHeaders(
        body === undefined ? {} : { "Content-Type": "application/json" }
      ),
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  );
}

/** POST multipart form data to an authenticated endpoint. */
async function authPostForm<T>(path: string, form: FormData): Promise<T> {
  // No Content-Type here on purpose: the browser must set the multipart boundary.
  return handle(
    await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    })
  );
}

// ---------- Auth endpoints ----------
export async function register(input: {
  email: string;
  password: string;
  name?: string;
}): Promise<Session> {
  const session = await handle<Session>(
    await fetch(`${BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: input.email,
        password: input.password,
        name: input.name ?? "",
      }),
    })
  );
  return storeSession(session);
}

export async function login(input: {
  email: string;
  password: string;
}): Promise<Session> {
  const session = await handle<Session>(
    await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    })
  );
  return storeSession(session);
}

/** Validate the stored token against the server. Returns null if unusable. */
export async function fetchMe(): Promise<AuthUser | null> {
  if (!getToken()) return null;
  try {
    const { user } = await authGet<{ user: AuthUser }>("/auth/me");
    try {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    } catch {
      /* ignore */
    }
    return user;
  } catch {
    // handle() already cleared the session on a 401.
    return null;
  }
}

/** Log out locally. The token is stateless, so there is nothing to revoke. */
export function logout(): void {
  clearSession();
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<{ status: string }> {
  return authSend("/auth/password", "POST", {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export async function deleteAccount(): Promise<{ status: string }> {
  const out = await authSend<{ status: string }>("/auth/me", "DELETE");
  clearSession();
  return out;
}

// ---------- Endpoints ----------
export async function getHealth(): Promise<{ status: string }> {
  return handle(await fetch(`${BASE}/health`));
}

export async function getCapabilities(): Promise<Capabilities> {
  return handle(await fetch(`${BASE}/capabilities`));
}

export async function listSamples(): Promise<{ samples: string[] }> {
  return handle(await fetch(`${BASE}/samples`));
}

export async function uploadCsv(file: File): Promise<DashboardData> {
  const form = new FormData();
  form.append("file", file);
  return authPostForm("/upload", form);
}

export async function loadSample(name: string): Promise<DashboardData> {
  const form = new FormData();
  form.append("name", name);
  return authPostForm("/load-sample", form);
}

export async function getDashboard(): Promise<DashboardData> {
  return authGet("/dashboard");
}

// ---------- Finzo hands-free voice ----------

/** Structured failure from POST /voice/ask. */
export interface VoiceAskError {
  code:
    | "EMPTY_AUDIO"
    | "NO_SPEECH"
    | "STT_FAILED"
    | "STT_UNAVAILABLE"
    | "NO_DATA"
    | "LLM_FAILED"
    | "INTERNAL";
  message: string;
}

/**
 * One complete spoken turn.
 *
 * Conversational failures arrive with HTTP 200 and `ok: false` so the voice loop
 * can speak `speech` and keep listening instead of unwinding on a rejected fetch.
 */
export interface VoiceAskResult {
  ok: boolean;
  /** "answer" | "acknowledge" (bare wake word) | "stop" (barge-in phrase). */
  action?: "answer" | "acknowledge" | "stop";
  transcript: string;
  /** The self-contained query after follow-up resolution, for display. */
  resolved_query?: string;
  intent?: string;
  /** Written answer, markdown, for the transcript panel. */
  response: string;
  /** Speech-shaped answer, matching the audio. */
  speech: string;
  /** base64 mp3, or null when TTS was off or failed. */
  audio_b64?: string | null;
  tts_error?: string | null;
  llm_used?: boolean;
  confidence?: number;
  low_confidence?: boolean;
  /** "client_web_speech" when the fast path skipped server transcription. */
  stt_provider?: string;
  language?: string;
  duration_ms?: number;
  /** Time the server spent getting to a transcript. ~0 on the fast path. */
  stt_ms?: number;
  voice_session_id?: string;
  conversation_id?: string;
  context?: {
    current_topic: string | null;
    last_category: string | null;
    last_metric: string | null;
  };
  error?: VoiceAskError;
}

export interface VoiceWakeConfig {
  wake_word: string;
  acknowledgements: string[];
  timeout_options: number[];
  default_timeout: number;
}

/**
 * Send a spoken query and get the answer back in one round trip.
 *
 * Pass `transcript` when the browser's own recogniser already heard the query:
 * the server then skips Whisper entirely, which is about a second off the round
 * trip. `audio` is the fallback for when it did not, and at least one of the two
 * must be supplied.
 *
 * `signal` exists so barge-in can abandon an in-flight request: without it, a
 * cancelled answer would still arrive and start speaking.
 */
export async function voiceAsk(
  audio: Blob | null,
  opts: {
    speak?: boolean;
    timeoutSeconds?: number;
    signal?: AbortSignal;
    transcript?: string;
  } = {}
): Promise<VoiceAskResult> {
  const form = new FormData();
  if (audio) {
    // The extension is only a container hint; the server whitelists it and never
    // uses it as a path.
    form.append("file", audio, "query.webm");
  }
  const transcript = opts.transcript?.trim();
  if (transcript) form.append("client_transcript", transcript);
  form.append("speak", String(opts.speak ?? true));
  if (opts.timeoutSeconds !== undefined) {
    form.append("timeout_seconds", String(opts.timeoutSeconds));
  }
  return handle(
    await fetch(`${BASE}/voice/ask`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
      signal: opts.signal,
    })
  );
}

// ---------- Finzo streaming turn ----------

export interface VoiceStreamMeta {
  transcript: string;
  resolved_query: string;
  intent: string;
  stt_provider?: string;
  stt_ms?: number;
  voice_session_id?: string;
  conversation_id?: string;
}

export interface VoiceStreamDone {
  response: string;
  speech: string;
  intent: string;
  llm_used: boolean;
  retrieved_context?: unknown[];
  duration_ms?: number;
  stt_ms?: number;
}

export interface VoiceStreamHandlers {
  /** Transcript and intent, before any answer text. */
  onMeta?: (meta: VoiceStreamMeta) => void;
  /** Raw answer text, for the on-screen transcript. */
  onDelta?: (text: string) => void;
  /** One complete speech-ready sentence. Speak these in arrival order. */
  onSpeak?: (text: string) => void;
  /** Terminal: a stop command or a bare wake word. No answer follows. */
  onAction?: (action: {
    action: "stop" | "acknowledge";
    transcript: string;
    speech?: string;
  }) => void;
  onDone?: (done: VoiceStreamDone) => void;
  onError?: (error: VoiceAskError) => void;
}

/**
 * Stream a spoken turn over Server-Sent Events.
 *
 * Read with fetch rather than EventSource, which cannot send an Authorization
 * header or use POST. Resolves once the stream closes; an aborted request
 * resolves quietly rather than throwing, since barge-in is a normal outcome and
 * not a failure.
 */
export async function voiceAskStream(
  audio: Blob | null,
  opts: {
    transcript?: string;
    timeoutSeconds?: number;
    maxSpokenSentences?: number;
    signal?: AbortSignal;
  } & VoiceStreamHandlers = {}
): Promise<void> {
  const form = new FormData();
  if (audio) form.append("file", audio, "query.webm");
  const transcript = opts.transcript?.trim();
  if (transcript) form.append("client_transcript", transcript);
  if (opts.timeoutSeconds !== undefined) {
    form.append("timeout_seconds", String(opts.timeoutSeconds));
  }
  if (opts.maxSpokenSentences !== undefined) {
    form.append("max_spoken_sentences", String(opts.maxSpokenSentences));
  }

  const res = await fetch(`${BASE}/voice/ask/stream`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
    signal: opts.signal,
  });

  // Validation, auth and rate limiting still arrive as real status codes,
  // because they are decided before the stream opens.
  if (!res.ok || !res.body) {
    await handle(res); // throws ApiError, and clears the session on 401
    return;
  }

  const dispatch = (event: string, raw: string) => {
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      return; // ignore a malformed frame rather than killing the turn
    }
    switch (event) {
      case "meta":
        opts.onMeta?.(data as VoiceStreamMeta);
        break;
      case "delta":
        opts.onDelta?.((data as { text: string }).text);
        break;
      case "speak":
        opts.onSpeak?.((data as { text: string }).text);
        break;
      case "action":
        opts.onAction?.(data as Parameters<
          NonNullable<VoiceStreamHandlers["onAction"]>
        >[0]);
        break;
      case "done":
        opts.onDone?.(data as VoiceStreamDone);
        break;
      case "error":
        opts.onError?.(data as VoiceAskError);
        break;
    }
  };

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  // Frames are separated by a blank line and can be split across network chunks,
  // so hold the remainder until the separator actually arrives.
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let split: number;
      while ((split = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);

        let event = "message";
        const dataLines: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (dataLines.length) dispatch(event, dataLines.join("\n"));
      }
    }
  } catch (e) {
    // Barge-in aborts the reader mid-stream. That is the feature working.
    if (!(e instanceof DOMException && e.name === "AbortError")) throw e;
  } finally {
    reader.releaseLock?.();
  }
}

export async function getVoiceWakeConfig(): Promise<VoiceWakeConfig> {
  return handle(await fetch(`${BASE}/voice/wake-config`));
}

export async function endVoiceSession(): Promise<{ ended: boolean }> {
  return authSend("/voice/session", "DELETE");
}

// ---------- Statement history ----------
// `/dashboard` returns only the active snapshot, which each upload replaces.
// These read the append-only archive, so previous statements stay browsable.

/** One archived statement, without its (large) analysis payload. */
export interface StatementSummary {
  id: number;
  /** Null for statements archived before filenames were recorded. */
  filename: string | null;
  source_format: string | null;
  txn_count: number;
  /** Date of the earliest/latest transaction. Null when the file had none. */
  period_start: string | null;
  period_end: string | null;
  total_income: number;
  /** Positive magnitude, unlike the negative amounts on transactions. */
  total_expenses: number;
  score: number | null;
  created_at: string;
}

/** A summary plus the full analysis, as returned by `GET /statements/:id`. */
export interface ArchivedStatement extends StatementSummary {
  payload: DashboardData;
}

export async function listStatements(): Promise<{
  statements: StatementSummary[];
}> {
  return authGet("/statements");
}

export async function getStatement(id: number): Promise<ArchivedStatement> {
  return authGet(`/statements/${id}`);
}

/**
 * Make an archived statement the active one again and return its analysis.
 * The whole dashboard reflects it afterwards, not just the history page.
 */
export async function restoreStatement(id: number): Promise<DashboardData> {
  return authSend(`/statements/${id}/restore`, "POST");
}

export async function deleteStatement(
  id: number
): Promise<{ deleted: boolean }> {
  return authSend(`/statements/${id}`, "DELETE");
}

export async function sendChat(query: string): Promise<ChatResponse> {
  return authSend("/chat", "POST", { query });
}

export async function getChatHistory(): Promise<{
  history: ChatHistoryMessage[];
}> {
  return authGet("/chat/history");
}

// ---------- Phase 2: Multi-Agent Debate ----------
export interface AgentOpinion {
  agent: string;
  role: string;
  icon: string;
  stance: string;
  summary: string;
  key_points: string[];
  confidence: number;
  llm_used: boolean;
  latency_ms: number;
  retries: number;
  error?: string | null;
}

export interface DebateDecision {
  summary: string;
  consensus_confidence: number;
  priorities: { agent: string; icon: string; action: string; confidence: number }[];
  llm_used: boolean;
}

export interface DebateResult {
  opinions: AgentOpinion[];
  decision: DebateDecision;
  meta: {
    agent_count: number;
    langgraph: boolean;
    elapsed_ms: number;
    llm_used: boolean;
  };
}

export async function runDebate(question = ""): Promise<DebateResult> {
  return authSend("/debate", "POST", { question });
}

// ---------- Phase 3: Digital Financial Twin ----------
export interface TwinGoal {
  name: string;
  target_amount: number;
}

export interface ScenarioInput {
  name: string;
  years: number;
  monthly_income: number;
  monthly_expenses: number;
  current_savings: number;
  salary_growth: number;
  expense_growth: number;
  inflation: number;
  investment_return: number;
  current_age?: number | null;
  retirement_age?: number | null;
  goals: TwinGoal[];
}

export interface YearProjection {
  year: number;
  age?: number | null;
  annual_income: number;
  annual_expenses: number;
  annual_savings: number;
  invested: number;
  net_worth: number;
  real_net_worth: number;
  emergency_fund_months: number;
}

export interface RetirementEstimate {
  applicable: boolean;
  retirement_age?: number | null;
  years_to_retirement?: number | null;
  projected_corpus?: number | null;
  sustainable_annual_income?: number | null;
  sustainable_monthly_income?: number | null;
  real_sustainable_monthly_income?: number | null;
}

export interface GoalTimeline {
  name: string;
  target_amount: number;
  reached: boolean;
  year_reached?: number | null;
  years_to_reach?: number | null;
}

export interface TwinResult {
  scenario: ScenarioInput;
  projection: YearProjection[];
  final_net_worth: number;
  final_real_net_worth: number;
  total_contributed: number;
  total_growth: number;
  retirement: RetirementEstimate;
  goals: GoalTimeline[];
}

export interface SavedSimulation {
  id: number;
  name: string;
  params: Partial<ScenarioInput>;
  result: TwinResult;
  created_at: string;
}

export async function simulateTwin(
  scenario: Partial<ScenarioInput>,
  opts: { save?: boolean; name?: string } = {}
): Promise<{ result: TwinResult; saved_id: number | null }> {
  const { save = false, name } = opts;
  return authSend("/twin/simulate", "POST", { scenario, save, name });
}

export async function compareTwin(
  scenarios: Partial<ScenarioInput>[]
): Promise<{ results: TwinResult[] }> {
  return authSend("/twin/compare", "POST", { scenarios });
}

export async function getSimulations(): Promise<{
  scenarios: SavedSimulation[];
}> {
  return authGet("/twin/scenarios");
}

export async function deleteSimulation(
  id: number
): Promise<{ status: string; id: number }> {
  return authSend(`/twin/scenario/${id}`, "DELETE");
}

export async function clearChatHistory(): Promise<{
  status: string;
  removed: number;
}> {
  return authSend("/chat/history", "DELETE");
}

export async function runWhatIf(params: {
  purchase_amount: number;
  tenure_months: number;
  current_savings?: number | null;
  explain?: boolean;
}): Promise<WhatIfResponse> {
  const { explain = true, ...rest } = params;
  return authSend("/whatif", "POST", { explain, ...rest });
}

export interface TranscriptionResult {
  text: string;
  available: boolean;
  error?: string | null;
  bytes?: number;
  provider?: string;
  confidence?: number;
  language?: string | null;
  latency_ms?: number;
  low_confidence?: boolean;
}

export interface VoiceConfig {
  stt_providers: string[];
  tts_providers: string[];
  config: {
    stt_priority: string[];
    tts_priority: string[];
    enable_streaming: boolean;
    enable_memory: boolean;
    enable_rag: boolean;
    enable_offline_mode: boolean;
    enable_auto_retry: boolean;
    whisper_model: string;
    whisper_lang: string;
    stt_min_confidence: number;
    tts_lang: string;
  };
}

export async function getVoiceConfig(): Promise<VoiceConfig> {
  return handle(await fetch(`${BASE}/voice/config`));
}

// ---------- Phase 4: Explainable AI ----------
export interface ExplanationCard {
  subject: string;
  title: string;
  why: string;
  evidence: string[];
  confidence: number;
  retrieved_documents: string[];
  transactions_used: Transaction[];
  formula: string;
  model: string;
  reasoning_summary: string;
}

export async function explainSubject(
  subject: string
): Promise<ExplanationCard> {
  return authSend("/explain", "POST", { subject });
}

// ---------- Phase 9: Goal Planner ----------
export interface GoalType {
  id: string;
  label: string;
  icon: string;
  default_months: number;
  assumed_return: number;
}

export interface GoalPlan {
  id?: number;
  name?: string;
  goal_type: string;
  label: string;
  icon: string;
  target_amount: number;
  current_saved: number;
  remaining: number;
  annual_return: number;
  /** null when the goal cannot be reached within the projection horizon. */
  timeline_months: number | null;
  months_to_reach: number | null;
  target_date: string;
  required_monthly: number;
  monthly_contribution: number;
  monthly_surplus: number;
  shortfall_monthly: number;
  completion_probability: number;
  risk: string;
  reachable: boolean;
  on_track: boolean;
  projected_label: string;
  trajectory: { month: number; balance: number; target: number }[];
  progress_pct: number;
}

export interface GoalCreateInput {
  name: string;
  goal_type: string;
  target_amount: number;
  current_saved?: number;
  target_months?: number | null;
  monthly_contribution?: number | null;
  /** Assumed annual return as a fraction, e.g. 0.07 for 7%. */
  annual_return?: number;
}

export async function getGoalTypes(): Promise<{ types: GoalType[] }> {
  return handle(await fetch(`${BASE}/goals/types`));
}

export async function getGoals(): Promise<{
  goals: GoalPlan[];
  monthly_surplus: number;
}> {
  return authGet("/goals");
}

export async function createGoal(
  input: GoalCreateInput
): Promise<{ goal: GoalPlan }> {
  return authSend("/goals", "POST", input);
}

export async function deleteGoal(
  id: number
): Promise<{ status: string; id: number }> {
  return authSend(`/goals/${id}`, "DELETE");
}

// ---------- Phase 6: Retrieval Visualization ----------
export interface RagChunk {
  text: string;
  collection: string;
  distance: number;
  similarity: number;
  rank: number;
  point?: [number, number, number];
}

export interface RagTraceResult {
  available: boolean;
  reason?: string;
  query?: string;
  embedding?: { model: string; dimension: number; query_point: [number, number, number] };
  chunks: RagChunk[];
  top_k?: number;
  final_context?: string;
  stages?: string[];
}

export async function ragTrace(
  query: string,
  k = 4
): Promise<RagTraceResult> {
  return authSend("/rag/trace", "POST", { query, k });
}

// ---------- Phase 5: Long-Term Memory ----------
export interface MemoryItem {
  kind: string;
  mem_key: string;
  content: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type MemoryByKind = Record<string, MemoryItem[]>;

export async function getMemory(): Promise<{ memory: MemoryByKind }> {
  return authGet("/memory");
}

export async function addPreference(
  key: string,
  value: string
): Promise<{ kind: string; key: string; value: string }> {
  return authSend("/memory/preference", "POST", { key, value });
}

export async function addGoal(
  name: string,
  targetAmount: number | null,
  note = ""
): Promise<{ kind: string; name: string }> {
  return authSend("/memory/goal", "POST", {
    name,
    target_amount: targetAmount,
    note,
  });
}

export async function clearMemory(
  kind?: string
): Promise<{ status: string; removed: number }> {
  const q = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return authSend(`/memory${q}`, "DELETE");
}

export async function transcribeAudio(blob: Blob): Promise<TranscriptionResult> {
  const type = blob.type || "audio/webm";
  const ext = type.includes("mp4")
    ? "mp4"
    : type.includes("ogg")
      ? "ogg"
      : "webm";
  const form = new FormData();
  form.append("file", blob, `recording.${ext}`);
  return authPostForm("/voice/transcribe", form);
}

export async function speak(text: string): Promise<Blob> {
  const res = await fetch(`${BASE}/voice/speak`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    if (res.status === 401) {
      clearSession();
      unauthorizedHandler?.();
    }
    throw new ApiError("TTS unavailable", res.status);
  }
  return res.blob();
}

// The workflow-trace and model-routing visualisations were removed from the UI.
// Their backend endpoints (/workflow/graph, /workflow/trace, /router/status,
// /router/provider, /metrics/llm) still exist and remain useful for operations
// and debugging via /docs — they simply have no client here any more.
