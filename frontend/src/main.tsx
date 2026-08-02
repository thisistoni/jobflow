import React from "react";
import ReactDOM from "react-dom/client";
import {
  Activity,
  ArrowUpRight,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  Circle,
  Inbox,
  ListFilter,
  MessageSquareText,
  RefreshCw,
  Save,
  SearchCheck,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  ThumbsDown,
  ThumbsUp
} from "lucide-react";
import "./styles.css";

type Rating = "good" | "maybe" | "bad";
type View = "inbox" | "activity" | "preferences";
type Filter = "inbox" | "strong" | "maybe" | "low" | "reviewed" | "all";

type Feedback = {
  rating: Rating;
  reasons: string[];
  note: string;
  updated_at: string;
};

type JobListItem = {
  id: string;
  title: string;
  company: string;
  location?: string | null;
  score?: number | null;
  verdict?: string | null;
  confidence?: string | null;
  status: "inbox" | Rating;
  summary?: string | null;
  salary_display?: string | null;
  work_mode?: string | null;
  missing_info: string[];
  source_url: string;
  feedback?: Feedback | null;
};

type EvidenceItem = {
  origin?: string | null;
  text: string;
  profile_fact_ref?: string | null;
};

type JobDetail = JobListItem & {
  fit_evidence: Record<string, EvidenceItem[]>;
  source_evidence: Record<string, string[]>;
  hard_gate_reasons: string[];
  requirements: string[];
  responsibilities: string[];
  technologies: string[];
  salary_min_annual?: number | null;
  home_office_days?: number | null;
  language_environment?: string | null;
  imported_state?: string | null;
  first_seen_at: string;
  updated_at: string;
  reviewed_at?: string | null;
};

type Preferences = {
  target_locations: string[];
  work_modes: string[];
  min_home_office_days?: number | null;
  salary_currency: string;
  salary_target_min?: number | null;
  salary_target_max?: number | null;
  acceptable_salary_min?: number | null;
  role_families: string[];
  priorities: string[];
  hard_rules: string[];
  discovery_queries: string[];
  discovery_limit_per_query: number;
  language_preference?: string | null;
  application_language?: string | null;
  manual_submission_only: boolean;
  updated_at?: string | null;
};

type ActivityItem = {
  id: string;
  kind: string;
  title: string;
  body: string;
  job_id?: string | null;
  created_at: string;
};

const filters: Array<{ id: Filter; label: string }> = [
  { id: "inbox", label: "Inbox" },
  { id: "strong", label: "Strong" },
  { id: "maybe", label: "Maybe" },
  { id: "low", label: "Low fit" },
  { id: "reviewed", label: "Reviewed" },
  { id: "all", label: "All" }
];

const quickReasons: Record<Rating, string[]> = {
  good: ["Strong builder fit", "Good salary signal", "Right work mode", "Worth preparing"],
  maybe: ["Needs salary check", "Remote policy unclear", "Seniority uncertain", "Could be adjacent"],
  bad: ["Salary below target", "Role focus is off", "Too support-heavy", "Seniority feels wrong", "Location mismatch"]
};

