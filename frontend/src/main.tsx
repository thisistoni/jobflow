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
  CheckCircle2,
  ClipboardCheck,
  Circle,
  Columns3,
  ExternalLink,
  FileText,
  Inbox,
  ListFilter,
  LockKeyhole,
  LogOut,
  Save,
  RefreshCw,
  ScanSearch,
  Settings2,
  SlidersHorizontal,

  Target,
  Trash2,
  Unplug,
  UserRound,
  X
} from "lucide-react";
import "./styles.css";

type Rating = "good" | "maybe" | "bad";
type View = "inbox" | "pipeline" | "activity" | "preferences";
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
  first_seen_at: string;
  source_url: string;
  feedback?: Feedback | null;
  pack_status?: "preparing" | "ready" | "failed" | null;
  pack_revision_state?: "current" | "changes_requested" | "regenerated" | null;
};

type ApplicationPack = {
  status: "preparing" | "ready" | "failed";
  version: number;
  revision_state: "current" | "changes_requested" | "regenerated";
  revision_reasons: string[];
  revision_note: string;
  resume_id: string | null;
  resume_name: string | null;
  resume_pdf_pages: number | null;
  letter_subject: string | null;
  letter_body: string | null;
  error: string | null;
  updated_at: string;
  versions: Array<{
    version: number;
    revision_state: "current" | "changes_requested" | "regenerated";
    revision_reasons: string[];
    revision_note: string;
    resume_id: string | null;
    resume_name: string | null;
    resume_pdf_pages: number | null;
    letter_subject: string | null;
    created_at: string;
  }>;
};

function isUserVisibleJob(job: JobListItem) {
  return job.status !== "inbox" || job.pack_status === "ready";
}

type EvidenceItem = {
  origin?: string | null;
  text: string;
  profile_fact_ref?: string | null;
};

