/**
 * The safe import, as the browser calls it — PLAN §5's seven steps.
 *
 * One function per step, because each step is a place a person stops and looks. A single
 * `importFile()` that did all of it would be shorter and would remove the review the whole design
 * exists for.
 *
 * The idempotency keys are derived from the import and the version being acted on, so a retry
 * after a dropped connection resumes rather than starting a second import of the same file.
 */

import { request } from "./client";
import type { ImportPreview, ImportSummary } from "./contract";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001/api/v1";

/**
 * Upload the file — steps 1 and 2.
 *
 * Sent as multipart rather than through `request()`, which is JSON-only. The cookie and the
 * idempotency header are set here by hand for the same reason, and nowhere else: this is the
 * only multipart call in the product.
 */
export async function uploadImport(
  file: File,
  sheetName?: string,
): Promise<ImportSummary> {
  const form = new FormData();
  form.append("file", file);
  if (sheetName) form.append("sheet_name", sheetName);

  const response = await fetch(`${BASE_URL}/hierarchy/imports`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      //  Derived from the file itself, so picking the same file twice after a failed upload
      //  resumes the first import instead of creating a second.
      "Idempotency-Key": `import:${file.name}:${file.size}:${file.lastModified}`,
    },
    body: form,
  });

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    //  The server's own message, never a generic one: it says which column or which row.
    throw new Error(
      (body as { message?: string } | null)?.message ??
        `The import could not be read (${response.status}).`,
    );
  }
  return body as ImportSummary;
}

/** Step 3 — ask a model about the headings nothing matched. Only those. */
export function proposeMapping(importId: string): Promise<ImportSummary> {
  return request<ImportSummary>(`/hierarchy/imports/${importId}/propose`, {
    method: "POST",
    body: {},
    idempotencyKey: `import-propose:${importId}`,
  });
}

/** Step 4 — the mapping the person confirmed. Every row is restaged against it. */
export function setMapping(
  importId: string,
  mapping: Record<string, string>,
  expectedVersion: number,
): Promise<ImportSummary> {
  return request<ImportSummary>(`/hierarchy/imports/${importId}/mapping`, {
    method: "PUT",
    body: { mapping, expected_version: expectedVersion },
    idempotencyKey: `import-mapping:${importId}:v${expectedVersion}`,
    expectedVersion,
  });
}

/** Step 5 — the staged rows, their errors, and the tree they would build. */
export function fetchPreview(
  importId: string,
  signal?: AbortSignal,
): Promise<ImportPreview> {
  return request<ImportPreview>(
    `/hierarchy/imports/${importId}`,
    signal ? { signal } : {},
  );
}

/** Step 7 — apply it, atomically. */
export function applyImport(
  importId: string,
  expectedVersion: number,
): Promise<ImportSummary> {
  return request<ImportSummary>(`/hierarchy/imports/${importId}/apply`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `import-apply:${importId}:v${expectedVersion}`,
    expectedVersion,
  });
}