function App() {
  const [jobs, setJobs] = React.useState<JobListItem[]>([]);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [selectedJob, setSelectedJob] = React.useState<JobDetail | null>(null);
  const [filter, setFilter] = React.useState<Filter>("inbox");
  const [view, setView] = React.useState<View>("inbox");
  const [activity, setActivity] = React.useState<ActivityItem[]>([]);
  const [preferences, setPreferences] = React.useState<Preferences | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = React.useState(false);

  const loadJobs = React.useCallback(async () => {
    setError(null);
    const data = await api<JobListItem[]>(`/api/jobs?filter=${filter}`);
    setJobs(data);
    setSelectedId((current) => current ?? data[0]?.id ?? null);
  }, [filter]);

  React.useEffect(() => {
    setLoading(true);
    loadJobs()
      .catch((reason: unknown) => setError(messageFrom(reason)))
      .finally(() => setLoading(false));
  }, [loadJobs]);

  React.useEffect(() => {
    if (!selectedId) {
      setSelectedJob(null);
      return;
    }
    api<JobDetail>(`/api/jobs/${selectedId}`)
      .then(setSelectedJob)
      .catch((reason: unknown) => setError(messageFrom(reason)));
  }, [selectedId]);

  React.useEffect(() => {
    if (view === "activity") {
      api<ActivityItem[]>("/api/activity").then(setActivity).catch((reason: unknown) => setError(messageFrom(reason)));
    }
    if (view === "preferences") {
      api<Preferences>("/api/preferences").then(setPreferences).catch((reason: unknown) => setError(messageFrom(reason)));
    }
  }, [view]);

  const inboxCount = jobs.filter((job) => job.status === "inbox").length;
  const strongCount = jobs.filter((job) => (job.score ?? 0) >= 70).length;

  async function submitFeedback(rating: Rating, reasons: string[], note: string) {
    if (!selectedJob) return;
    const feedback = await api<Feedback>(`/api/jobs/${selectedJob.id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, reasons, note })
    });
    setSelectedJob({ ...selectedJob, status: rating, feedback });
    await loadJobs();
    setActivity(await api<ActivityItem[]>("/api/activity"));
  }

  async function savePreferences(next: Preferences) {
    const updated = await api<Preferences>("/api/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next)
    });
    setPreferences(updated);
    setActivity(await api<ActivityItem[]>("/api/activity"));
  }

  return (
    <div className="app-shell">
      <aside className="rail" aria-label="Primary">
        <div className="brand-mark">JF</div>
        <NavButton icon={<Inbox />} label="Inbox" active={view === "inbox"} onClick={() => { setView("inbox"); setMobileDetailOpen(false); }} />
        <NavButton icon={<Activity />} label="Activity" active={view === "activity"} onClick={() => { setView("activity"); setMobileDetailOpen(false); }} />
        <NavButton icon={<SlidersHorizontal />} label="Me" active={view === "preferences"} onClick={() => { setView("preferences"); setMobileDetailOpen(false); }} />
      </aside>

      <main className={`workspace view-${view} ${mobileDetailOpen ? "mobile-detail-open" : ""}`}>
        <section className="inbox-pane">
          <header className="pulse-hero">
            <div>
              <p className="kicker">LOCAL JOBFLOW</p>
              <h1>{view === "inbox" ? "Review queue" : view === "activity" ? "While you were away" : "Train your search"}</h1>
            </div>
            <button className="round-action" type="button" onClick={() => void loadJobs()} aria-label="Refresh jobs">
              <RefreshCw size={18} />
            </button>
            <div className="hero-metrics">
              <div className="hero-metric">
                <strong>{jobs.length}</strong>
                <span>preserved jobs</span>
              </div>
              <div className="hero-metric orange">
                <strong>{strongCount}</strong>
                <span>strong signals</span>
              </div>
            </div>
            <PulseBars />
          </header>

          <nav className="filter-strip" aria-label="Job filters">
            {filters.map((item) => (
              <button key={item.id} className={filter === item.id ? "active" : ""} onClick={() => setFilter(item.id)} type="button">
                {item.label}
              </button>
            ))}
          </nav>

          {error ? <div className="state-card error">{error}</div> : null}
          {loading ? <div className="state-card">Loading preserved jobs...</div> : null}

          <div className="job-list">
            {jobs.map((job) => (
              <button
                type="button"
                className={`job-card ${selectedId === job.id ? "selected" : ""}`}
                key={job.id}
                onClick={() => {
                  setSelectedId(job.id);
                  setView("inbox");
                  setMobileDetailOpen(true);
                }}
              >
                <span className="initial">{initial(job.company)}</span>
                <span className="job-card-main">
                  <strong>{job.title}</strong>
                  <small>
                    {job.company} · {job.score ?? "--"}%
                  </small>
                  <span>{job.location || "Location unknown"}</span>
                </span>
                <ChevronRight size={18} />
              </button>
            ))}
            {!loading && jobs.length === 0 ? <div className="state-card">No jobs match this filter.</div> : null}
          </div>
        </section>

        <section className="detail-pane">
          {view === "inbox" ? (
            selectedJob ? (
              <JobReview
                job={selectedJob}
                onBack={() => setMobileDetailOpen(false)}
                onFeedback={(rating, reasons, note) => void submitFeedback(rating, reasons, note)}
              />
            ) : (
              <EmptyDetail />
            )
          ) : view === "activity" ? (
            <ActivityView items={activity} />
          ) : preferences ? (
            <PreferencesView preferences={preferences} onSave={(next) => void savePreferences(next)} />
          ) : (
            <div className="state-card">Loading preferences...</div>
          )}
        </section>
      </main>

      <div className="bottom-nav-dock">
        <nav className="bottom-nav" aria-label="Primary mobile">
          <NavButton icon={<Inbox />} label="Inbox" active={view === "inbox"} onClick={() => { setView("inbox"); setMobileDetailOpen(false); }} />
          <NavButton icon={<Activity />} label="Activity" active={view === "activity"} onClick={() => { setView("activity"); setMobileDetailOpen(false); }} />
          <NavButton icon={<SlidersHorizontal />} label="Me" active={view === "preferences"} onClick={() => { setView("preferences"); setMobileDetailOpen(false); }} />
        </nav>
      </div>
    </div>
  );
}

function JobReview({
  job,
  onBack,
  onFeedback
}: {
  job: JobDetail;
  onBack: () => void;
  onFeedback: (rating: Rating, reasons: string[], note: string) => void;
}) {
  const [rating, setRating] = React.useState<Rating>(job.feedback?.rating ?? "maybe");
  const [reasons, setReasons] = React.useState<string[]>(job.feedback?.reasons ?? []);
  const [note, setNote] = React.useState(job.feedback?.note ?? "");

  React.useEffect(() => {
    setRating(job.feedback?.rating ?? "maybe");
    setReasons(job.feedback?.reasons ?? []);
    setNote(job.feedback?.note ?? "");
  }, [job.id, job.feedback]);

  function toggleReason(reason: string) {
    setReasons((current) => (current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason]));
  }

  return (
    <article className="review-surface">
      <header className="review-header">
        <button className="mobile-back" type="button" onClick={onBack}>
          <ChevronRight size={17} /> Back to jobs
        </button>
        <div className="review-topline">
          <span className="initial orange-initial">{initial(job.company)}</span>
          <span>{job.company}</span>
          <a href={job.source_url} target="_blank" rel="noreferrer" aria-label="Open source job">
            <ArrowUpRight size={16} />
          </a>
        </div>
        <h2>{job.title}</h2>
        <div className="score-row">
          <strong>{job.score ?? "--"}</strong>
          <span>{job.verdict || "unscored"} · {job.confidence || "confidence unknown"}</span>
        </div>
      </header>

      <section className="insight-block">
        <span className="insight-number">01</span>
        <div>
          <h3>Why this surfaced</h3>
          <p>{job.summary || "The old scoring pass preserved this role for manual review."}</p>
        </div>
      </section>

      <div className="spec-grid">
        <Spec label="Salary" value={formatSalary(job)} />
        <Spec label="Place" value={job.location || "Unknown"} />
        <Spec label="Mode" value={formatWorkMode(job)} />
      </div>

      <EvidenceSection title="Fit evidence" evidence={job.fit_evidence} />
      <ListSection title="Missing information" icon={<ListFilter size={16} />} items={job.missing_info} empty="No obvious missing fields." />
      <ListSection title="Hard gate concerns" icon={<Circle size={16} />} items={job.hard_gate_reasons} empty="No hard gate concern preserved." />
      <ListSection title="Responsibilities" icon={<BriefcaseBusiness size={16} />} items={job.responsibilities} empty="No responsibilities extracted." />
      <ListSection title="Requirements" icon={<SearchCheck size={16} />} items={job.requirements} empty="No requirements extracted." />

      <section className="feedback-panel">
        <div className="panel-title">
          <MessageSquareText size={18} />
          <h3>Teach the next search</h3>
        </div>
        <div className="rating-grid">
          <button type="button" className={rating === "good" ? "selected good" : ""} onClick={() => setRating("good")}>
            <ThumbsUp size={17} /> Good
          </button>
          <button type="button" className={rating === "maybe" ? "selected maybe" : ""} onClick={() => setRating("maybe")}>
            <Sparkles size={17} /> Maybe
          </button>
          <button type="button" className={rating === "bad" ? "selected bad" : ""} onClick={() => setRating("bad")}>
            <ThumbsDown size={17} /> Bad
          </button>
        </div>
        <div className="reason-list">
          {quickReasons[rating].map((reason, index) => (
            <button key={reason} type="button" className={reasons.includes(reason) ? "chosen" : ""} onClick={() => toggleReason(reason)}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              {reason}
              {reasons.includes(reason) ? <Check size={16} /> : <Circle size={16} />}
            </button>
          ))}
        </div>
        <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add context for future ranking..." />
        <button className="primary-action" type="button" onClick={() => onFeedback(rating, reasons, note)}>
          Save feedback <ChevronRight size={18} />
        </button>
      </section>
    </article>
  );
}

function EvidenceSection({ title, evidence }: { title: string; evidence: Record<string, EvidenceItem[]> }) {
  const entries = Object.entries(evidence).filter(([, items]) => items.length > 0);
  return (
    <section className="content-section">
      <h3>{title}</h3>
      {entries.length === 0 ? <p className="muted">No preserved fit evidence.</p> : null}
      {entries.map(([key, items]) => (
        <div className="evidence-group" key={key}>
          <h4>{humanize(key)}</h4>
          {items.slice(0, 3).map((item, index) => (
            <p key={`${key}-${index}`}>
              <span>{item.origin || "source"}</span>
              {item.text}
            </p>
          ))}
        </div>
      ))}
    </section>
  );
}

function ListSection({ title, icon, items, empty }: { title: string; icon: React.ReactNode; items: string[]; empty: string }) {
  return (
    <section className="content-section compact">
      <h3>{icon}{title}</h3>
      {items.length ? (
        <ul>
          {items.slice(0, 6).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">{empty}</p>
      )}
    </section>
  );
}

function PreferencesView({ preferences, onSave }: { preferences: Preferences; onSave: (next: Preferences) => void }) {
  const [draft, setDraft] = React.useState(preferences);
  React.useEffect(() => setDraft(preferences), [preferences]);

  function setList(key: keyof Preferences, value: string) {
    setDraft({ ...draft, [key]: value.split("\n").map((item) => item.trim()).filter(Boolean) });
  }

  function toggleWorkMode(mode: string) {
    const nextModes = draft.work_modes.includes(mode)
      ? draft.work_modes.filter((item) => item !== mode)
      : [...draft.work_modes, mode];
    setDraft({ ...draft, work_modes: nextModes });
  }

  return (
    <article className="preferences-surface">
      <header>
        <p className="kicker">SEARCH DNA</p>
        <h2>Train your search</h2>
        <p>Hard rules filter. Soft preferences re-rank. Feedback stays local in this self-hosted slice.</p>
      </header>

      <div className="salary-box">
        <label>
          Target minimum
          <input
            type="number"
            value={draft.salary_target_min ?? ""}
            onChange={(event) => setDraft({ ...draft, salary_target_min: numberOrNull(event.target.value) })}
          />
        </label>
        <label>
          Target maximum
          <input
            type="number"
            value={draft.salary_target_max ?? ""}
            onChange={(event) => setDraft({ ...draft, salary_target_max: numberOrNull(event.target.value) })}
          />
        </label>
        <span>{draft.salary_currency} gross / year</span>
      </div>

      <section className="content-section">
        <h3>Work setup</h3>
        <div className="rating-grid">
          {["remote", "hybrid", "onsite"].map((mode) => (
            <button key={mode} type="button" className={draft.work_modes.includes(mode) ? "selected" : ""} onClick={() => toggleWorkMode(mode)}>
              {humanize(mode)}
            </button>
          ))}
        </div>
        <label className="field-row">
          Minimum home-office days
          <input
            type="number"
            min={0}
            max={7}
            value={draft.min_home_office_days ?? ""}
            onChange={(event) => setDraft({ ...draft, min_home_office_days: numberOrNull(event.target.value) })}
          />
        </label>
      </section>

      <EditorArea label="Target locations" value={draft.target_locations.join("\n")} onChange={(value) => setList("target_locations", value)} />
      <EditorArea label="Role families" value={draft.role_families.join("\n")} onChange={(value) => setList("role_families", value)} />
      <EditorArea label="Prioritize" value={draft.priorities.join("\n")} onChange={(value) => setList("priorities", value)} />
      <EditorArea label="Hard rules" value={draft.hard_rules.join("\n")} onChange={(value) => setList("hard_rules", value)} />

      <section className="content-section compact">
        <h3>Discovery</h3>
        <label className="field-row">
          Results per query
          <input
            type="number"
            min={1}
            max={20}
            value={draft.discovery_limit_per_query}
            onChange={(event) => setDraft({ ...draft, discovery_limit_per_query: boundedNumber(event.target.value, 1, 20, 5) })}
          />
        </label>
      </section>
      <EditorArea
        label="Discovery queries"
        value={draft.discovery_queries.join("\n")}
        onChange={(value) => setList("discovery_queries", value)}
      />

      <section className="content-section compact">
        <h3>Manual control</h3>
        <label className="toggle-row">
          External applications stay manual
          <input
            type="checkbox"
            checked={draft.manual_submission_only}
            onChange={(event) => setDraft({ ...draft, manual_submission_only: event.target.checked })}
          />
        </label>
      </section>

      <button className="primary-action" type="button" onClick={() => onSave(draft)}>
        <Save size={18} /> Save preferences
      </button>
    </article>
  );
}

function ActivityView({ items }: { items: ActivityItem[] }) {
  return (
    <article className="activity-surface">
      <header>
        <p className="kicker">ACTIVITY</p>
        <h2>Local log</h2>
      </header>
      <div className="activity-list">
        {items.map((item) => (
          <div className="activity-item" key={item.id}>
            <span className="activity-dot"><Activity size={15} /></span>
            <div>
              <time>{formatDate(item.created_at)}</time>
              <strong>{item.title}</strong>
              <p>{item.body}</p>
            </div>
          </div>
        ))}
      </div>
      {items.length === 0 ? <div className="state-card">No activity yet.</div> : null}
    </article>
  );
}

function EditorArea({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="editor-area">
      <span>{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="spec">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function NavButton({ icon, label, active, onClick }: { icon: React.ReactNode; label: string; active: boolean; onClick: () => void }) {
  return (
    <button className={active ? "nav-button active" : "nav-button"} type="button" onClick={onClick}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function PulseBars() {
  return (
    <div className="pulse-bars" aria-hidden="true">
      {[3, 5, 8, 4, 7, 6, 8, 3, 5, 8, 6, 4, 7, 8, 5, 3].map((height, index) => (
        <span key={`${height}-${index}`} style={{ height }} className={height > 6 ? "hot" : ""} />
      ))}
    </div>
  );
}

function EmptyDetail() {
  return <div className="state-card">Select a preserved job to review.</div>;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

function initial(value: string) {
  return value.trim().charAt(0).toUpperCase() || "J";
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatWorkMode(job: JobDetail) {
  const days = job.home_office_days == null ? "" : ` · ${job.home_office_days} home days`;
  return `${job.work_mode || "Unknown"}${days}`;
}

function formatSalary(job: JobDetail) {
  if (job.salary_min_annual != null) {
    return `${new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(job.salary_min_annual)}+ gross / year`;
  }
  return job.salary_display || "Unknown";
}

function numberOrNull(value: string) {
  if (value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function boundedNumber(value: string, min: number, max: number, fallback: number) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

function messageFrom(reason: unknown) {
  return reason instanceof Error ? reason.message : "Unknown error";
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
