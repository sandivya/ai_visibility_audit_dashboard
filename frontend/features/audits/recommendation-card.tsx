"use client";

import { useToast } from "@/components/toast";
import { useUpdateRecommendation } from "@/features/audits/hooks";
import type { Recommendation, RecommendationStatus } from "@/lib/types";

const recommendationStatuses: RecommendationStatus[] = [
  "open",
  "in_progress",
  "completed",
  "dismissed",
];

type RecommendationCardProps = {
  auditId: string;
  item: Recommendation;
  index: number;
  canWrite: boolean;
  evidenceHref?: string;
};

export function RecommendationCard({
  auditId,
  item,
  index,
  canWrite,
  evidenceHref,
}: RecommendationCardProps) {
  const update = useUpdateRecommendation(auditId);
  const { showToast } = useToast();
  const saveStateId = `recommendation-save-${item.id}`;

  return (
    <article className="result-card recommendation">
      <div className="number" aria-hidden="true">
        {String(index + 1).padStart(2, "0")}
      </div>
      <div className="recommendation-body">
        <div className="recommendation-toolbar">
          <span className={`tag ${item.priority}`}>{item.priority} priority</span>
          <div className="recommendation-control">
            <label className="sr-only" htmlFor={`recommendation-${item.id}`}>
              Status for {item.title}
            </label>
            <select
              id={`recommendation-${item.id}`}
              value={item.status}
              disabled={!canWrite || update.isPending}
              aria-describedby={
                !canWrite
                  ? "recommendations-readonly"
                  : update.isPending || update.error
                    ? saveStateId
                    : undefined
              }
              onChange={(event) =>
                update.mutate(
                  { recommendationId: item.id, status: event.target.value as RecommendationStatus },
                  {
                    onSuccess: () =>
                      showToast({
                        title: "Recommendation updated",
                        description: item.title,
                        tone: "success",
                      }),
                  },
                )
              }
            >
              {recommendationStatuses.map((status) => (
                <option key={status} value={status}>
                  {status.replaceAll("_", " ")}
                </option>
              ))}
            </select>
            {update.isPending && (
              <span className="save-state" data-state="saving" id={saveStateId} role="status">
                Saving…
              </span>
            )}
            {update.error && (
              <span className="field-error" id={saveStateId} role="alert">
                Update failed. Try again.
              </span>
            )}
          </div>
        </div>
        <h3>{item.title}</h3>
        <p>{item.description}</p>
        {evidenceHref && (
          <a className="card-action" href={evidenceHref}>
            Review diagnostic evidence
          </a>
        )}
      </div>
    </article>
  );
}