type JobDetail = JobListItem & {
  raw_description?: string | null;
  extracted_description?: string | null;
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
  application_pack: ApplicationPack | null;
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
  priority_role_families: string[];
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

type DiscoveryRun = {
  run_id: string;
  queries: string[];
  limit_per_query: number;
  results: Array<{ url: string; title?: string | null; description?: string | null }>;
  jobs_added: number;
  jobs_evaluated: number;
  packs_prepared: number;
};

type DiscoveryRunSummary = {
  id: string;
  trigger: "manual" | "scheduled";
  status: "running" | "succeeded" | "failed";
  started_at: string;
  finished_at?: string | null;
  queries: string[];
  candidate_count: number;
  unique_count: number;
  jobs_added: number;
  jobs_evaluated: number;
  packs_prepared: number;
  error?: string | null;
};

type DiscoveryOperations = {
  schedule: { enabled: boolean; timezone: string; times: string[] };
  sources: Array<{
    id: string;
    label: string;
    enabled: boolean;
    status: "available" | "setup_required" | "manual" | "disabled" | "failing";
    detail: string;
  }>;
  generated_queries: string[];
  next_run_at?: string | null;
  last_run?: DiscoveryRunSummary | null;
  recent_runs: DiscoveryRunSummary[];
};

type ReactiveResumeStatus = {
  encryption_ready: boolean;
  configured: boolean;
  verified: boolean;
  base_url: string;
  configured_at: string | null;
  last_verified_at: string | null;
  last_error: string | null;
  reference: { id: string; name: string; template: string | null; updated_at: string | null } | null;
  available_resumes: Array<{ id: string; name: string; updated_at: string | null; historical_source: boolean }>;
};

type DashboardPulse = {
  days: Array<{ date: string; count: number }>;
  today_count: number;
};

const filters: Array<{ id: Filter; label: string }> = [
  { id: "inbox", label: "For you" },
  { id: "maybe", label: "Review" },
  { id: "reviewed", label: "Saved" }
];

const quickReasons: Record<Rating, string[]> = {
  good: ["Strong builder fit", "Good salary signal", "Right work mode", "Worth preparing"],
  maybe: ["CV needs changes", "Letter needs changes", "Fit analysis looks wrong", "Missing information", "Keep for later"],
  bad: ["Salary below target", "Remote policy unclear", "Company does not excite me", "Seniority feels wrong", "Role focus is off"]
};

function App() {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);
  const [jobs, setJobs] = React.useState<JobListItem[]>([]);
  const [allJobs, setAllJobs] = React.useState<JobListItem[]>([]);
  const [pipelineJobs, setPipelineJobs] = React.useState<JobListItem[]>([]);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [selectedJob, setSelectedJob] = React.useState<JobDetail | null>(null);
  const [filter, setFilter] = React.useState<Filter>("inbox");
  const [view, setView] = React.useState<View>("inbox");
  const [activity, setActivity] = React.useState<ActivityItem[]>([]);
  const [preferences, setPreferences] = React.useState<Preferences | null>(null);
  const [pulse, setPulse] = React.useState<DashboardPulse>({ days: [], today_count: 0 });
  const [discoveryOperations, setDiscoveryOperations] = React.useState<DiscoveryOperations | null>(null);
  const [reactiveResume, setReactiveResume] = React.useState<ReactiveResumeStatus | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [discoveryRunning, setDiscoveryRunning] = React.useState(false);
  const [discoveryMessage, setDiscoveryMessage] = React.useState<string | null>(null);
  const [discoveryError, setDiscoveryError] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = React.useState(false);
  const [feedbackMode, setFeedbackMode] = React.useState<"decline" | "revise" | null>(null);
  const [feedbackSaving, setFeedbackSaving] = React.useState(false);
  const [feedbackError, setFeedbackError] = React.useState<string | null>(null);
  const [regenerationRunning, setRegenerationRunning] = React.useState(false);
  const [actionNotice, setActionNotice] = React.useState<{ jobId: string; text: string } | null>(null);
  const isUnlocked = auth != null && (!auth.auth_required || auth.authenticated);

  const handleAuthExpired = React.useCallback((reason: unknown) => {
    if (reason instanceof AuthExpiredError) {
      setAuth({ auth_required: true, authenticated: false });
      setJobs([]);
      setAllJobs([]);
      setPipelineJobs([]);
      setSelectedId(null);
      setSelectedJob(null);
      setActivity([]);
      setPreferences(null);
      setPulse({ days: [], today_count: 0 });
      setDiscoveryOperations(null);
      setReactiveResume(null);
      setError(null);
      setFeedbackMode(null);
      setFeedbackSaving(false);
      setFeedbackError(null);
      setDiscoveryError(null);
      setActionNotice(null);
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

  const loadAllJobs = React.useCallback(async () => {
    const data = await api<JobListItem[]>("/api/jobs?filter=all&limit=200");
    setAllJobs(data);
    setPipelineJobs(data.filter(isUserVisibleJob));
    return data;
  }, []);

  React.useEffect(() => {
    if (!isUnlocked) return;
    setLoading(true);
    Promise.all([loadJobs(), loadAllJobs()])
      .catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      })
      .finally(() => setLoading(false));
  }, [handleAuthExpired, isUnlocked, loadAllJobs, loadJobs]);

  React.useEffect(() => {
    if (!isUnlocked) return;
    api<DashboardPulse>("/api/dashboard/pulse?days=20").then(setPulse).catch((reason: unknown) => {
      if (!handleAuthExpired(reason)) setError(messageFrom(reason));
    });
  }, [handleAuthExpired, isUnlocked]);

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
    if (view === "pipeline") {
      loadAllJobs().catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
    }
    if (view === "activity") {
      api<ActivityItem[]>("/api/activity").then(setActivity).catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
    }
    if (view === "preferences") {
      Promise.all([
        api<Preferences>("/api/preferences"),
        api<DiscoveryOperations>("/api/discovery/operations"),
        api<ReactiveResumeStatus>("/api/integrations/reactive-resume")
      ]).then(([nextPreferences, operations, resumeStatus]) => {
        setPreferences(nextPreferences);
        setDiscoveryOperations(operations);
        setReactiveResume(resumeStatus);
      }).catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
    }
  }, [handleAuthExpired, isUnlocked, loadAllJobs, view]);

  React.useEffect(() => {
    if (!isUnlocked) return;
    function refreshVisibleData() {
      if (document.visibilityState !== "visible") return;
      void loadJobs().catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
      void loadAllJobs().catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
      void api<DashboardPulse>("/api/dashboard/pulse?days=20").then(setPulse).catch((reason: unknown) => {
        if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      });
      if (view === "activity") {
        void api<ActivityItem[]>("/api/activity").then(setActivity).catch((reason: unknown) => {
          if (!handleAuthExpired(reason)) setError(messageFrom(reason));
        });
      }
      if (view === "preferences") {
        void api<DiscoveryOperations>("/api/discovery/operations").then(setDiscoveryOperations).catch((reason: unknown) => {
          if (!handleAuthExpired(reason)) setError(messageFrom(reason));
        });
      }
    }
    window.addEventListener("focus", refreshVisibleData);
    document.addEventListener("visibilitychange", refreshVisibleData);
    return () => {
      window.removeEventListener("focus", refreshVisibleData);
      document.removeEventListener("visibilitychange", refreshVisibleData);
    };
  }, [handleAuthExpired, isUnlocked, loadAllJobs, loadJobs, view]);

  const inboxCount = allJobs.filter((job) => job.status === "inbox" && job.pack_status === "ready").length;
  const strongCount = allJobs.filter((job) => job.status === "inbox" && job.pack_status === "ready" && (job.score ?? 0) >= 70).length;

  async function submitFeedback(rating: Rating, reasons: string[], note: string) {
    if (!selectedJob || feedbackSaving) return;
    const actedJobId = selectedJob.id;
    setFeedbackSaving(true);
    setFeedbackError(null);
    try {
      await api<Feedback>(`/api/jobs/${actedJobId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, reasons, note })
      });
      const updated = await api<JobDetail>(`/api/jobs/${actedJobId}`);
      setSelectedJob(updated);
      setFeedbackMode(null);
      const text = rating === "bad"
        ? "Moved to Passed. Your decline feedback is saved."
        : rating === "maybe"
          ? "Moved to Review. The current pack is invalidated until regenerated."
          : "Application pack approved and saved for manual application.";
      setActionNotice({ jobId: actedJobId, text });
      if (rating === "maybe") {
        setJobs((current) => current.filter((job) => job.id !== actedJobId));
      } else {
        await loadJobs();
      }
      await loadAllJobs();
      setActivity(await api<ActivityItem[]>("/api/activity"));
    } catch (reason) {
      if (!handleAuthExpired(reason)) {
        const message = messageFrom(reason);
        setFeedbackError(message);
        setError(message);
      }
    } finally {
      setFeedbackSaving(false);
    }
  }

  async function regeneratePack() {
    if (!selectedJob || regenerationRunning) return;
    const actedJobId = selectedJob.id;
    setRegenerationRunning(true);
    setFeedbackError(null);
    try {
      const updated = await api<JobDetail>(`/api/jobs/${actedJobId}/regenerate-pack`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reasons: selectedJob.feedback?.reasons ?? [],
          note: selectedJob.feedback?.note ?? ""
        })
      });
      setSelectedJob(updated);
      setActionNotice({ jobId: actedJobId, text: `Regenerated pack v${updated.application_pack?.version ?? ""}. Returned to Inbox when ready.` });
      await loadJobs();
      await loadAllJobs();
      setActivity(await api<ActivityItem[]>("/api/activity"));
    } catch (reason) {
      if (!handleAuthExpired(reason)) {
        const message = messageFrom(reason);
        setFeedbackError(message);
        setError(message);
      }
    } finally {
      setRegenerationRunning(false);
    }
  }

  async function runDiscovery() {
    setDiscoveryRunning(true);
    setDiscoveryMessage(null);
    setDiscoveryError(null);
    setError(null);
    try {
      const result = await api<DiscoveryRun>("/api/discovery/run", { method: "POST" });
      setDiscoveryMessage(
        `${result.results.length} unique candidates · ${result.jobs_added} new jobs · ${result.packs_prepared} application packs ready.`
      );
      setDiscoveryOperations(await api<DiscoveryOperations>("/api/discovery/operations"));
      setActivity(await api<ActivityItem[]>("/api/activity"));
      await loadJobs();
      await loadAllJobs();
    } catch (reason) {
      if (!handleAuthExpired(reason)) {
        const message = messageFrom(reason);
        setDiscoveryError(message);
        setError(message);
      }
    } finally {
      setDiscoveryRunning(false);
    }
  }

  async function savePreferences(next: Preferences): Promise<Preferences> {
    try {
      const updated = await api<Preferences>("/api/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next)
      });
      setPreferences(updated);
      setDiscoveryOperations(await api<DiscoveryOperations>("/api/discovery/operations"));
      setActivity(await api<ActivityItem[]>("/api/activity"));
      return updated;
    } catch (reason) {
      if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      throw reason;
    }
  }

  async function saveDiscoveryConfig(schedule: DiscoveryOperations["schedule"], sourcesEnabled: Record<string, boolean>) {
    try {
      const updated = await api<DiscoveryOperations>("/api/discovery/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schedule, sources_enabled: sourcesEnabled })
      });
      setDiscoveryOperations(updated);
      setActivity(await api<ActivityItem[]>("/api/activity"));
      return updated;
    } catch (reason) {
      if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      throw reason;
    }
  }

  async function updateReactiveResume(path: string, method: "POST" | "PUT" | "DELETE", payload?: unknown) {
    try {
      const options: RequestInit = { method };
      if (payload !== undefined) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(payload);
      }
      const updated = await api<ReactiveResumeStatus>(path, options);
      setReactiveResume(updated);
      return updated;
    } catch (reason) {
      if (!handleAuthExpired(reason)) setError(messageFrom(reason));
      throw reason;
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
      setAllJobs([]);
      setPipelineJobs([]);
      setSelectedId(null);
      setSelectedJob(null);
      setActivity([]);
      setPreferences(null);
      setPulse({ days: [], today_count: 0 });
      setDiscoveryOperations(null);
      setReactiveResume(null);
      setMobileDetailOpen(false);
      setFeedbackMode(null);
      setFeedbackSaving(false);
      setFeedbackError(null);
      setDiscoveryError(null);
      setActionNotice(null);
    }
  }

  function navigate(next: View) {
    setView(next);
    setMobileDetailOpen(false);
    setFeedbackMode(null);
    setActionNotice(null);
  }

  if (auth == null) {
    return <LoginScreen loading={loading} error={error} onLogin={submitLogin} />;
  }

  if (auth.auth_required && !auth.authenticated) {
    return <LoginScreen error={error} onLogin={submitLogin} />;
  }

  const detail = feedbackMode && selectedJob ? (
      <DeclineFeedback
        job={selectedJob}
        mode={feedbackMode}
        saving={feedbackSaving}
        error={feedbackError}
        onClose={() => setFeedbackMode(null)}
        onFeedback={(reasons, note) => void submitFeedback(feedbackMode === "decline" ? "bad" : "maybe", reasons, note)}
      />
  ) : view === "inbox" ? (
    selectedJob ? (
      <JobReview
        job={selectedJob}
        actionNotice={actionNotice?.jobId === selectedJob.id ? actionNotice.text : null}
        saving={feedbackSaving || regenerationRunning}
        error={feedbackError}
        onBack={() => setMobileDetailOpen(false)}
        onDecline={() => setFeedbackMode("decline")}
        onRevise={() => setFeedbackMode("revise")}
        onApprove={() => void submitFeedback("good", ["Application pack approved"], "")}
        onRegenerate={() => void regeneratePack()}
      />
    ) : (
      <EmptyDetail />
    )
  ) : view === "pipeline" ? (
    <PipelineView
      jobs={pipelineJobs}
      onSelect={(id) => {
        setSelectedId(id);
        setActionNotice(null);
        setView("inbox");
        setMobileDetailOpen(true);
      }}
    />
  ) : view === "activity" ? (
    <ActivityView
      items={activity}
      jobs={allJobs}
      onOpenJob={(id) => {
        setSelectedId(id);
        setActionNotice(null);
        setView("inbox");
        setMobileDetailOpen(true);
        setFeedbackMode(null);
      }}
      onOpenSettings={() => {
        navigate("preferences");
        window.setTimeout(() => document.getElementById("search-automation")?.scrollIntoView({ behavior: "smooth" }), 0);
      }}
    />
  ) : preferences ? (
    <PreferencesView
      preferences={preferences}
      operations={discoveryOperations}
      discoveryRunning={discoveryRunning}
      discoveryMessage={discoveryMessage}
      discoveryError={discoveryError}
      reactiveResume={reactiveResume}
      onRunDiscovery={runDiscovery}
      onSaveDiscovery={saveDiscoveryConfig}
      onConnectReactiveResume={(apiKey, baseUrl) => updateReactiveResume(
        "/api/integrations/reactive-resume/connect",
        "POST",
        { api_key: apiKey, base_url: baseUrl }
      )}
      onRefreshReactiveResume={() => updateReactiveResume("/api/integrations/reactive-resume/refresh", "POST")}
      onSelectReactiveResume={(resumeId) => updateReactiveResume(
        "/api/integrations/reactive-resume/reference",
        "PUT",
        { resume_id: resumeId }
      )}
      onDisconnectReactiveResume={() => updateReactiveResume("/api/integrations/reactive-resume", "DELETE")}
      onSave={savePreferences}
    />
  ) : (
    <div className="state-card">Loading preferences...</div>
  );

  return (
    <div className="app-shell">
      <aside className="desktop-rail" aria-label="Primary">
        <div className="brand-mark">JF</div>
        <NavButton icon={<Inbox />} label="Inbox" active={view === "inbox" && !feedbackMode} onClick={() => navigate("inbox")} />
        <NavButton icon={<Columns3 />} label="Pipeline" active={view === "pipeline"} onClick={() => navigate("pipeline")} />
        <NavButton icon={<Bell />} label="Activity" active={view === "activity"} onClick={() => navigate("activity")} />
        <NavButton icon={<UserRound />} label="Me" active={view === "preferences"} onClick={() => navigate("preferences")} />
        {auth.auth_required ? (
          <button className="rail-logout" type="button" onClick={() => void logout()} aria-label="Log out">
            <LogOut size={18} />
          </button>
        ) : null}
      </aside>

      <main className={`workspace view-${view} ${mobileDetailOpen || feedbackMode ? "mobile-detail-open" : ""}`}>
        <section className="phone-surface inbox-pane" aria-label="Pulse Inbox">
          <InboxScreen
            jobs={jobs}
            countJobs={allJobs}
            selectedId={selectedId}
            filter={filter}
            loading={loading}
            discoveryRunning={discoveryRunning}
            discoveryMessage={discoveryMessage}
            operations={discoveryOperations}
            pulse={pulse}
            error={error || discoveryError}
            counts={{ inboxCount, strongCount }}
            onRefresh={() => void runDiscovery()}
            onFilter={setFilter}
            onSelect={(id) => {
              setSelectedId(id);
              setActionNotice(null);
              setView("inbox");
              setMobileDetailOpen(true);
              setFeedbackMode(null);
            }}
            activeView={view}
            onNavigate={navigate}
          />
        </section>

        <section className="phone-surface detail-pane" aria-label="Current JobFlow state">
          {detail}
        </section>
      </main>

      {mobileDetailOpen || feedbackMode ? null : <MobileDock activeView={view} onNavigate={navigate} />}
    </div>
  );
}

function InboxScreen({
  jobs,
  countJobs,
  selectedId,
  filter,
  loading,
  discoveryRunning,
  discoveryMessage,
  operations,
  pulse,
  error,
  counts,
  onRefresh,
  onFilter,
  onSelect,
  activeView,
  onNavigate
}: {
  jobs: JobListItem[];
  countJobs: JobListItem[];
  selectedId: string | null;
  filter: Filter;
  loading: boolean;
  discoveryRunning: boolean;
  discoveryMessage: string | null;
  operations: DiscoveryOperations | null;
  pulse: DashboardPulse;
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
          <button
            className={discoveryRunning ? "round-action is-running" : "round-action"}
            type="button"
            onClick={onRefresh}
            disabled={discoveryRunning}
            aria-label="Run job discovery"
          >
            <ScanSearch size={20} />
          </button>
        </div>
        <div className="daily-match">
          <strong>{jobs.length.toString().padStart(2, "0")}</strong>
          <div>
            <h2>{filter === "inbox" ? "application packs ready" : "jobs in this view"}</h2>
            <p>{filter === "inbox" && operations?.last_run
              ? `Last search ${formatDateTime(operations.last_run.finished_at || operations.last_run.started_at)} · ${operations.last_run.jobs_added} new · ${operations.last_run.packs_prepared} packs`
              : filter === "inbox" ? "Prepared CV + PDF application letter" : "Only complete packs and reviewed history are shown"}</p>
          </div>
        </div>
        <PulseBars days={pulse.days} />
      </header>

      <div className="screen-body inbox-body">
        <nav className="filter-strip" aria-label="Job filters">
          {filters.map((item) => (
            <button key={item.id} className={filter === item.id ? "active" : ""} onClick={() => onFilter(item.id)} type="button">
              {item.label.toUpperCase()} · {filterCount(item.id, countJobs, counts)}
            </button>
          ))}
        </nav>

        {discoveryMessage ? <div className="discovery-status" role="status">{discoveryMessage}</div> : null}

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
              {featured.pack_status === "ready" ? <span>PACK READY</span> : null}
              <span>FOUND {formatFoundDate(featured.first_seen_at)}</span>
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
                <small>{job.company.toUpperCase()} · {compactLocation(job).toUpperCase()} · {shortSalary(job)} · {job.score ?? "--"}%{job.pack_status === "ready" ? " · PACK READY" : ""} · FOUND {formatFoundDate(job.first_seen_at)}</small>
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
  actionNotice,
  saving,
  error,
  onBack,
  onDecline,
  onRevise,
  onApprove,
  onRegenerate
}: {
  job: JobDetail;
  actionNotice: string | null;
  saving: boolean;
  error: string | null;
  onBack: () => void;
  onDecline: () => void;
  onRevise: () => void;
  onApprove: () => void;
  onRegenerate: () => void;
}) {
  const pack = job.application_pack;
  const statusCopy = actionNotice || (
    job.status === "bad"
      ? "Passed. Your decline feedback is saved."
      : job.status === "maybe"
        ? "Changes requested. Your feedback is attached in Review."
        : job.status === "good"
          ? "Pack approved and saved for manual application."
          : null
  );
  return (
    <article className="review-screen">
      <header className="review-hero">
        <div className="detail-nav">
          <button className="icon-button outlined mobile-back" type="button" onClick={onBack} aria-label="Back to jobs">
            <ArrowLeft size={18} />
          </button>
          <span className="micro orange-text">MATCH REVIEW</span>
          <a className="icon-button outlined" href={job.source_url} target="_blank" rel="noreferrer" aria-label="Open source job">
            <ExternalLink size={18} />
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
            <small>{job.verdict || "Preserved for review"} · {job.confidence || "confidence unknown"} · Found {formatFoundDate(job.first_seen_at, true)}</small>
          </span>
        </div>
      </header>

      <div className="screen-body review-body">
        {statusCopy ? (
          <div className={`job-status-notice status-${job.status}`} role="status">
            <CheckCircle2 size={17} />
            <span>{statusCopy}</span>
          </div>
        ) : null}
        {error ? <div className="state-card error">{error}</div> : null}
        <section className="insight-row">
          <span>01</span>
          <div>
            <h2>Why your agent chose this</h2>
            <p>{job.summary || "This role was preserved by the scoring pass for a closer manual review."}</p>
          </div>
        </section>

        <section className={`pack pack-${pack?.status || "missing"}`}>
          <div className="pack-header">
            <b>APPLICATION PACK</b>
            <span>{pack?.status === "ready" ? `READY V${pack.version}` : pack?.revision_state === "changes_requested" ? `CHANGES REQUESTED V${pack.version}` : pack?.status === "failed" ? "NEEDS ATTENTION" : "PREPARING"}</span>
          </div>
          {pack?.status === "ready" ? (
            <>
              <PackRow number="01" title="Prepared CV" meta={`${pack.resume_pdf_pages || 1}-page PDF · ${pack.resume_name || "Job-specific Base CV copy"}`} href={`/api/jobs/${job.id}/cv.pdf`} />
              <PackRow number="02" title="Application letter" meta={`PDF · ${pack.letter_subject || "German application letter"}`} href={`/api/jobs/${job.id}/application-letter.pdf`} />
              {pack.versions?.length > 1 ? (
                <div className="pack-version-history">
                  <b>VERSION HISTORY</b>
                  {pack.versions.map((item) => (
                    <span key={item.version}>
                      V{item.version}
                      <a href={`/api/jobs/${job.id}/cv.pdf?version=${item.version}`} target="_blank" rel="noreferrer">CV</a>
                      <a href={`/api/jobs/${job.id}/application-letter.pdf?version=${item.version}`} target="_blank" rel="noreferrer">LETTER</a>
                    </span>
                  ))}
                </div>
              ) : null}
            </>
          ) : (
            <p className="pack-state-copy">
              {pack?.status === "failed"
                ? pack.error || "The package could not be prepared yet."
                : pack?.revision_state === "changes_requested"
                  ? pack.error || "Changes are saved. Regenerate to create a new ready pack version."
                : "JobFlow is preparing a job-specific Base CV copy and German application letter."}
            </p>
          )}
          {pack?.revision_state === "changes_requested" ? (
            <button className="regenerate-action" type="button" onClick={onRegenerate} disabled={saving}>
              <RefreshCw size={15} /> {saving ? "REGENERATING" : "REGENERATE PACK"}
            </button>
          ) : null}
        </section>

        <div className="spec-strip">
          <Spec label="Salary" value={formatSalary(job)} />
          <Spec label="Type" value={(job.work_mode || "Unknown").toUpperCase()} />
          <Spec label="Place" value={compactLocation(job).toUpperCase()} />
        </div>

        <EvidenceSection title="Fit evidence" evidence={job.fit_evidence} />
        <ListSection title="Missing information" icon={<ListFilter size={15} />} items={job.missing_info} empty="Source extraction is complete enough for review." />
        <ListSection title="Hard gate concerns" icon={<Circle size={15} />} items={job.hard_gate_reasons} empty="No hard gate concern preserved." />
        <ListSection title="Responsibilities" icon={<BriefcaseBusiness size={15} />} items={job.responsibilities} empty="No responsibilities extracted." />
        <ListSection title="Requirements" icon={<ClipboardCheck size={15} />} items={job.requirements} empty="No requirements extracted." />
        <SourceDescription job={job} />
      </div>

      <footer className="review-actions">
        <button className="reject-action" type="button" onClick={onDecline} aria-label="Decline role" disabled={saving}>
          <Trash2 size={18} />
        </button>
        <button className="revise-action" type="button" onClick={onRevise} disabled={saving}>
          REQUEST CHANGES
        </button>
        <button className="approve-action" type="button" onClick={onApprove} disabled={saving || pack?.status !== "ready"}>
          {saving ? "SAVING…" : "APPROVE PACK"} <ArrowRight size={16} />
        </button>
      </footer>
    </article>
  );
}

function DeclineFeedback({
  job,
  mode,
  saving,
  error,
  onClose,
  onFeedback
}: {
  job: JobDetail;
  mode: "decline" | "revise";
  saving: boolean;
  error: string | null;
  onClose: () => void;
  onFeedback: (reasons: string[], note: string) => void;
}) {
  const targetRating: Rating = mode === "decline" ? "bad" : "maybe";
  const options = quickReasons[targetRating];
  const initialReasons = job.feedback?.rating === targetRating ? job.feedback.reasons : [];
  const [reasons, setReasons] = React.useState<string[]>(initialReasons);
  const [note, setNote] = React.useState(job.feedback?.rating === targetRating ? job.feedback.note : "");
  const canSubmit = reasons.length > 0 || note.trim().length > 0;

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
          <span className="micro">REVIEW CONTEXT</span>
        </div>
        <h1>{mode === "decline" ? <>Pass on this.<br />Save the reason.</> : <>What should<br />change?</>}</h1>
        <p className="decline-lead">
          {mode === "decline"
            ? "This exact role will move to Passed with your reason saved."
            : "The job will move to Review and the current pack will be invalidated until you regenerate it."}
        </p>

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
            <h2>{mode === "decline" ? "What missed?" : "What needs another look?"}</h2>
            <span>{reasons.length} SELECTED</span>
          </div>
          {options.map((reason, index) => (
            <button type="button" key={reason} className={reasons.includes(reason) ? "chosen" : ""} onClick={() => toggleReason(reason)}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <b>{reason}</b>
              {reasons.includes(reason) ? <Check size={14} /> : <Circle size={18} />}
            </button>
          ))}
        </section>

        <label className="note-field">
          <span>ADD CONTEXT · {reasons.length ? "OPTIONAL" : "REQUIRED"}</span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={mode === "decline" ? "Why is this not for you?" : "What should change in the CV, letter, or fit analysis?"}
          />
        </label>

        {error ? <div className="state-card error">{error}</div> : null}

        <div className="learning-line">
          <BrainCircuit size={18} />
          <span>Saved here as review context; regeneration uses these notes deterministically for this job.</span>
        </div>
      </div>
      <footer className="decline-submit">
        <button type="button" disabled={!canSubmit || saving} onClick={() => onFeedback(reasons, note)}>
          {saving ? "SAVING…" : mode === "decline" ? "DECLINE + SAVE FEEDBACK" : "MOVE TO REVIEW"} <ArrowRight size={16} />
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

function PreferencesView({
  preferences,
  operations,
  discoveryRunning,
  discoveryMessage,
  discoveryError,
  reactiveResume,
  onRunDiscovery,
  onSaveDiscovery,
  onConnectReactiveResume,
  onRefreshReactiveResume,
  onSelectReactiveResume,
  onDisconnectReactiveResume,
  onSave
}: {
  preferences: Preferences;
  operations: DiscoveryOperations | null;
  discoveryRunning: boolean;
  discoveryMessage: string | null;
  discoveryError: string | null;
  reactiveResume: ReactiveResumeStatus | null;
  onRunDiscovery: () => Promise<void>;
  onSaveDiscovery: (schedule: DiscoveryOperations["schedule"], sourcesEnabled: Record<string, boolean>) => Promise<DiscoveryOperations>;
  onConnectReactiveResume: (apiKey: string, baseUrl: string) => Promise<ReactiveResumeStatus>;
  onRefreshReactiveResume: () => Promise<ReactiveResumeStatus>;
  onSelectReactiveResume: (resumeId: string) => Promise<ReactiveResumeStatus>;
  onDisconnectReactiveResume: () => Promise<ReactiveResumeStatus>;
  onSave: (next: Preferences) => Promise<Preferences>;
}) {
  const initial = normalizeEditablePreferences(preferences);
  const [draft, setDraft] = React.useState(initial);
  const [baseline, setBaseline] = React.useState(initial);
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  React.useEffect(() => {
    const normalized = normalizeEditablePreferences(preferences);
    setDraft(normalized);
    setBaseline(normalized);
    setSaveError(null);
  }, [preferences]);


  function toggleWorkMode(mode: string) {
    const nextModes = draft.work_modes.includes(mode)
      ? draft.work_modes.filter((item) => item !== mode)
      : [...draft.work_modes, mode];
    setDraft({ ...draft, work_modes: nextModes });
  }

  const salaryMin = boundedNumber(String(draft.salary_target_min ?? 50000), 30000, 120000, 50000);
  const salaryMax = boundedNumber(String(draft.salary_target_max ?? 56000), 30000, 120000, 56000);
  const isDirty = preferenceFingerprint(draft) !== preferenceFingerprint(baseline);

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      const saved = normalizeEditablePreferences(await onSave({ ...draft, manual_submission_only: true }));
      setDraft(saved);
      setBaseline(saved);
    } catch (reason) {
      setSaveError(messageFrom(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="preferences-screen">
      <header className="pref-hero">
        <div className="hero-top">
          <div>
            <p className="micro orange-text">SEARCH DNA</p>
            <h1>Search profile</h1>
          </div>
          <span className="round-action">
            <BrainCircuit size={20} />
          </span>
        </div>
        <p>Saved salary, location, commute, language, and seniority gates control which packs can reach Inbox.</p>
        <div className="quality-row factual">
          <span><i style={{ width: `${Math.min(100, Math.max(18, draft.role_families.length * 12))}%` }} /></span>
          <b>{draft.role_families.length} ROLE TAGS</b>
        </div>
      </header>

      <div className="screen-body preferences-body">
        <section className="salary-card">
          <div>
            <span className="micro">TARGET RANGE</span>
            <strong>{formatCurrencyValue(salaryMin, draft.salary_currency)}–{formatCurrencyValue(salaryMax, draft.salary_currency)}</strong>
          </div>
          <span className="micro">GROSS / YEAR</span>
          <div className="salary-track">
            <span className="salary-rail" />
            <span
              className="salary-fill"
              style={{ left: `${salaryPercent(salaryMin)}%`, right: `${100 - salaryPercent(salaryMax)}%` }}
            />
            <input
              className="salary-range salary-range-min"
              aria-label="Target minimum salary"
              type="range"
              min={30000}
              max={120000}
              step={1000}
              value={salaryMin}
              onChange={(event) => {
                const nextMin = Math.min(Number(event.target.value), salaryMax);
                setDraft({ ...draft, salary_target_min: nextMin, acceptable_salary_min: nextMin });
              }}
            />
            <input
              className="salary-range salary-range-max"
              aria-label="Target maximum salary"
              type="range"
              min={30000}
              max={120000}
              step={1000}
              value={salaryMax}
              onChange={(event) => setDraft({ ...draft, salary_target_max: Math.max(Number(event.target.value), salaryMin) })}
            />
          </div>
          <div className="salary-inputs">
            <input
              aria-label="Target minimum salary"
              type="number"
              min={30000}
              max={salaryMax}
              step={1000}
              value={salaryMin}
              onChange={(event) => {
                const nextMin = Math.min(boundedNumber(event.target.value, 30000, 120000, salaryMin), salaryMax);
                setDraft({ ...draft, salary_target_min: nextMin, acceptable_salary_min: nextMin });
              }}
            />
            <input
              aria-label="Target maximum salary"
              type="number"
              min={salaryMin}
              max={120000}
              step={1000}
              value={salaryMax}
              onChange={(event) => setDraft({ ...draft, salary_target_max: Math.max(boundedNumber(event.target.value, 30000, 120000, salaryMax), salaryMin) })}
            />
          </div>
          <p className="salary-note">The target minimum is also the hard salary gate used before pack preparation.</p>
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
          {[
            ["Location", draft.target_locations.length ? draft.target_locations.join(", ") : "Wien default"],
            ["Salary", `${formatCurrencyValue(salaryMin, draft.salary_currency)} minimum`],
            ["Work setup", draft.work_modes.length ? draft.work_modes.join(", ") : "No commute gate saved"],
            ["Home office", draft.min_home_office_days == null ? "No minimum saved" : `${draft.min_home_office_days}+ days`],
            ["Seniority", "Senior, lead, manager, principal roles are blocked"]
          ].map(([label, value]) => (
            <div className="rule-row readonly" key={label}>
              <span>
                <b>{label}</b>
                <small>{value}</small>
              </span>
              <i className="on"><b /></i>
            </div>
          ))}
        </section>

        <TagEditor
          label="Target locations"
          placeholder="Add a city or region…"
          values={draft.target_locations}
          onChange={(target_locations) => setDraft({ ...draft, target_locations })}
        />
        <TagEditor
          label="Roles & keywords"
          placeholder="Add a role or keyword…"
          values={draft.role_families}
          onChange={(role_families) => setDraft({
            ...draft,
            role_families,
            priority_role_families: draft.priority_role_families.filter((priority) => role_families.some((role) => role.toLocaleLowerCase() === priority.toLocaleLowerCase()))
          })}
        />
        <TagEditor
          label="Custom search phrases"
          placeholder="Optional exact search phrase…"
          values={draft.discovery_queries}
          onChange={(discovery_queries) => setDraft({ ...draft, discovery_queries })}
        />

        <section className="pref-section">
          <div className="section-head">
            <h2>Priority roles</h2>
            <span>PICK UP TO 5</span>
          </div>
          <p className="priority-help">Choose which of your role tags should lead discovery and ranking.</p>
          <div className="priority-role-grid">
            {draft.role_families.map((role) => {
              const selected = draft.priority_role_families.some((item) => item.toLocaleLowerCase() === role.toLocaleLowerCase());
              return (
                <button
                  type="button"
                  className={selected ? "selected" : ""}
                  key={role}
                  onClick={() => setDraft({
                    ...draft,
                    priority_role_families: selected
                      ? draft.priority_role_families.filter((item) => item.toLocaleLowerCase() !== role.toLocaleLowerCase())
                      : draft.priority_role_families.length < 5 ? [...draft.priority_role_families, role] : draft.priority_role_families
                  })}
                >
                  {selected ? <Check size={12} /> : null}{role}
                </button>
              );
            })}
          </div>
        </section>

        <section className="pref-section" id="search-automation">
          <h2>Discovery operations</h2>
          <label className="inline-field">
            <span>RESULTS PER SEARCH</span>
            <input
              type="number"
              min={1}
              max={20}
              value={draft.discovery_limit_per_query}
              onChange={(event) => setDraft({ ...draft, discovery_limit_per_query: boundedNumber(event.target.value, 1, 20, 5) })}
            />
          </label>
          <DiscoveryOperationsPanel
            operations={operations}
            running={discoveryRunning}
            message={discoveryMessage}
            error={discoveryError}
            onRun={async () => {
              if (isDirty) await save();
              await onRunDiscovery();
            }}
            onSave={onSaveDiscovery}
          />
          <div className="approval-boundary">
            <span className="company-mark dark"><LockKeyhole size={14} /></span>
            <span>
              <b>Applying requires your approval</b>
              <small>Approval saves the pack as good for your manual application. JobFlow does not submit or contact employers.</small>
            </span>
          </div>
        </section>

        <ReactiveResumePanel
          status={reactiveResume}
          onConnect={onConnectReactiveResume}
          onRefresh={onRefreshReactiveResume}
          onSelect={onSelectReactiveResume}
          onDisconnect={onDisconnectReactiveResume}
        />

        <div className="learning-note">
          <span className="company-mark dark"><BrainCircuit size={14} /></span>
          <b>Feedback is stored per job and used when regenerating that job's pack.</b>
        </div>
      </div>

      {isDirty ? (
        <footer className="sticky-submit">
          {saveError ? <span className="save-error">{saveError}</span> : null}
          <button className="save-preferences" type="button" onClick={() => void save()} disabled={saving}>
            <Save size={16} /> {saving ? "SAVING" : "SAVE"}
          </button>
          <button
            className="discard-preferences"
            type="button"
            onClick={() => { setDraft(baseline); setSaveError(null); }}
            disabled={saving}
            aria-label="Discard unsaved preference changes"
          >
            <X size={16} />
          </button>
        </footer>
      ) : null}
    </article>
  );
}

function ReactiveResumePanel({
  status,
  onConnect,
  onRefresh,
  onSelect,
  onDisconnect
}: {
  status: ReactiveResumeStatus | null;
  onConnect: (apiKey: string, baseUrl: string) => Promise<ReactiveResumeStatus>;
  onRefresh: () => Promise<ReactiveResumeStatus>;
  onSelect: (resumeId: string) => Promise<ReactiveResumeStatus>;
  onDisconnect: () => Promise<ReactiveResumeStatus>;
}) {
  const [apiKey, setApiKey] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState(status?.base_url ?? "https://rxresu.me/api/openapi");
  const [busy, setBusy] = React.useState(false);
  const [panelError, setPanelError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (status?.base_url) setBaseUrl(status.base_url);
  }, [status?.base_url]);

  async function run(action: () => Promise<ReactiveResumeStatus>, clearKey = false) {
    setBusy(true);
    setPanelError(null);
    try {
      await action();
      if (clearKey) setApiKey("");
    } catch (reason) {
      setPanelError(messageFrom(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="pref-section reactive-resume-panel" id="reactive-resume">
      <div className="integration-heading">
        <div>
          <p className="eyebrow">CV INTEGRATION</p>
          <h2>Reactive Resume</h2>
        </div>
        <span className={`integration-state ${status?.verified ? "ready" : ""}`}>
          {status?.reference ? "READY" : status?.configured ? "CONNECTED" : "SETUP"}
        </span>
      </div>

      {!status ? <p className="operations-loading">Loading connection status...</p> : !status.encryption_ready ? (
        <div className="integration-warning">
          <LockKeyhole size={16} /> Server secret storage must be configured before an API key can be accepted.
        </div>
      ) : !status.configured ? (
        <form
          className="integration-connect"
          onSubmit={(event) => {
            event.preventDefault();
            void run(() => onConnect(apiKey, baseUrl), true);
          }}
        >
          <p>Connect once. The API key is encrypted and never returned to this screen or to agents.</p>
          <label>
            <span>OPENAPI URL</span>
            <input type="url" required value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} disabled={busy} />
          </label>
          <label>
            <span>API KEY</span>
            <input
              type="password"
              autoComplete="off"
              required
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              disabled={busy}
              placeholder="Paste once"
            />
          </label>
          <button className="integration-primary" type="submit" disabled={busy || !apiKey.trim()}>
            <LockKeyhole size={15} /> {busy ? "VERIFYING" : "CONNECT & VERIFY"}
          </button>
        </form>
      ) : (
        <div className="integration-ready">
          {status.reference ? (
            <div className="reference-card">
              <span className="reference-icon"><FileText size={20} /></span>
              <span>
                <small>REFERENCE CV</small>
                <b>{status.reference.name}</b>
                <em>{status.reference.template ?? "Template unavailable"}{status.reference.updated_at ? ` · Updated ${formatDateTime(status.reference.updated_at)}` : ""}</em>
              </span>
            </div>
          ) : (
            <div className="integration-warning">Connected. Choose the canonical tailoring reference below.</div>
          )}

          <label className="reference-select">
            <span>TAILORING REFERENCE</span>
            <select
              value={status.reference?.id ?? ""}
              onChange={(event) => void run(() => onSelect(event.target.value))}
              disabled={busy}
            >
              <option value="">Choose a reference CV</option>
              {status.available_resumes.map((resume) => (
                <option key={resume.id} value={resume.id} disabled={resume.historical_source}>
                  {resume.name}{resume.historical_source ? " — historical source" : ""}
                </option>
              ))}
            </select>
          </label>

          {status.reference ? (
            <div className="reference-actions">
              <a href="/api/integrations/reactive-resume/reference.pdf" target="_blank" rel="noreferrer">
                <ExternalLink size={15} /> VIEW
              </a>
              <a href="/api/integrations/reactive-resume/reference.pdf?download=true">
                <FileText size={15} /> DOWNLOAD
              </a>
            </div>
          ) : null}

          <p className="immutable-note">Job-specific CVs are created as duplicates. This reference is never edited in place.</p>
          <div className="integration-secondary-actions">
            <button type="button" onClick={() => void run(onRefresh)} disabled={busy}>
              <RefreshCw size={14} /> REFRESH
            </button>
            <button type="button" onClick={() => void run(onDisconnect)} disabled={busy}>
              <Unplug size={14} /> DISCONNECT
            </button>
          </div>
        </div>
      )}

      {status?.last_error || panelError ? <p className="integration-error">{panelError ?? status?.last_error}</p> : null}
    </section>
  );
}

function DiscoveryOperationsPanel({
  operations,
  running,
  message,
  error,
  onRun,
  onSave
}: {
  operations: DiscoveryOperations | null;
  running: boolean;
  message: string | null;
  error: string | null;
  onRun: () => Promise<void>;
  onSave: (schedule: DiscoveryOperations["schedule"], sourcesEnabled: Record<string, boolean>) => Promise<DiscoveryOperations>;
}) {
  const [schedule, setSchedule] = React.useState<DiscoveryOperations["schedule"] | null>(operations?.schedule ?? null);
  const [sourcesEnabled, setSourcesEnabled] = React.useState<Record<string, boolean>>(
    Object.fromEntries((operations?.sources ?? []).map((source) => [source.id, source.enabled]))
  );
  const [saving, setSaving] = React.useState(false);
  const [configError, setConfigError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!operations) return;
    setSchedule(operations.schedule);
    setSourcesEnabled(Object.fromEntries(operations.sources.map((source) => [source.id, source.enabled])));
    setConfigError(null);
  }, [operations]);

  if (!operations || !schedule) return <div className="operations-loading">Loading discovery configuration…</div>;
  const baselineSources = Object.fromEntries(operations.sources.map((source) => [source.id, source.enabled]));
  const dirty = JSON.stringify(schedule) !== JSON.stringify(operations.schedule)
    || JSON.stringify(sourcesEnabled) !== JSON.stringify(baselineSources);

  async function saveConfig() {
    if (!schedule) return;
    setSaving(true);
    setConfigError(null);
    try {
      await onSave(schedule, sourcesEnabled);
    } catch (reason) {
      setConfigError(messageFrom(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="discovery-operations">
      <div className="operations-summary">
        <div>
          <span>NEXT SEARCH</span>
          <strong>{operations.next_run_at ? formatDateTime(operations.next_run_at) : "PAUSED"}</strong>
        </div>
        <div>
          <span>LAST SEARCH</span>
          <strong>{operations.last_run ? formatDateTime(operations.last_run.started_at) : "NOT RUN"}</strong>
        </div>
      </div>

      <button className="search-now" type="button" disabled={running || dirty} onClick={() => void onRun()}>
        <ScanSearch size={16} /> {running ? "SEARCHING…" : "SEARCH NOW"}
      </button>
      {message ? <p className="operation-message">{message}</p> : null}
      {error ? <p className="operation-message error">{error}</p> : null}
      {dirty ? <p className="operation-message">Save schedule and source changes before Search Now.</p> : null}

      <div className="operation-block">
        <div className="operation-heading">
          <div><b>Search times</b><small>{schedule.timezone}</small></div>
          <button
            type="button"
            className={schedule.enabled ? "mini-toggle on" : "mini-toggle"}
            onClick={() => setSchedule({ ...schedule, enabled: !schedule.enabled })}
            aria-label={schedule.enabled ? "Pause scheduled discovery" : "Enable scheduled discovery"}
          ><i /></button>
        </div>
        <p className="schedule-explainer">
          Every selected time runs discovery, then only jobs with complete extraction and ready packs can appear in Inbox.
        </p>
        <div className="schedule-times">
          {schedule.times.map((time, index) => (
            <label key={`${index}-${time}`}>
              <span>TIME {index + 1}</span>
              <input
                type="time"
                value={time}
                onChange={(event) => setSchedule({ ...schedule, times: schedule.times.map((item, itemIndex) => itemIndex === index ? event.target.value : item) })}
              />
            </label>
          ))}
        </div>
      </div>

      <div className="operation-block">
        <div className="operation-heading"><div><b>Sources</b><small>Only available sources can be enabled.</small></div></div>
        <div className="source-list">
          {operations.sources.map((source) => (
            <button
              type="button"
              className={sourcesEnabled[source.id] ? "source-row selected" : "source-row"}
              disabled={source.status !== "available"}
              key={source.id}
              onClick={() => setSourcesEnabled({ ...sourcesEnabled, [source.id]: !sourcesEnabled[source.id] })}
            >
              <span>{sourcesEnabled[source.id] ? <Check size={12} /> : null}</span>
              <span><b>{source.label}</b><small>{source.detail}</small></span>
              <em>{source.status.replace("_", " ")}</em>
            </button>
          ))}
        </div>
      </div>

      <div className="operation-block query-preview">
        <div className="operation-heading"><div><b>Search plan</b><small>Exact phrases used by Search Now and scheduled scans, generated from saved roles and locations.</small></div><em>{operations.generated_queries.length}</em></div>
        {operations.generated_queries.slice(0, 4).map((query) => <span key={query}>{query}</span>)}
        {operations.generated_queries.length > 4 ? <small>+{operations.generated_queries.length - 4} more searches</small> : null}
      </div>

      {dirty || configError ? (
        <div className="operations-save">
          {configError ? <small>{configError}</small> : null}
          <button type="button" disabled={saving} onClick={() => void saveConfig()}><Save size={14} /> {saving ? "SAVING" : "SAVE SCHEDULE"}</button>
        </div>
      ) : null}

      <div className="operation-block run-history">
        <div className="operation-heading"><div><b>Execution history</b><small>Recent discovery runs with pack counts and failure details.</small></div></div>
        {operations.recent_runs.slice(0, 5).map((run) => (
          <div className="run-row" key={run.id}>
            <span className={`run-state ${run.status}`} />
            <span>
              <b>{run.status === "succeeded" ? `${run.unique_count} found → ${run.jobs_added} new jobs → ${run.packs_prepared} packs` : run.status}</b>
              <small>{run.trigger === "manual" ? "Search now" : "Scheduled"} · {formatDateTime(run.started_at)}{run.error ? ` · ${run.error}` : ""}</small>
            </span>
          </div>
        ))}
        {operations.recent_runs.length === 0 ? <p className="operations-empty">No searches have run yet.</p> : null}
      </div>
    </div>
  );
}

function PipelineView({ jobs, onSelect }: { jobs: JobListItem[]; onSelect: (id: string) => void }) {
  const stages = [
    { label: "Inbox", note: "Ready and unreviewed", jobs: jobs.filter((job) => job.status === "inbox" && job.pack_status === "ready") },
    { label: "Needs attention", note: "Pack failed", jobs: jobs.filter((job) => job.status === "inbox" && job.pack_status === "failed") },
    { label: "Review", note: "Changes requested", jobs: jobs.filter((job) => job.status === "maybe") },
    { label: "Saved", note: "Approved packs", jobs: jobs.filter((job) => job.status === "good") },
    { label: "Passed", note: "Declined roles", jobs: jobs.filter((job) => job.status === "bad") }
  ];

  return (
    <article className="pipeline-screen">
      <header className="pipeline-hero">
        <p className="micro">APPLICATION FLOW</p>
        <h1>Momentum</h1>
        <p>Every role has one persisted review state.</p>
        <div className="pipeline-stats">
          {stages.map((stage, index) => (
            <div className={index === 0 ? "pipeline-stat dark" : "pipeline-stat"} key={stage.label}>
              <strong>{String(stage.jobs.length).padStart(2, "0")}</strong>
              <span>{stage.label.toUpperCase()}</span>
            </div>
          ))}
        </div>
      </header>

      <div className="screen-body pipeline-body">
        {stages.map((stage) => (
          <section className="pipeline-stage" key={stage.label}>
            <div className="section-head">
              <h2>{stage.label}</h2>
              <span>{stage.jobs.length} · {stage.note.toUpperCase()}</span>
            </div>
            <div className="pipeline-list">
              {stage.jobs.map((job) => (
                <button type="button" className="pipeline-row" key={job.id} onClick={() => onSelect(job.id)}>
                  <span className="company-mark dark">{initial(job.company)}</span>
                  <span>
                    <b>{job.title}</b>
                    <small>{job.company.toUpperCase()} · {job.score ?? "--"}% · {shortSalary(job)}</small>
                  </span>
                  <ArrowUpRight size={16} />
                </button>
              ))}
              {stage.jobs.length === 0 ? <p className="pipeline-empty">No roles here.</p> : null}
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}

function ActivityView({
  items,
  jobs,
  onOpenJob,
  onOpenSettings
}: {
  items: ActivityItem[];
  jobs: JobListItem[];
  onOpenJob: (id: string) => void;
  onOpenSettings: () => void;
}) {
  const packCount = jobs.filter((job) => job.pack_status === "ready").length;
  const likedCount = jobs.filter((job) => job.status === "good").length;
  const groups = groupActivitiesByDay(collapseSystemActivities(items));
  return (
    <article className="activity-screen">
      <header className="activity-hero">
        <div className="hero-top">
          <div>
            <p className="micro">AGENT LOG</p>
            <h1>While you were away</h1>
          </div>
          <button className="round-action black" type="button" onClick={onOpenSettings} aria-label="Open search automation settings">
            <Settings2 size={18} />
          </button>
        </div>
        <div className="activity-stats">
          <Stat label="FOUND" value={String(jobs.length).padStart(2, "0")} dark />
          <Stat label="PACKS" value={String(packCount).padStart(2, "0")} />
          <Stat label="LIKED" value={String(likedCount).padStart(2, "0")} />
        </div>
      </header>

      <div className="screen-body activity-body">
        {groups.map((group) => (
          <React.Fragment key={group.key}>
            <div className="section-head">
              <h2>{group.label}</h2>
              <span>{new Intl.DateTimeFormat(undefined, { weekday: "short", day: "2-digit", month: "short" }).format(group.date).toUpperCase()}</span>
            </div>
            <div className="activity-list">
              {group.items.map((item) => {
                const content = (
                  <>
                  <span className="activity-icon"><ActivityIcon kind={item.kind} /></span>
                  <div>
                    <div className="activity-item-top">
                      <strong>{item.title}</strong>
                      <time>{formatTime(item.created_at)}</time>
                    </div>
                    <p>{item.body}</p>
                  </div>
                  {item.job_id ? <ArrowUpRight size={14} /> : null}
                  </>
                );
                return item.job_id ? (
                  <button className="activity-item" type="button" key={item.id} onClick={() => onOpenJob(item.job_id as string)}>
                    {content}
                  </button>
                ) : (
                  <div className="activity-item" key={item.id}>{content}</div>
                );
              })}
            </div>
          </React.Fragment>
        ))}
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

function SourceDescription({ job }: { job: JobDetail }) {
  const description = (job.extracted_description || job.raw_description || "").trim();
  return (
    <section className="content-section source-description">
      <h2><FileText size={15} />Source description</h2>
      {description ? <p>{description}</p> : <p className="muted">No source description was extracted.</p>}
    </section>
  );
}

function TagEditor({ label, placeholder = "Add another…", values, onChange }: { label: string; placeholder?: string; values: string[]; onChange: (values: string[]) => void }) {
  const [input, setInput] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (document.activeElement !== inputRef.current) return;
    window.requestAnimationFrame(() => inputRef.current?.closest(".tag-editor")?.scrollIntoView({ block: "center" }));
  }, [values.length]);

  function addTags(candidates: string[]) {
    const next = [...values];
    for (const candidate of candidates) {
      const value = candidate.trim();
      if (value && !next.some((existing) => existing.toLocaleLowerCase() === value.toLocaleLowerCase())) next.push(value);
    }
    onChange(next);
  }

  function commit() {
    if (!input.trim()) return;
    addTags(input.split(/[;,]/));
    setInput("");
  }

  return (
    <div className="tag-editor">
      <span className="tag-editor-label">{label.toUpperCase()}</span>
      <div className="tag-editor-box" onClick={(event) => (event.currentTarget.querySelector("input") as HTMLInputElement | null)?.focus()}>
        {values.map((value) => (
          <span className="keyword-tag" key={value}>
            {value}
            <button type="button" onClick={() => onChange(values.filter((item) => item !== value))} aria-label={`Remove ${value}`}>
              <X size={11} />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          aria-label={`Add ${label.toLowerCase()}`}
          placeholder={values.length ? "Add another…" : placeholder}
          value={input}
          onChange={(event) => {
            const next = event.target.value;
            if (/[;,]/.test(next)) {
              const parts = next.split(/[;,]/);
              addTags(parts.slice(0, -1));
              setInput(parts.at(-1) ?? "");
            } else {
              setInput(next);
            }
          }}
          onBlur={commit}
          onFocus={(event) => {
            const editor = event.currentTarget.closest(".tag-editor");
            window.requestAnimationFrame(() => editor?.scrollIntoView({ block: "center" }));
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ";" || event.key === ",") {
              event.preventDefault();
              commit();
            } else if (event.key === "Backspace" && !input && values.length) {
              onChange(values.slice(0, -1));
            }
          }}
        />
      </div>
      <small>Press Enter, comma, or semicolon to create a tag.</small>
    </div>
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

function PackRow({
  number,
  title,
  meta,
  href,
  download = false
}: {
  number: string;
  title: string;
  meta: string;
  href?: string;
  download?: boolean;
}) {
  const content = (
    <>
      <span>{number}</span>
      <div>
        <b>{title}</b>
        <small>{meta}</small>
      </div>
      <ArrowUpRight size={16} />
    </>
  );
  return href ? (
    <a className="pack-row" href={href} target={download ? undefined : "_blank"} rel={download ? undefined : "noreferrer"} download={download}>
      {content}
    </a>
  ) : (
    <div className="pack-row">{content}</div>
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
        <NavButton icon={<Columns3 />} label="Pipeline" active={activeView === "pipeline"} onClick={() => onNavigate("pipeline")} />
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

function PulseBars({ days = [] }: { days?: Array<{ date: string; count: number }> }) {
  const fallback = [3, 5, 8, 4, 7, 6, 8, 3, 5, 8, 6, 4, 7, 8, 5, 3, 6, 8, 4, 7];
  const maximum = Math.max(1, ...days.map((day) => day.count));
  return (
    <div
      className="pulse-bars"
      aria-hidden={days.length ? undefined : true}
      aria-label={days.length ? "Jobs discovered each day over the last 20 days" : undefined}
      role={days.length ? "img" : undefined}
    >
      {(days.length ? days : fallback.map((height, index) => ({ date: String(index), count: height }))).map((day) => {
        const height = days.length ? 3 + Math.round((day.count / maximum) * 5) : day.count;
        return <span key={day.date} title={days.length ? `${day.date}: ${day.count} found` : undefined} style={{ height }} className={day.count / maximum >= 0.7 ? "hot" : ""} />;
      })}
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

function groupActivitiesByDay(items: ActivityItem[]) {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const dateKey = (date: Date) => `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
  const todayKey = dateKey(today);
  const yesterdayKey = dateKey(yesterday);
  const groups = new Map<string, { key: string; label: string; date: Date; items: ActivityItem[] }>();

  for (const item of items) {
    const date = new Date(item.created_at);
    const key = dateKey(date);
    const existing = groups.get(key);
    if (existing) {
      existing.items.push(item);
      continue;
    }
    groups.set(key, {
      key,
      label: key === todayKey
        ? "Today"
        : key === yesterdayKey
          ? "Yesterday"
          : new Intl.DateTimeFormat(undefined, { weekday: "long" }).format(date),
      date,
      items: [item]
    });
  }

  return [...groups.values()];
}

function collapseSystemActivities(items: ActivityItem[]) {
  const collapsed: ActivityItem[] = [];
  for (const item of items) {
    const previous = collapsed.at(-1);
    if (
      previous
      && !item.job_id
      && !previous.job_id
      && item.kind === previous.kind
      && item.title === previous.title
    ) {
      collapsed[collapsed.length - 1] = { ...previous, body: `${previous.body} · ${item.body}` };
    } else {
      collapsed.push(item);
    }
  }
  return collapsed;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)).toUpperCase();
}

