"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";

import type { CopilotSource } from "@/lib/api/contract";
import { searchWorkspace } from "@/lib/api/copilot";
import { cn } from "@/lib/cn";

/**
 * §3's global search, connected.
 *
 * It showed a disabled box saying so from Gate 1 until now, which the work breakdown asked for in
 * as many words: *"Search shows an honest unavailable state until Gate 7."* This is the gate.
 *
 * ## What it searches, and why that is the same thing the Copilot reads
 *
 * `/copilot/search` is the Copilot's own permission-filtered retrieval with the model left out.
 * That is deliberate: two search implementations would be two answers to *"may this person see
 * this?"*, and the one in the search box is the one nobody would remember to re-check. So a result
 * here is always something the person could open, and it is always something the Copilot could
 * quote.
 *
 * ## Two seconds of typing is not a query
 *
 * Nothing is sent until two characters, and then only after the typing pauses. A request per
 * keystroke would be six requests to spell *"quotes"*, each doing full-text work across six tables
 * and a permission check per candidate row.
 *
 * ## The states are all real
 *
 * Matches, nothing matched, and failed. There is no fixture and no placeholder list: a search box
 * that shows plausible results before it has any is the exact dishonesty
 * `CLAUDE.md`'s truthfulness rules were written about.
 */
export function GlobalSearch() {
  const t = useTranslations("shell");
  const listId = useId();
  const [text, setText] = useState("");
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const box = useRef<HTMLDivElement>(null);

  //  Debounced: `text` is what the person sees, `term` is what has been asked for.
  useEffect(() => {
    const timer = setTimeout(() => setTerm(text.trim()), 220);
    return () => clearTimeout(timer);
  }, [text]);

  const results = useQuery({
    queryKey: ["search", term],
    queryFn: ({ signal }) => searchWorkspace(term, signal),
    enabled: term.length >= 2,
    //  A search is a read of things that change slowly; a person retyping the same word within a
    //  minute is not asking a new question.
    staleTime: 60_000,
  });

  //  Click outside closes it. Escape does too, below — a panel that only closes on one of the two
  //  is a panel somebody gets stuck in.
  useEffect(() => {
    function onDown(event: MouseEvent) {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const found: CopilotSource[] = results.data ?? [];
  const showing = open && term.length >= 2;

  function go(source: CopilotSource) {
    setOpen(false);
    setText("");
    window.location.assign(source.href);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!showing || found.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index + 1) % found.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index <= 0 ? found.length - 1 : index - 1));
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      go(found[active]!);
    }
  }

  return (
    <div ref={box} className="relative hidden min-w-0 max-w-xs flex-1 lg:block">
      <label htmlFor="global-search" className="sr-only">
        {t("search")}
      </label>
      <Search
        aria-hidden
        className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
      />
      <input
        id="global-search"
        type="search"
        role="combobox"
        aria-expanded={showing}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          showing && active >= 0 ? `${listId}-${active}` : undefined
        }
        autoComplete="off"
        value={text}
        maxLength={200}
        placeholder={t("searchPlaceholder")}
        onChange={(event) => {
          setText(event.target.value);
          setActive(-1);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        className={cn(
          "w-full rounded-md border border-border bg-card py-1.5 pl-8 pr-3 text-sm",
          "placeholder:text-muted-foreground",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
        )}
      />

      {showing ? (
        <div
          className={cn(
            "absolute left-0 right-0 top-full z-40 mt-1 overflow-hidden rounded-md",
            "border border-border bg-background shadow-dialog",
          )}
        >
          {results.isPending ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">{t("searching")}</p>
          ) : results.isError ? (
            /*  A failed search says so. It does not render an empty list, which would say
                "nothing matched" about a request that never arrived. */
            <p className="px-3 py-2 text-xs text-danger">{t("searchFailed")}</p>
          ) : found.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              {t("searchNothing", { term })}
            </p>
          ) : (
            <ul id={listId} role="listbox" aria-label={t("search")} className="max-h-80 overflow-y-auto">
              {found.map((source, index) => (
                <li
                  key={`${source.kind}-${source.id}`}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                >
                  <button
                    type="button"
                    onMouseEnter={() => setActive(index)}
                    onClick={() => go(source)}
                    className={cn(
                      "flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left text-sm",
                      index === active ? "bg-accent" : "hover:bg-accent",
                    )}
                  >
                    <span className="min-w-0 truncate">{source.label}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {t(`searchKind.${source.kind}` as "searchKind.objective")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
