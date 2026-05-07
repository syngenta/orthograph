# Planning: Epics and Tasks

> Generated from: `reviews/2026-05-07_post-gqlalchemy-review.md`
> Date: 2026-05-07

## Epic Overview

| Epic | Title | Priority | Tasks |
|------|-------|----------|-------|
| E1 | API Ergonomics & Developer Experience | High | 5 |
| E2 | Code Deduplication & Internal Quality | Medium | 4 |
| E3 | Documentation & Onboarding | High | 3 |
| E4 | Extension Robustness & Consistency | Medium | 3 |

## Dependency Order

```
E3 (Documentation) -- independent, can start immediately
E2 (Deduplication) -- independent, pure refactoring
E1 (API Ergonomics) -- benefits from E2 being done first (shared base)
E4 (Extension Robustness) -- benefits from E2 (shared utilities)
```

## Relationship to Roadmap

These epics address **quality and polish** on the existing v0.1 feature
set. They are distinct from the roadmap's **new feature** items (schema
hierarchy, custom validators, property constraints, etc.). Completing
these epics brings the library to a "v0.2-beta" quality level suitable
for internal pilot adoption.

## Detailed Specs

Each epic has a dedicated file in `epics/`:
- `epics/E1_api_ergonomics.md`
- `epics/E2_code_deduplication.md`
- `epics/E3_documentation.md`
- `epics/E4_extension_robustness.md`