function formatFoundDate(value: string, includeYear = false) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Vienna",
    day: "numeric",
    month: "short",
    ...(includeYear ? { year: "numeric" as const } : {})
  }).format(new Date(value)).toUpperCase();
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
  if (filter === "low") return jobs.filter((job) => job.status === "bad").length;
  if (filter === "reviewed") return jobs.filter((job) => job.status === "good").length;
  return jobs.length;
}

function formatCurrencyValue(value: number, currency: string) {
  if (!value) return `${currency} --`;
  return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0, notation: "compact" }).format(value);
}

function salaryPercent(value: number) {
  if (!value) return 0;
  return Math.min(100, Math.max(0, ((value - 30000) / 90000) * 100));
}

function preferredRules(preferences: Preferences) {
  return preferences.hard_rules.filter((rule) => !isInternalPolicyRule(rule)).slice(0, 5);
}

function ruleMeta(rule: string) {
  if (/home.?office/i.test(rule)) return "Required work setup";
  if (/german/i.test(rule)) return "Preferred language environment";
  if (/vienna|wien/i.test(rule)) return "Required commute area";
  return "Required condition";
}

function isInternalPolicyRule(rule: string) {
  return /normally reject below|application.*approval|manual submission|recruiter contact/i.test(rule);
}

function humanizeRule(rule: string) {
  return rule.includes("_") ? humanize(rule) : rule;
}

