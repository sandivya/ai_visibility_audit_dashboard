const DOMAIN = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

export function normalizeDomain(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/$/, "");
}

export function isValidDomain(value: string) {
  return DOMAIN.test(normalizeDomain(value));
}

export function parseCompetitors(value: string) {
  return [...new Set(value.split(",").map(normalizeDomain).filter(Boolean))];
}

export type ProjectDraft = { name: string; domain: string; competitors: string[] };
export type ProjectFormErrors = Partial<Record<"name" | "domain" | "competitors", string>>;

export function validateProjectDraft(input: { name: string; domain: string; competitors: string }) {
  const name = input.name.trim();
  const domain = normalizeDomain(input.domain);
  const competitors = parseCompetitors(input.competitors).filter(
    (competitor) => competitor !== domain,
  );
  const invalidCompetitor = competitors.find((competitor) => !isValidDomain(competitor));
  const errors: ProjectFormErrors = {};

  if (!name) errors.name = "Enter a project name.";
  else if (name.length > 120) errors.name = "Project names must be 120 characters or fewer.";
  if (!isValidDomain(domain)) errors.domain = "Enter a valid domain such as example.com.";
  if (invalidCompetitor)
    errors.competitors = `${invalidCompetitor} is not a valid competitor domain.`;
  else if (competitors.length > 10) errors.competitors = "Add no more than 10 competitors.";

  return {
    draft:
      Object.keys(errors).length === 0
        ? ({ name, domain, competitors } satisfies ProjectDraft)
        : null,
    errors,
  };
}
