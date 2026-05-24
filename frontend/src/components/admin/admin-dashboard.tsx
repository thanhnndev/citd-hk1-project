"use client";

import { useEffect, useState } from "react";
import { Loader2, Database, Activity, BarChart3, Scale } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import {
  getCorpusStats,
  triggerEval,
  getTracesStatus,
  getFairnessSummary,
  type CorpusStatsResponse,
  type TracesStatusResponse,
  type FairnessSummaryResponse,
} from "@/lib/admin-api";

/* ── Labels interface (passed from server for i18n) ───────── */

export interface AdminDashboardLabels {
  title: string;
  corpus: {
    title: string;
    noData: string;
  };
  evaluation: {
    title: string;
    triggerButton: string;
    triggering: string;
    lastVerdict: string;
    noResults: string;
    error: string;
  };
  traces: {
    title: string;
    enabled: string;
    disabled: string;
    noData: string;
    error: string;
  };
  fairness: {
    title: string;
    totalAudits: string;
    meanLocalFactor: string;
    noData: string;
    error: string;
  };
  fetchError: string;
}

interface AdminDashboardProps {
  labels: AdminDashboardLabels;
}

function StatSkeleton() {
  return (
    <div className="animate-pulse space-y-2">
      <div className="h-4 w-20 rounded bg-muted" />
      <div className="h-8 w-16 rounded bg-muted" />
      <div className="h-3 w-32 rounded bg-muted" />
    </div>
  );
}

export function AdminDashboard({ labels }: AdminDashboardProps) {
  // Corpus
  const [corpus, setCorpus] = useState<CorpusStatsResponse | null>(null);
  const [corpusLoading, setCorpusLoading] = useState(true);
  const [corpusError, setCorpusError] = useState<string | null>(null);

  // Evaluation
  const [evalVerdict, setEvalVerdict] = useState<string | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalError, setEvalError] = useState<string | null>(null);

  // Traces
  const [traces, setTraces] = useState<TracesStatusResponse | null>(null);
  const [tracesError, setTracesError] = useState<string | null>(null);

  // Fairness
  const [fairness, setFairness] = useState<FairnessSummaryResponse | null>(null);
  const [fairnessError, setFairnessError] = useState<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();

    async function fetchAll() {
      // Corpus stats
      try {
        const stats = await getCorpusStats();
        if (!abort.signal.aborted) setCorpus(stats);
      } catch (e) {
        if (!abort.signal.aborted)
          setCorpusError(e instanceof Error ? e.message : labels.fetchError);
      } finally {
        if (!abort.signal.aborted) setCorpusLoading(false);
      }

      // Traces status
      try {
        const t = await getTracesStatus();
        if (!abort.signal.aborted) setTraces(t);
      } catch (e) {
        if (!abort.signal.aborted)
          setTracesError(e instanceof Error ? e.message : labels.traces.error);
      }

      // Fairness summary
      try {
        const f = await getFairnessSummary();
        if (!abort.signal.aborted) setFairness(f);
      } catch (e) {
        if (!abort.signal.aborted)
          setFairnessError(
            e instanceof Error ? e.message : labels.fairness.error,
          );
      }
    }

    fetchAll();
    return () => abort.abort();
  }, [labels.fetchError, labels.traces.error, labels.fairness.error]);

  const handleTriggerEval = async () => {
    setEvalLoading(true);
    setEvalError(null);
    try {
      const result = await triggerEval();
      setEvalVerdict(result.verdict);
    } catch (e) {
      setEvalError(e instanceof Error ? e.message : labels.evaluation.error);
    } finally {
      setEvalLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">{labels.title}</h1>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {/* ── Corpus Stats Card ─────────────────────────────── */}
        <Card>
          <CardHeader className="flex flex-row items-center gap-3 pb-2">
            <Database className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">
              {labels.corpus.title}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {corpusLoading ? (
              <StatSkeleton />
            ) : corpusError ? (
              <p className="text-sm text-destructive">{corpusError}</p>
            ) : corpus ? (
              <div className="space-y-2">
                <p className="text-2xl font-bold">{corpus.total_docs}</p>
                <p className="text-xs text-muted-foreground">
                  {corpus.total_chunks} chunks
                </p>
                {Object.entries(corpus.language_distribution).map(
                  ([lang, count]) => (
                    <div
                      key={lang}
                      className="flex items-center justify-between text-xs"
                    >
                      <Badge variant="outline" className="uppercase">
                        {lang}
                      </Badge>
                      <span className="text-muted-foreground">{count}</span>
                    </div>
                  ),
                )}
                <p className="text-xs text-muted-foreground">
                  BM25 vocab: {corpus.bm25_vocab_size}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {labels.corpus.noData}
              </p>
            )}
          </CardContent>
        </Card>

        {/* ── Evaluation Card ───────────────────────────────── */}
        <Card>
          <CardHeader className="flex flex-row items-center gap-3 pb-2">
            <Activity className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">
              {labels.evaluation.title}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {evalError ? (
              <p className="text-sm text-destructive">{evalError}</p>
            ) : (
              <div className="space-y-3">
                <Button
                  onClick={handleTriggerEval}
                  disabled={evalLoading}
                  size="sm"
                  className="w-full"
                >
                  {evalLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      {labels.evaluation.triggering}
                    </>
                  ) : (
                    labels.evaluation.triggerButton
                  )}
                </Button>
                {evalVerdict && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">
                      {labels.evaluation.lastVerdict}
                    </p>
                    <Badge
                      variant={
                        evalVerdict === "completed" ? "success" : "destructive"
                      }
                    >
                      {evalVerdict}
                    </Badge>
                  </div>
                )}
                {!evalVerdict && (
                  <p className="text-xs text-muted-foreground">
                    {labels.evaluation.noResults}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Traces Card ───────────────────────────────────── */}
        <Card>
          <CardHeader className="flex flex-row items-center gap-3 pb-2">
            <BarChart3 className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">
              {labels.traces.title}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {tracesError ? (
              <p className="text-sm text-destructive">{tracesError}</p>
            ) : traces ? (
              <div className="space-y-2">
                <Badge
                  variant={traces.langfuse_enabled ? "success" : "destructive"}
                >
                  {traces.langfuse_enabled
                    ? labels.traces.enabled
                    : labels.traces.disabled}
                </Badge>
                {traces.host && (
                  <p className="truncate text-xs text-muted-foreground">
                    {traces.host}
                  </p>
                )}
                <p className="text-xs text-muted-foreground">
                  {traces.message}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {labels.traces.noData}
              </p>
            )}
          </CardContent>
        </Card>

        {/* ── Fairness Card ─────────────────────────────────── */}
        <Card>
          <CardHeader className="flex flex-row items-center gap-3 pb-2">
            <Scale className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">
              {labels.fairness.title}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {fairnessError ? (
              <p className="text-sm text-destructive">{fairnessError}</p>
            ) : fairness ? (
              <div className="space-y-2">
                <p className="text-2xl font-bold">
                  {fairness.total_audits}
                </p>
                <p className="text-xs text-muted-foreground">
                  {labels.fairness.totalAudits}
                </p>
                {fairness.local_factor_distribution &&
                  "mean" in fairness.local_factor_distribution && (
                    <p className="text-xs text-muted-foreground">
                      {labels.fairness.meanLocalFactor}:{" "}
                      {(fairness.local_factor_distribution.mean as number)?.toFixed(3)}
                    </p>
                  )}
                {fairness.latest_timestamp && (
                  <p className="text-xs text-muted-foreground">
                    {new Date(fairness.latest_timestamp).toLocaleString()}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {labels.fairness.noData}
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