function humanizeRole(value: string) {
  const trimmed = value.trim();
  if (!trimmed.includes("_")) return trimmed;
  const acronyms: Record<string, string> = { ai: "AI", it: "IT", rpa: "RPA", ui: "UI", ux: "UX", qa: "QA" };
  const words = trimmed.split("_").filter(Boolean).map((word) => acronyms[word.toLowerCase()] ?? word.toLowerCase());
  if (!words.length) return trimmed;
  words[0] = acronyms[words[0].toLowerCase()] ?? `${words[0].charAt(0).toUpperCase()}${words[0].slice(1)}`;
  return words.join(" ");
}

function normalizeEditablePreferences(preferences: Preferences): Preferences {
  const targetMin = preferences.salary_target_min ?? preferences.acceptable_salary_min ?? null;
  return {
    ...preferences,
    salary_target_min: targetMin,
    acceptable_salary_min: targetMin,
    role_families: Array.from(new Set(preferences.role_families.map(humanizeRole).filter(Boolean))),
    priority_role_families: Array.from(new Set((preferences.priority_role_families ?? []).map(humanizeRole).filter(Boolean))),
    hard_rules: preferences.hard_rules.filter((rule) => !isInternalPolicyRule(rule)),
    manual_submission_only: true
  };
}

function preferenceFingerprint(preferences: Preferences) {
  const { updated_at: _updatedAt, ...comparable } = preferences;
  return JSON.stringify(comparable);
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

if (!document.documentElement.dataset.jobflowGesturesLocked) {
  const preventGesture = (event: Event) => event.preventDefault();
  document.addEventListener(
    "touchmove",
    (event) => {
      if (event.touches.length > 1) event.preventDefault();
    },
    { passive: false }
  );
  for (const eventName of ["gesturestart", "gesturechange", "gestureend"]) {
    document.addEventListener(eventName, preventGesture, { passive: false });
  }
  document.documentElement.dataset.jobflowGesturesLocked = "true";
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
