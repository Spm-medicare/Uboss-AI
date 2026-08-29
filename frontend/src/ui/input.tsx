import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";
import { controlClass } from "@/ui/field";

/**
 * A text box. Pair it with `Field` — on its own it has no label, and a control without a label is
 * unusable for anyone not looking at the screen.
 *
 * There is no `error` prop: `aria-invalid` already carries that, `Field` sets it, and the style
 * follows from it. A second way to say the same thing is a second way for them to disagree.
 */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, type = "text", ...rest }, ref) {
    return (
      <input ref={ref} type={type} className={cn(controlClass, className)} {...rest} />
    );
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, rows = 4, ...rest }, ref) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(controlClass, "resize-y", className)}
      {...rest}
    />
  );
});
