# Task Memory

## When To Read

Read when matching a current goal to saved work, creating the minimum task scope, restoring task/run context, or persisting a material user preference addition, removal, or reversal.

## Stage Goal

Maintain durable conversational intent without making product rankings. Preserve `original_goal`; represent the latest accumulated intent as `effective_goal`.

## Minimum Data Prerequisites

A lookup needs no identifier. Creation needs the user's full natural-language goal and a short neutral title. An update needs a task ID, the exact preference-changing user message, and the resulting complete effective goal.

## Reuse Saved Evidence

Inspect recent or named tasks before creating a duplicate. A preference change does not invalidate saved candidates automatically: update the task, then reassess the existing pool against the new goal before requesting another search.

## Canonical Commands

```powershell
python -m shopping_agent.cli task-summary --limit 10 --pretty
python -m shopping_agent.cli task-summary --task-id 8 --pretty
python -m shopping_agent.cli task-create --title "MacBook Air M2" --goal "帮我找一台 MacBook Air M2，预算 4000 左右" --city 上海
python -m shopping_agent.cli task-update --task-id 8 --user-message "算了，不要最低价了，看看成色好的" --effective-goal "找成色好的 MacBook Air M2，上海自提优先" --add-preference "成色优先" --remove-preference "最低价优先"
```

## Output And Evidence Semantics

Task summaries report persisted intent, attached runs, cumulative unique candidates, and per-run gains. Those counts describe saved coverage, not relevance or purchase quality. Preference revisions are stored in SQLite; no Markdown file is updated during a conversation.

## Exit Conditions

Exit when the current effective goal and the minimum relevant saved scope are known, or when a required task update has been persisted. If no task is needed to answer a narrow saved-listing question, do not create one.

## Related Stages

Use search discovery only when saved coverage is insufficient. Use candidate review after a goal change to re-evaluate existing cards before collecting more data.
