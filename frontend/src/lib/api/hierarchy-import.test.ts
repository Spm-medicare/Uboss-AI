import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { uploadImport } from "@/lib/api/hierarchy-import";

/**
 * The upload's idempotency key.
 *
 * `CLAUDE.md`: *"Idempotency keys are derived from the logical operation, never
 * `crypto.randomUUID()` per call — a retry must reuse the key."* This is the one call in the
 * product that builds its own request rather than going through `request()`, so the rule is not
 * enforced for it by anything else — which is exactly why it is pinned here.
 *
 * The failure this prevents is concrete: a dropped connection on a 4 MB upload, the person
 * presses the button again, and the workspace ends up with two imports of one file.
 */
describe("uploadImport", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** The idempotency header from each call, in order. */
  function keysSent(mock: typeof fetchMock): string[] {
    return mock.mock.calls.map((call) => {
      const headers = (call[1] as RequestInit).headers as Record<string, string>;
      return headers["Idempotency-Key"] ?? "";
    });
  }

  function fileNamed(name: string): File {
    const file = new File(["Department\nAcme\n"], name, { type: "text/csv" });
    //  `lastModified` is part of the key, and jsdom's File does not let it be set through the
    //  constructor options in every version. Fixed here so the assertion is about the key's
    //  shape rather than about the clock.
    Object.defineProperty(file, "lastModified", { value: 1_700_000_000_000 });
    return file;
  }

  it("derives its key from the file, so a retry reuses it", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ id: "abc" }),
    });

    const file = fileNamed("structure.csv");
    await uploadImport(file);
    await uploadImport(file);

    const [first, second] = keysSent(fetchMock);
    expect(first).toBe(second);
    expect(first).toContain("structure.csv");
  });

  it("gives a different key to a different file", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ id: "abc" }),
    });

    await uploadImport(fileNamed("one.csv"));
    await uploadImport(fileNamed("two.csv"));

    const [first, second] = keysSent(fetchMock);
    expect(first).not.toBe(second);
  });

  it("surfaces the server's own message rather than a generic one", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        message: "No column was mapped to the department name.",
      }),
    });

    //  The server's message names the column or the row. "Something went wrong" is the version
    //  nobody can act on.
    await expect(uploadImport(fileNamed("bad.csv"))).rejects.toThrow(
      "No column was mapped to the department name.",
    );
  });
});
