# UBOSS UI Package

This package is the only source for reusable visual foundations and components.

## Stack

- TypeScript
- React
- Tailwind CSS
- shadcn/ui with Base UI primitives
- Lucide icons
- Storybook or an equivalent isolated component workbench
- Vitest and Testing Library

## Ownership rules

- Product pages consume package components; they do not fork them.
- Semantic tokens are used instead of literal colors.
- Component variants are finite and documented.
- Domain components compose primitives without changing their accessibility contract.
- Every interactive component supports keyboard and disabled/loading/error behavior.
- Changes require visual, accessibility and regression review.

## Initial component backlog

### Foundations

- Typography
- Color and semantic status
- Spacing, radius and elevation
- Motion and focus
- Responsive containers

### Primitives

- Button and icon button
- Link
- Input and textarea
- Select/multi-select/combobox
- Checkbox/radio/switch
- Badge/status
- Tooltip/popover/menu
- Dialog/drawer
- Tabs
- Table
- Skeleton/spinner/progress
- Toast

### Composite

- AppSidebar
- AppTopbar
- WorkspaceSwitcher
- GlobalSearch
- NotificationDrawer
- CopilotDrawer
- BuilderHeader
- BuilderSectionNav
- BuilderFooter
- SaveState
- ErrorSummary
- SummaryDialog
- PermissionPicker
- AssignmentRuleCard
- InputDefinitionCard
- ScheduleBuilder
- FileImportStepper
- VersionSelector
- VersionDiff
- RunTimeline
- EmptyState
- ErrorState
- PermissionDenied

### Domain

- HierarchyTree/HierarchyNode
- ObjectiveStepCard
- ObjectiveGraph
- JobStepCard
- AgentToolCard
- AgentTestResult
- SkillRegistrySearch
- SkillCandidateComparison
- SkillCompatibilityGates
- SkillFactoryBuilder
- SupervisorScopeMatrix
- SupervisorRunControl
- TaskItem
- ApprovalDecision
- EvidencePanel

## Component documentation template

Each component documents:

1. Purpose and non-use cases.
2. Props and variants.
3. Keyboard interaction.
4. Focus behavior.
5. Loading/empty/error/disabled state.
6. Responsive behavior.
7. Accessibility name/description.
8. Visual examples.
9. Unit and interaction tests.

## Forbidden patterns

- Literal product colors in page components.
- New button/input styling inside feature folders.
- Clickable divs.
- Icon-only action without accessible name.
- Color-only status.
- Nested modal chains.
- Local duplicate status enums.
- Fake progress.
- Raw JSON as normal-user summary.
- Client-side permission checks as the only enforcement.
