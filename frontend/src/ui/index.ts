/**
 * The single import path for everything shared.
 *
 * A page imports from `@/ui`; it never reaches into a file inside it. That is what makes the rule
 * in `ui/README.md` — no new button or input styling inside a feature folder — enforceable rather
 * than aspirational: there is one door, and everything behind it is documented.
 */

export { Alert, type AlertTone } from "@/ui/alert";
export { Badge, type BadgeProps } from "@/ui/badge";
export { Button, type ButtonProps } from "@/ui/button";
export {
  Card,
  CardBody,
  CardHeader,
  DescriptionList,
  DescriptionRow,
} from "@/ui/card";
export { Field, controlClass } from "@/ui/field";
export { Input, Textarea } from "@/ui/input";
export { Skeleton } from "@/ui/skeleton";
export { SkipLink } from "@/ui/skip-link";
export { Spinner } from "@/ui/spinner";
export {
  DeniedState,
  EmptyState,
  ErrorState,
  LoadingState,
  OfflineState,
  QueryStates,
} from "@/ui/states";
