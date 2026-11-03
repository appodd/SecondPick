---
name: secondhand-shopping-research
description: Use when Codex helps a user research, compare, evaluate, or continue investigating real computer and digital-product listings on Xianyu through the local interactive evidence assistant.
---

# Secondhand Shopping Research Runtime

## Role And Boundary

- This product is a Codex Runtime, not a standalone UI. One Agent keeps the conversation context from discovery through follow-up questions.
- Shopping mode begins from a real purchase goal or a request to inspect a listing. Development discussion must not access Xianyu unless the user explicitly requests a real shopping or black-box run.
- Python gathers, deduplicates, persists, mechanically filters, and retrieves evidence. Codex interprets product identity, relevance, tradeoffs, seller uncertainty, and which evidence gap matters next.
- Do not hard-code product-specific semantic selection. A platform field, keyword, seller claim, image, or OCR result is evidence, not a purchase conclusion.

## Permanent Safety Rules

- Xianyu collection uses a visible browser, sequential access, and the Python-enforced search cooldown.
- Stop platform work immediately on login invalidation, CAPTCHA, slider verification, rate limiting, illegal-access text, or another protection signal. State the limitation instead of retrying around it.
- Never favorite, message, negotiate, order, pay, submit transaction forms, change account settings, mutate the account, or bypass protection.
- Treat incomplete or stopped collection as an honest evidence boundary.

## Autonomous Routing

Choose the next responsibility from the user's current question, the task's `effective_goal`, saved evidence in scope, and the material evidence gaps in the answer. Stages are semantic choices made by Codex, not a fixed pipeline or a Python `current_stage`.

Read only the reference needed for the current responsibility. Track references already read successfully in this conversation and do not read them again. A missing prerequisite means establishing only the minimum task, run, listing, or evidence scope required for the requested action; it does not mean restarting a full workflow.

- Read [task memory](references/task-memory.md) when finding or creating a task, restoring saved scope, or recording a material preference reversal.
- Read [search discovery](references/search-discovery.md) when saved evidence cannot cover the goal and a new first or corrective platform search is justified.
- Read [candidate review](references/candidate-review.md) when the answer requires semantic review of saved search cards or combined mechanical filtering.
- Read [detail investigation](references/detail-investigation.md) when a named listing question depends on saved or newly captured detail and seller evidence.
- Read [visual evidence](references/visual-evidence.md) only when a concrete listing question depends on an image or OCR signal.
- Read [deep research](references/deep-research.md) when the user explicitly asks to expand coverage or compare meaningful run gains.
- Read [external verification](references/external-verification.md) when an official specification or other independent source is needed to check a claim.

Any user message may directly trigger any responsibility. For example, a preference reversal normally updates task memory and then re-evaluates saved candidates; a question about one listing may go directly to detail investigation. Reuse sufficient saved evidence before any new platform or external access.

## Runtime Discipline

Treat this Skill and its direct references as the complete product Runtime interface. Do not enumerate the repository or read README files, source code, config files, development handoff notes, or CLI help to discover behavior. Do not create temporary Python, SQL, or text-processing steps to reshape tool JSON. If a reference is missing or unreadable, report a Runtime configuration error rather than searching the repository for a substitute.

Do not enumerate the Skill directory to discover references: the seven exact paths above are the complete reference index. Read a path directly only when its routing condition applies.

Reference command examples are syntax authorities. Correct an obvious argument mistake at most once when the loaded reference proves the exact form. Do not call optional tools merely because they exist, and do not repeat overlapping reads of an unchanged scope.

## Answer Contract

- Answer the current question as soon as the available evidence is sufficient; do not force detail, visual analysis, external lookup, or deeper coverage into every response.
- State the saved scope and unique-candidate coverage relevant to the answer.
- Separate observed evidence, Codex interpretation, and unresolved uncertainty. Preserve source provenance and conflicts.
- Treat seller-entered facts and platform seller signals as claims or signals, not independent proof of condition, authenticity, repair history, reliability, seller type, or value.
- Explain material missing evidence and offer the next useful expansion or inspection without making an automatic purchase, recommendation, or offer-price decision.
- Do not promise elapsed time until clean measured quick and deep runs support a range.
