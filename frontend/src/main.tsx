import React from "react";
import ReactDOM from "react-dom/client";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Bell,
  BrainCircuit,
  BriefcaseBusiness,
  Check,
  Circle,
  Columns3,
  Ellipsis,
  Inbox,
  ListFilter,
  LockKeyhole,
  LogOut,
  Save,
  ScanSearch,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Target,
  UserRound,
  X
} from "lucide-react";
import "./styles.css";

type Rating = "good" | "maybe" | "bad";
type View = "inbox" | "activity" | "preferences";
type Filter = "inbox" | "strong" | "maybe" | "low" | "reviewed" | "all";

type AuthStatus = {
  auth_required: boolean;
  authenticated: boolean;
  expires_at?: number | null;
};

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
  { id: "inbox", label: "For you" },
  { id: "maybe", label: "Review" },
  { id: "reviewed", label: "Saved" }
];

const quickReasons: Record<Rating, string[]> = {
  good: ["Strong builder fit", "Good salary signal", "Right work mode", "Worth preparing"],
  maybe: ["Needs salary check", "Remote policy unclear", "Seniority uncertain", "Could be adjacent"],
  bad: ["Salary below target", "Remote policy unclear", "Company does not excite me", "Seniority feels wrong", "Role focus is off"]
};

function App() {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);
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
  const [declineOpen, setDeclineOpen] = React.useState(false);
  const isUnlocked = auth != null && (!auth.auth_required || auth.authenticated);

  const handleAuthExpired = React.useCallback((reason: unknown) => {
    if (reason instanceof AuthExpiredError) {
      setAuth({ auth_required: true, authenticated: false });
      setJobs([]);
      setSelectedId(null);
      setSelectedJob(null);
      setActivity([]);
      setPreferences(null);
      setError(null);
      setDeclineOpen(false);
      return true;
    }
    return false;
  }, []);

  React.useEffect(() => {
    api<AuthStatus>("/api/auth/status")
      .then(setAuth)
      .catch((reason: unknown) => {
        const message = messageFrom(reason);
        if (message.includes("404") || message.includes("Not Found")) {
          setAuth({ auth_required: false, authenticated: true });
          return;
        }
        setError(message);
      })
      .finally(() => setLoading(false));
  }, []);

  const loadJobs = React.useCallback(async () => {
    setError(null);
    const data = await api<JobListItem[]>(`/api/jobs?filter=${filter}`);
    setJobs(data);
    setSelectedId((current) => current ?? data[0]?.id ?? null);
  }, [filter]);

  React.useEffect(() => {
    if (!isUnlocked) return;
    setLoading(true);
    loadJobs()
      .catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      })
      .finally(() => setLoading(false));
  }, [handleAuthExpired, isUnlocked, loadJobs]);

  React.useEffect(() => {
    if (!isUnlocked) return;
    if (!selectedId) {
      setSelectedJob(null);
      return;
    }
    api<JobDetail>(`/api/jobs/${selectedId}`)
      .then(setSelectedJob)
      .catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
  }, [handleAuthExpired, isUnlocked, selectedId]);

  React.useEffect(() => {
    if (!isUnlocked) return;
    if (view === "activity") {
      api<ActivityItem[]>("/api/activity").then(setActivity).catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
    }
    if (view === "preferences") {
      api<Preferences>("/api/preferences").then(setPreferences).catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
    }
  }, [handleAuthExpired, isUnlocked, view]);

  const inboxCount = jobs.filter((job) => job.status === "inbox").length;
  const strongCount = jobs.filter((job) => (job.score ?? 0) >= 70).length;

  async function submitFeedback(rating: Rating, reasons: string[], note: string) {
    if (!selectedJob) return;
    try {
      const feedback = await api<Feedback>(`/api/jobs/${selectedJob.id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, reasons, note })
      });
      setSelectedJob({ ...selectedJob, status: rating, feedback });
      setDeclineOpen(false);
      await loadJobs();
      setActivity(await api<ActivityItem[]>("/api/activity"));
    } catch (reason) {
      if (!handleAuthExpired(reason)) setError(messageFrom(reason));
    }
  }

  async function savePreferences(next: Preferences) {
    try {
      const updated = await api<Preferences>("/api/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next)
      });
      setPreferences(updated);
      setActivity(await api<ActivityItem[]>("/api/activity"));
    } catch (reason) {
      if (!handleAuthExpired(reason)) setError(messageFrom(reason));
    }
  }

  async function submitLogin(username: string, password: string) {
    const status = await api<AuthStatus>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    setAuth(status);
    setError(null);
  }

  async function logout() {
    try {
      await api<AuthStatus>("/api/auth/logout", { method: "POST" });
    } finally {
      setAuth({ auth_required: true, authenticated: false });
      setJobs([]);
      setSelectedId(null);
      setSelectedJob(null);
      setActivity([]);
      setPreferences(null);
      setMobileDetailOpen(false);
      setDeclineOpen(false);
    }
  }

  function navigate(next: View) {
    setView(next);
    setMobileDetailOpen(false);
    setDeclineOpen(false);
  }

  if (auth == null) {
    return <LoginScreen loading={loading} error={error} onLogin={submitLogin} />;
  }

  if (auth.auth_required && !auth.authenticated) {
    return <LoginScreen error={error} onLogin={submitLogin} />;
  }

  const detail = declineOpen && selectedJob ? (
    <DeclineFeedback
      job={selectedJob}
      onClose={() => setDeclineOpen(false)}
      onFeedback={(reasons, note) => void submitFeedback("bad", reasons, note)}
    />
  ) : view === "inbox" ? (
    selectedJob ? (
      <JobReview
        job={selectedJob}
        onBack={() => setMobileDetailOpen(false)}
        onDecline={() => setDeclineOpen(true)}
        onFeedback={(rating, reasons, note) => void submitFeedback(rating, reasons, note)}
      />
    ) : (
      <EmptyDetail />
    )
  ) : view === "activity" ? (
    <ActivityView items={activity} jobs={jobs} />
  ) : preferences ? (
    <PreferencesView preferences={preferences} onSave={(next) => void savePreferences(next)} />
  ) : (
    <div className="state-card">Loading preferences...</div>
  );

  return (
    <div className="app-shell">
      <aside className="desktop-rail" aria-label="Primary">
        <div className="brand-mark">JF</div>
        <NavButton icon={<Inbox />} label="Inbox" active={view === "inbox" && !declineOpen} onClick={() => navigate("inbox")} />
        <NavButton icon={<Columns3 />} label="Pipeline" active={false} onClick={() => navigate("inbox")} />
        <NavButton icon={<Bell />} label="Activity" active={view === "activity"} onClick={() => navigate("activity")} />
        <NavButton icon={<UserRound />} label="Me" active={view === "preferences"} onClick={() => navigate("preferences")} />
        {auth.auth_required ? (
          <button className="rail-logout" type="button" onClick={() => void logout()} aria-label="Log out">
            <LogOut size={18} />
          </button>
        ) : null}
      </aside>

      <main className={`workspace view-${view} ${mobileDetailOpen || declineOpen ? "mobile-detail-open" : ""}`}>
        <section className="phone-surface inbox-pane" aria-label="Pulse Inbox">
          <InboxScreen
            jobs={jobs}
            selectedId={selectedId}
            filter={filter}
            loading={loading}
            error={error}
            counts={{ inboxCount, strongCount }}
            onRefresh={() => void loadJobs()}
            onFilter={setFilter}
            onSelect={(id) => {
              setSelectedId(id);
              setView("inbox");
              setMobileDetailOpen(true);
              setDeclineOpen(false);
            }}
            activeView={view}
            onNavigate={navigate}
          />
        </section>

        <section className="phone-surface detail-pane" aria-label="Current JobFlow state">
          {detail}
        </section>
      </main>

      {mobileDetailOpen || declineOpen ? null : <MobileDock activeView={view} onNavigate={navigate} />}
    </div>
  );
}

function InboxScreen({
  jobs,
  selectedId,
  filter,
  loading,
  error,
  counts,
  onRefresh,
  onFilter,
  onSelect,
  activeView,
  onNavigate
}: {
  jobs: JobListItem[];
  selectedId: string | null;
  filter: Filter;
  loading: boolean;
  error: string | null;
  counts: { inboxCount: number; strongCount: number };
  onRefresh: () => void;
  onFilter: (filter: Filter) => void;
  onSelect: (id: string) => void;
  activeView: View;
  onNavigate: (view: View) => void;
}) {
  const featured = jobs[0] ?? null;
  const rest = featured ? jobs.slice(1) : jobs;

  return (
    <>
      <header className="pulse-hero">
        <div className="hero-top">
          <div>
            <p className="micro orange-text">LOCAL JOBFLOW</p>
            <h1>Pulse Inbox</h1>
          </div>
          <button className="round-action" type="button" onClick={onRefresh} aria-label="Refresh jobs">
            <ScanSearch size={20} />
          </button>
        </div>
        <div className="daily-match">
          <strong>{jobs.length.toString().padStart(2, "0")}</strong>
          <div>
            <h2>new roles found</h2>
            <p>{counts.strongCount} look unusually good for you</p>
          </div>
        </div>
        <PulseBars />
      </header>

      <div className="screen-body inbox-body">
        <nav className="filter-strip" aria-label="Job filters">
          {filters.map((item) => (
            <button key={item.id} className={filter === item.id ? "active" : ""} onClick={() => onFilter(item.id)} type="button">
              {item.label.toUpperCase()} · {filterCount(item.id, jobs, counts)}
            </button>
          ))}
        </nav>

        {error ? <div className="state-card error">{error}</div> : null}
        {loading ? <div className="state-card">Loading preserved jobs...</div> : null}

        {featured ? (
          <button type="button" className={`featured-job ${selectedId === featured.id ? "selected" : ""}`} onClick={() => onSelect(featured.id)}>
            <div className="featured-top">
              <div className="company-line">
                <span className="company-mark dark">{initial(featured.company)}</span>
                <span>
                  <b>{featured.company.toUpperCase()}</b>
                  <small>{compactLocation(featured)}</small>
                </span>
              </div>
              <span className="match-pill">{featured.score ?? "--"}% MATCH</span>
            </div>
            <strong className="featured-title">{featured.title}</strong>
            <div className="tag-row">
              <span>{shortSalary(featured)}</span>
              <span>{(featured.work_mode || "Role").toUpperCase()}</span>
              <span>{formatAge(featured.feedback?.updated_at)}</span>
            </div>
            <div className="featured-why">
              <Target size={15} />
              <span>{featured.summary || `${featured.missing_info.length ? "Some details need review" : "Profile signals are ready to review"}`}</span>
            </div>
          </button>
        ) : null}

        <div className="more-matches">
          {rest.map((job, index) => (
            <button type="button" className={`match-row ${selectedId === job.id ? "selected" : ""}`} key={job.id} onClick={() => onSelect(job.id)}>
              <span className={`company-mark tint-${index % 4}`}>{initial(job.company)}</span>
              <span className="match-copy">
                <strong>{job.title}</strong>
                <small>{job.company.toUpperCase()} · {job.score ?? "--"}%</small>
              </span>
              <ArrowUpRight size={17} />
            </button>
          ))}
          {!loading && jobs.length === 0 ? <div className="state-card">No jobs match this filter.</div> : null}
        </div>
      </div>

      <BottomNav activeView={activeView} onNavigate={onNavigate} />
    </>
  );
}

function JobReview({
  job,
  onBack,
  onDecline,
  onFeedback
}: {
  job: JobDetail;
  onBack: () => void;
  onDecline: () => void;
  onFeedback: (rating: Rating, reasons: string[], note: string) => void;
}) {
  return (
    <article className="review-screen">
      <header className="review-hero">
        <div className="detail-nav">
          <button className="icon-button outlined mobile-back" type="button" onClick={onBack} aria-label="Back to jobs">
            <ArrowLeft size={18} />
          </button>
          <span className="micro orange-text">MATCH REVIEW</span>
          <a className="icon-button outlined" href={job.source_url} target="_blank" rel="noreferrer" aria-label="Open source job">
            <Ellipsis size={18} />
          </a>
        </div>
        <div className="company-line">
          <span className="company-mark orange">{initial(job.company)}</span>
          <span>
            <b>{job.company.toUpperCase()} · {compactLocation(job).toUpperCase()}</b>
          </span>
        </div>
        <h1>{job.title}</h1>
        <div className="fit-line">
          <strong>{job.score ?? "--"}</strong>
          <span>
            <b>MATCH SCORE</b>
            <small>{job.verdict || "Preserved for review"} · {job.confidence || "confidence unknown"}</small>
          </span>
        </div>
      </header>

      <div className="screen-body review-body">
        <section className="insight-row">
          <span>01</span>
          <div>
            <h2>Why your agent chose this</h2>
            <p>{job.summary || "This role was preserved by the scoring pass for a closer manual review."}</p>
          </div>
        </section>

        <section className="pack">
          <div className="pack-header">
            <b>APPLICATION PACK</b>
            <span>READY</span>
          </div>
          <PackRow number="01" title="Fit brief" meta={job.summary ? "Summary generated" : "Needs summary review"} />
          <PackRow number="02" title="Evidence map" meta={`${evidenceCount(job.fit_evidence)} fit signals`} />
          <PackRow number="03" title="Manual checklist" meta={`${job.missing_info.length} missing fields`} />
        </section>

        <div className="spec-strip">
          <Spec label="Salary" value={formatSalary(job)} />
          <Spec label="Type" value={(job.work_mode || "Unknown").toUpperCase()} />
          <Spec label="Place" value={compactLocation(job).toUpperCase()} />
        </div>

        <EvidenceSection title="Fit evidence" evidence={job.fit_evidence} />
        <ListSection title="Missing information" icon={<ListFilter size={15} />} items={job.missing_info} empty="No obvious missing fields." />
        <ListSection title="Hard gate concerns" icon={<Circle size={15} />} items={job.hard_gate_reasons} empty="No hard gate concern preserved." />
        <ListSection title="Responsibilities" icon={<BriefcaseBusiness size={15} />} items={job.responsibilities} empty="No responsibilities extracted." />
        <ListSection title="Requirements" icon={<Sparkles size={15} />} items={job.requirements} empty="No requirements extracted." />
      </div>

      <footer className="review-actions">
        <button className="reject-action" type="button" onClick={onDecline} aria-label="Decline role">
          <X size={19} />
        </button>
        <button className="revise-action" type="button" onClick={() => onFeedback("maybe", quickReasons.maybe.slice(0, 1), "")}>
          REVISE
        </button>
        <button className="approve-action" type="button" onClick={() => onFeedback("good", quickReasons.good.slice(0, 2), "")}>
          APPROVE PACK <ArrowRight size={16} />
        </button>
      </footer>
    </article>
  );
}

function DeclineFeedback({
  job,
  onClose,
  onFeedback
}: {
  job: JobDetail;
  onClose: () => void;
  onFeedback: (reasons: string[], note: string) => void;
}) {
  const initialReasons = job.feedback?.rating === "bad" ? job.feedback.reasons : [];
  const [reasons, setReasons] = React.useState<string[]>(initialReasons);
  const [note, setNote] = React.useState(job.feedback?.rating === "bad" ? job.feedback.note : "");

  function toggleReason(reason: string) {
    setReasons((current) => (current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason]));
  }

  return (
    <article className="decline-screen">
      <div className="decline-body">
        <div className="decline-top">
          <button className="icon-button black" type="button" onClick={onClose} aria-label="Close feedback">
            <X size={18} />
          </button>
          <span className="micro">TEACH THE AGENT</span>
        </div>
        <h1>Pass on this.<br />Improve the next.</h1>
        <p className="decline-lead">Every no becomes a sharper filter for tomorrow's search.</p>

        <div className="decline-ticket">
          <span className="company-mark dark">{initial(job.company)}</span>
          <span>
            <b>{job.title}</b>
            <small>{job.company.toUpperCase()} · {job.score ?? "--"}% MATCH</small>
          </span>
          <ArrowUpRight size={17} />
        </div>

        <section className="decline-reasons">
          <div className="section-head">
            <h2>What missed?</h2>
            <span>{reasons.length} SELECTED</span>
          </div>
          {quickReasons.bad.map((reason, index) => (
            <button type="button" key={reason} className={reasons.includes(reason) ? "chosen" : ""} onClick={() => toggleReason(reason)}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <b>{reason}</b>
              {reasons.includes(reason) ? <Check size={14} /> : <Circle size={18} />}
            </button>
          ))}
        </section>

        <label className="note-field">
          <span>ADD CONTEXT · OPTIONAL</span>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="I only want fully remote roles above EUR 90k..." />
        </label>

        <div className="learning-line">
          <BrainCircuit size={18} />
          <span>These signals will re-rank future matches.</span>
        </div>
      </div>
      <footer className="decline-submit">
        <button type="button" onClick={() => onFeedback(reasons, note)}>
          DECLINE + UPDATE AGENT <ArrowRight size={16} />
        </button>
      </footer>
    </article>
  );
}

function LoginScreen({
  loading = false,
  error,
  onLogin
}: {
  loading?: boolean;
  error: string | null;
  onLogin: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [loginError, setLoginError] = React.useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setLoginError(null);
    try {
      await onLogin(username, password);
    } catch (reason) {
      setLoginError(messageFrom(reason));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="phone-surface login-screen" aria-label="JobFlow login">
        <div className="login-hero">
          <div className="login-topline">
            <span className="micro orange-text">JOBFLOW</span>
            <span className="micro">01 / 01</span>
          </div>
          <h1>Start with what you've already built.</h1>
          <p>Your agent keeps the local job search loop private, persistent, and ready to review.</p>
          <PulseBars />
        </div>
        <form className="login-form" onSubmit={(event) => void submit(event)}>
          <div className="upload-tile">
            <LockKeyhole size={22} />
            <b>Unlock JobFlow</b>
            <span>Use the credentials configured for this self-hosted app.</span>
          </div>
          <label>
            <span>USERNAME</span>
            <input
              autoComplete="username"
              autoFocus
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              disabled={loading || submitting}
            />
          </label>
          <label>
            <span>PASSWORD</span>
            <input
              autoComplete="current-password"
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={loading || submitting}
            />
          </label>
          {error || loginError ? <div className="state-card error">{loginError ?? error}</div> : null}
          <button className="approve-action login-action" type="submit" disabled={loading || submitting}>
            {loading ? "CHECKING SESSION" : submitting ? "SIGNING IN" : "SIGN IN"} <ArrowRight size={16} />
          </button>
        </form>
      </section>
    </main>
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

  function toggleRule(rule: string) {
    const nextRules = draft.hard_rules.includes(rule)
      ? draft.hard_rules.filter((item) => item !== rule)
      : [...draft.hard_rules, rule];
    setDraft({ ...draft, hard_rules: nextRules });
  }

  const salaryValue = draft.salary_target_min ?? draft.acceptable_salary_min ?? 0;
  const visibleRules = preferredRules(draft);

  return (
    <article className="preferences-screen">
      <header className="pref-hero">
        <div className="hero-top">
          <div>
            <p className="micro orange-text">SEARCH DNA</p>
            <h1>Train your agent</h1>
          </div>
          <span className="round-action">
            <BrainCircuit size={20} />
          </span>
        </div>
        <p>Hard rules filter. Soft preferences re-rank. Your feedback keeps both evolving.</p>
        <div className="quality-row">
          <span><i style={{ width: `${Math.min(100, 62 + draft.hard_rules.length * 6)}%` }} /></span>
          <b>{Math.min(98, 62 + draft.hard_rules.length * 6)}% SHARP</b>
        </div>
      </header>

      <div className="screen-body preferences-body">
        <section className="salary-card">
          <div>
            <span className="micro">MINIMUM SALARY</span>
            <strong>{formatCurrencyValue(salaryValue, draft.salary_currency)}</strong>
          </div>
          <span className="micro">GROSS / YEAR</span>
          <div className="salary-track">
            <i style={{ width: `${salaryPercent(salaryValue)}%` }} />
            <b style={{ left: `${salaryPercent(salaryValue)}%` }} />
          </div>
          <div className="salary-inputs">
            <input
              aria-label="Target minimum salary"
              type="number"
              value={draft.salary_target_min ?? ""}
              onChange={(event) => setDraft({ ...draft, salary_target_min: numberOrNull(event.target.value) })}
            />
            <input
              aria-label="Target maximum salary"
              type="number"
              value={draft.salary_target_max ?? ""}
              onChange={(event) => setDraft({ ...draft, salary_target_max: numberOrNull(event.target.value) })}
            />
          </div>
        </section>

        <section className="pref-section">
          <h2>Work setup</h2>
          <div className="mode-grid">
            {["remote", "hybrid", "onsite"].map((mode) => (
              <button key={mode} type="button" className={draft.work_modes.includes(mode) ? "selected" : ""} onClick={() => toggleWorkMode(mode)}>
                {draft.work_modes.includes(mode) ? <Check size={12} /> : null}
                {mode === "onsite" ? "ON-SITE" : mode.toUpperCase()}
              </button>
            ))}
          </div>
          <label className="inline-field">
            <span>HOME-OFFICE DAYS</span>
            <input
              type="number"
              min={0}
              max={7}
              value={draft.min_home_office_days ?? ""}
              onChange={(event) => setDraft({ ...draft, min_home_office_days: numberOrNull(event.target.value) })}
            />
          </label>
        </section>

        <section className="pref-section rules-section">
          <h2>Hard rules</h2>
          {visibleRules.map((rule) => (
            <button className="rule-row" type="button" key={rule} onClick={() => toggleRule(rule)}>
              <span>
                <b>{rule}</b>
                <small>{ruleMeta(rule)}</small>
              </span>
              <i className={draft.hard_rules.includes(rule) ? "on" : ""}><b /></i>
            </button>
          ))}
        </section>

        <EditorArea label="Target locations" value={draft.target_locations.join("\n")} onChange={(value) => setList("target_locations", value)} />
        <EditorArea label="Role families" value={draft.role_families.join("\n")} onChange={(value) => setList("role_families", value)} />
        <EditorArea label="Discovery queries" value={draft.discovery_queries.join("\n")} onChange={(value) => setList("discovery_queries", value)} />

        <section className="pref-section">
          <div className="section-head">
            <h2>Prioritize</h2>
            <span>EDIT</span>
          </div>
          <div className="interest-chips">
            {draft.priorities.slice(0, 5).map((priority) => (
              <span key={priority}>{priority.toUpperCase()}</span>
            ))}
          </div>
          <EditorArea label="Priorities" value={draft.priorities.join("\n")} onChange={(value) => setList("priorities", value)} compact />
        </section>

        <section className="pref-section">
          <h2>Discovery</h2>
          <label className="inline-field">
            <span>RESULTS PER QUERY</span>
            <input
              type="number"
              min={1}
              max={20}
              value={draft.discovery_limit_per_query}
              onChange={(event) => setDraft({ ...draft, discovery_limit_per_query: boundedNumber(event.target.value, 1, 20, 5) })}
            />
          </label>
          <label className="rule-row checkbox-row">
            <span>
              <b>External applications stay manual</b>
              <small>Approval required</small>
            </span>
            <input
              type="checkbox"
              checked={draft.manual_submission_only}
              onChange={(event) => setDraft({ ...draft, manual_submission_only: event.target.checked })}
            />
          </label>
        </section>

        <div className="learning-note">
          <span className="company-mark dark"><BrainCircuit size={14} /></span>
          <b>Last learned from local feedback</b>
        </div>
      </div>

      <footer className="sticky-submit">
        <button type="button" onClick={() => onSave(draft)}>
          <Save size={16} /> SAVE PREFERENCES
        </button>
      </footer>
    </article>
  );
}

function ActivityView({ items, jobs }: { items: ActivityItem[]; jobs: JobListItem[] }) {
  const packCount = jobs.filter((job) => job.status !== "bad").length;
  const appliedCount = jobs.filter((job) => job.status === "good").length;
  return (
    <article className="activity-screen">
      <header className="activity-hero">
        <div className="hero-top">
          <div>
            <p className="micro">AGENT LOG</p>
            <h1>While you were away</h1>
          </div>
          <span className="round-action black">
            <Settings2 size={18} />
          </span>
        </div>
        <div className="activity-stats">
          <Stat label="FOUND" value={String(jobs.length).padStart(2, "0")} dark />
          <Stat label="PACKS" value={String(packCount).padStart(2, "0")} />
          <Stat label="APPLIED" value={String(appliedCount).padStart(2, "0")} />
        </div>
      </header>

      <div className="screen-body activity-body">
        <div className="section-head">
          <h2>Today</h2>
          <span>{new Intl.DateTimeFormat(undefined, { weekday: "short", day: "2-digit", month: "short" }).format(new Date()).toUpperCase()}</span>
        </div>
        <div className="activity-list">
          {items.map((item, index) => (
            <div className="activity-item" key={item.id}>
              <span className="activity-icon"><ActivityIcon kind={item.kind} /></span>
              <div>
                <div className="activity-item-top">
                  <strong>{item.title}</strong>
                  <time>{formatTime(item.created_at)}</time>
                </div>
                <p>{item.body}</p>
              </div>
              <ArrowUpRight size={14} />
              {index === 3 ? <div className="day-break">Yesterday</div> : null}
            </div>
          ))}
        </div>
        {items.length === 0 ? <div className="state-card">No activity yet.</div> : null}
      </div>
      <BottomNav activeView="activity" onNavigate={() => undefined} />
    </article>
  );
}

function EvidenceSection({ title, evidence }: { title: string; evidence: Record<string, EvidenceItem[]> }) {
  const entries = Object.entries(evidence).filter(([, items]) => items.length > 0);
  return (
    <section className="content-section">
      <h2>{title}</h2>
      {entries.length === 0 ? <p className="muted">No preserved fit evidence.</p> : null}
      {entries.map(([key, items], groupIndex) => (
        <div className="evidence-group" key={key}>
          <span>{String(groupIndex + 1).padStart(2, "0")}</span>
          <div>
            <h3>{humanize(key)}</h3>
            {items.slice(0, 3).map((item, index) => (
              <p key={`${key}-${index}`}>
                <b>{item.origin || "source"}</b>
                {item.text}
              </p>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function ListSection({ title, icon, items, empty }: { title: string; icon: React.ReactNode; items: string[]; empty: string }) {
  return (
    <section className="content-section compact">
      <h2>{icon}{title}</h2>
      {items.length ? (
        <div className="number-list">
          {items.slice(0, 6).map((item, index) => (
            <div key={item}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <p>{item}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">{empty}</p>
      )}
    </section>
  );
}

function EditorArea({ label, value, onChange, compact = false }: { label: string; value: string; onChange: (value: string) => void; compact?: boolean }) {
  return (
    <label className={compact ? "editor-area compact-editor" : "editor-area"}>
      <span>{label.toUpperCase()}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function PackRow({ number, title, meta }: { number: string; title: string; meta: string }) {
  return (
    <div className="pack-row">
      <span>{number}</span>
      <div>
        <b>{title}</b>
        <small>{meta}</small>
      </div>
      <ArrowUpRight size={16} />
    </div>
  );
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="spec">
      <span>{label.toUpperCase()}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Stat({ label, value, dark = false }: { label: string; value: string; dark?: boolean }) {
  return (
    <div className={dark ? "stat-box dark" : "stat-box"}>
      <strong>{value}</strong>
      <span>{label}</span>
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

function BottomNav({ activeView, onNavigate }: { activeView: View; onNavigate: (view: View) => void }) {
  return (
    <div className="screen-nav-wrap">
      <nav className="bottom-nav" aria-label="Primary">
        <NavButton icon={<Inbox />} label="Inbox" active={activeView === "inbox"} onClick={() => onNavigate("inbox")} />
        <NavButton icon={<Columns3 />} label="Pipeline" active={false} onClick={() => onNavigate("inbox")} />
        <NavButton icon={<Bell />} label="Activity" active={activeView === "activity"} onClick={() => onNavigate("activity")} />
        <NavButton icon={<UserRound />} label="Me" active={activeView === "preferences"} onClick={() => onNavigate("preferences")} />
      </nav>
    </div>
  );
}

function MobileDock({ activeView, onNavigate }: { activeView: View; onNavigate: (view: View) => void }) {
  return (
    <div className="mobile-dock">
      <BottomNav activeView={activeView} onNavigate={onNavigate} />
    </div>
  );
}

function PulseBars() {
  return (
    <div className="pulse-bars" aria-hidden="true">
      {[3, 5, 8, 4, 7, 6, 8, 3, 5, 8, 6, 4, 7, 8, 5, 3, 6, 8, 4, 7].map((height, index) => (
        <span key={`${height}-${index}`} style={{ height }} className={height > 6 ? "hot" : ""} />
      ))}
    </div>
  );
}

function EmptyDetail() {
  return <div className="state-card empty-detail">Select a preserved job to review.</div>;
}

function ActivityIcon({ kind }: { kind: string }) {
  if (kind.includes("feedback")) return <BrainCircuit size={15} />;
  if (kind.includes("job")) return <ScanSearch size={15} />;
  if (kind.includes("preference")) return <SlidersHorizontal size={15} />;
  return <Bell size={15} />;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    const detail = await errorDetail(response);
    if (response.status === 401) {
      throw new AuthExpiredError(detail);
    }
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

class AuthExpiredError extends Error {
  constructor(message: string) {
    super(message || "Session expired");
    this.name = "AuthExpiredError";
  }
}

async function errorDetail(response: Response) {
  const body = await response.text();
  if (!body) return `${response.status} ${response.statusText}`;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    return typeof parsed.detail === "string" ? parsed.detail : body;
  } catch {
    return body;
  }
}

function initial(value: string) {
  return value.trim().charAt(0).toUpperCase() || "J";
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatAge(value?: string) {
  if (!value) return "NEW";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "2-digit" }).format(new Date(value)).toUpperCase();
}

function compactLocation(job: Pick<JobListItem, "location" | "work_mode">) {
  return job.location || job.work_mode || "Location unknown";
}

function shortSalary(job: Pick<JobListItem, "salary_display">) {
  const display = job.salary_display?.trim();
  if (!display) return "SALARY TBD";
  const amount = display.match(/[€$£]\s?[\d.,]+(?:\s*[–-]\s*[€$£]?\s?[\d.,]+)?(?:\s*[kK])?/);
  if (amount) return amount[0].toUpperCase();
  return display.length <= 24 ? display.toUpperCase() : "SALARY LISTED";
}

function formatSalary(job: JobDetail) {
  if (job.salary_min_annual != null) {
    return `${new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(job.salary_min_annual)}+`;
  }
  return job.salary_display || "Unknown";
}

function evidenceCount(evidence: Record<string, EvidenceItem[]>) {
  return Object.values(evidence).reduce((count, items) => count + items.length, 0);
}

function filterCount(filter: Filter, jobs: JobListItem[], counts: { inboxCount: number; strongCount: number }) {
  if (filter === "inbox") return counts.inboxCount;
  if (filter === "strong") return counts.strongCount;
  if (filter === "maybe") return jobs.filter((job) => job.status === "maybe").length;
  if (filter === "low") return jobs.filter((job) => (job.score ?? 100) < 50 || job.status === "bad").length;
  if (filter === "reviewed") return jobs.filter((job) => job.status !== "inbox").length;
  return jobs.length;
}

function formatCurrencyValue(value: number, currency: string) {
  if (!value) return `${currency} --`;
  return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0, notation: "compact" }).format(value);
}

function salaryPercent(value: number) {
  if (!value) return 46;
  return Math.min(92, Math.max(12, ((value - 30000) / 120000) * 100));
}

function preferredRules(preferences: Preferences) {
  const defaults = ["Remote within EU", "Senior or lead", "Product companies"];
  const merged = [...defaults, ...preferences.hard_rules];
  return Array.from(new Set(merged)).slice(0, 5);
}

function ruleMeta(rule: string) {
  if (/remote/i.test(rule)) return "No relocation";
  if (/senior|lead/i.test(rule)) return "Skip junior roles";
  if (/product/i.test(rule)) return "Agencies are okay";
  return "Hard filter";
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
