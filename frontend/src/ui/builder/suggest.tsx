"use client";

import { useId } from "react";

import { cn } from "@/lib/cn";
import { controlClass } from "@/ui/field";

/**
 * A field that offers the workbook's list and accepts anything typed.
 *
 * This is the whole point. Every list on the approved workbook's "Dropdown Lists" sheet ends in
 * `Other`, which means the sheet itself allows a value that is not on it. A `<select>` would
 * refuse one — telling a team that the way they actually work is invalid — and a plain text box
 * would throw away the vocabulary the sheet standardised.
 *
 * A native `<datalist>` does both: the browser offers the list, the person can type past it, and
 * it needs no popover, no keyboard handling and no focus trap of our own. The trade is that its
 * styling is the browser's; for a field whose job is to suggest rather than to constrain, that is
 * the right side of the trade.
 */
export function Suggest({
  label,
  value,
  onChange,
  options,
  multiline = false,
  disabled = false,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** The workbook's suggestions. Absent means a plain field — some columns have no list. */
  options?: string[] | undefined;
  multiline?: boolean | undefined;
  disabled?: boolean | undefined;
  placeholder?: string | undefined;
}) {
  const id = useId();
  const listId = `${id}-options`;

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted-foreground">
        {label}
      </label>

      {multiline ? (
        <textarea
          id={id}
          value={value}
          rows={2}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          className={cn(controlClass, "resize-y text-sm")}
        />
      ) : (
        <>
          <input
            id={id}
            value={value}
            disabled={disabled}
            placeholder={placeholder}
            list={options ? listId : undefined}
            onChange={(event) => onChange(event.target.value)}
            className={cn(controlClass, "text-sm")}
          />
          {options ? (
            <datalist id={listId}>
              {options.map((option) => (
                <option key={option} value={option} />
              ))}
            </datalist>
          ) : null}
        </>
      )}
    </div>
  );
}
