import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { api } from "./client";

export const queries = {
  checkReviews: (taskId: number, listingId: number, checkId: number, enabled = true) => infiniteQueryOptions({
    queryKey: ["task", taskId, "listing", listingId, "checks", checkId, "reviews"],
    queryFn: ({ pageParam }) => api.getCheckReviews(taskId, listingId, checkId, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: page => page.next_before_id ?? undefined,
    enabled,
  }),
  checkSuggestions: (taskId: number, listingId: number, enabled = true) => infiniteQueryOptions({
    queryKey: ["task", taskId, "listing", listingId, "check-suggestions"],
    queryFn: ({ pageParam }) => api.getCheckSuggestions(taskId, listingId, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: page => page.next_before_id ?? undefined,
    enabled,
  }),
  candidateChecks: (taskId: number, listingId: number, enabled = true) => infiniteQueryOptions({
    queryKey: ["task", taskId, "listing", listingId, "checks"],
    queryFn: ({ pageParam }) => api.getChecks(taskId, listingId, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: page => page.next_before_id ?? undefined,
    enabled,
  }),
  researchHistory: (taskId: number) => infiniteQueryOptions({
    queryKey: ["task", taskId, "research-history"],
    queryFn: ({ pageParam }) => api.getResearchHistory(taskId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: page => page.page?.next_cursor ?? undefined,
    enabled: Number.isFinite(taskId),
  }),
  assessment: (taskId: number, assessmentId: number, enabled = true) => queryOptions({
    queryKey: ["task", taskId, "assessment", assessmentId],
    queryFn: () => api.getAssessment(taskId, assessmentId),
    enabled: Number.isFinite(taskId) && enabled,
  }),
  messages: (taskId: number) => infiniteQueryOptions({
    queryKey: ["task", taskId, "messages"],
    queryFn: ({ pageParam }) => api.getMessages(taskId, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: page => page.next_before_id ?? undefined,
    enabled: Number.isFinite(taskId),
  }),
  actionRequests: (taskId: number) => infiniteQueryOptions({
    queryKey: ["task", taskId, "action-requests"],
    queryFn: ({ pageParam }) => api.getActionRequests(taskId, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: page => page.next_before_id ?? undefined,
    enabled: Number.isFinite(taskId),
  }),
  operation: (operationId: number | undefined) => queryOptions({
    queryKey: ["operation", operationId], queryFn: () => api.getOperation(operationId!),
    enabled: operationId !== undefined,
    refetchInterval: query => ["queued", "running", "waiting_confirmation"].includes(query.state.data?.operation.state ?? "") ? 2000 : false,
  }),
  setupStatus: () =>
    queryOptions({
      queryKey: ["setup-status"],
      queryFn: () => api.getSetupStatus(),
    }),

  settings: () =>
    queryOptions({
      queryKey: ["settings"],
      queryFn: () => api.getSettings(),
    }),

  taskPages: (limit = 50) =>
    infiniteQueryOptions({
      queryKey: ["tasks", limit],
      queryFn: ({ pageParam }) => api.getTasks(limit, pageParam),
      initialPageParam: 0,
      getNextPageParam: (lastPage) => lastPage.page.next_offset ?? undefined,
    }),

  task: (taskId: number) =>
    queryOptions({
      queryKey: ["task", taskId],
      queryFn: () => api.getTask(taskId),
      enabled: Number.isFinite(taskId),
    }),

  candidates: (taskId: number, limit = 4) =>
    queryOptions({
      queryKey: ["task", taskId, "candidates", limit],
      queryFn: () => api.getCandidates(taskId, limit),
      enabled: Number.isFinite(taskId),
    }),

  candidatePages: (taskId: number, limit = 50, enabled = true) =>
    infiniteQueryOptions({
      queryKey: ["task", taskId, "candidate-pages", limit],
      queryFn: ({ pageParam }) => api.getCandidates(taskId, limit, pageParam),
      initialPageParam: undefined as string | undefined,
      getNextPageParam: (lastPage) => lastPage.page.next_cursor ?? undefined,
      enabled: Number.isFinite(taskId) && enabled,
    }),

  market: (taskId: number, enabled = true) =>
    queryOptions({
      queryKey: ["task", taskId, "market"],
      queryFn: () => api.getMarket(taskId),
      enabled: Number.isFinite(taskId) && enabled,
    }),

  debug: (taskId: number, enabled = true) =>
    queryOptions({
      queryKey: ["task", taskId, "debug"],
      queryFn: () => api.getDebug(taskId),
      enabled: Number.isFinite(taskId) && enabled,
    }),

  listingEvidence: (
    taskId: number,
    listingId: number | undefined,
    enabled = true,
  ) =>
    queryOptions({
      queryKey: ["task", taskId, "listing", listingId, "evidence"],
      queryFn: () => api.getListingEvidence(taskId, listingId as number),
      enabled: Number.isFinite(taskId) && listingId !== undefined && enabled,
    }),
};
