import type {
  ApiErrorEnvelope,
  CandidatePage,
  CodexStatus,
  DebugSnapshot,
  ListingEvidence,
  MarketOverview,
  SettingsPatch,
  SetupCheck,
  SetupStatus,
  TaskDetail,
  ResearchHistory, AssessmentBatch, TaskHistory,
  TaskListResponse,
  UserSettings,
} from "./types";
import { conversationClient } from "./conversationClient";
import { checksClient } from "./checksClient";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor({
    status,
    code,
    message,
  }: {
    status: number;
    code: string;
    message: string;
  }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export async function request<T>(path: string, init?: RequestInit, allowNull = false): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const body = await response.text();
  let payload: unknown = null;
  if (body) {
    try {
      payload = JSON.parse(body);
    } catch {
      if (!response.ok) {
        throw new ApiError({
          status: response.status,
          code: "http_error",
          message: "Request failed.",
        });
      }
      throw invalidResponse("API");
    }
  }

  if (!response.ok) {
    const envelope = isRecord(payload) ? payload as ApiErrorEnvelope : {};
    throw new ApiError({
      status: response.status,
      code: envelope.error?.code ?? "http_error",
      message: envelope.error?.message ?? "Request failed.",
    });
  }

  if (payload === null && !allowNull) {
    throw invalidResponse("API");
  }
  return payload as T;
}

function invalidResponse(resource: string) {
  return new ApiError({
    status: 200,
    code: "invalid_response",
    message: `${resource} response is incomplete.`,
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseSetupStatus(value: unknown): SetupStatus {
  if (
    !isRecord(value) ||
    typeof value.setup_completed !== "boolean" ||
    !Array.isArray(value.environment) ||
    !value.environment.every(
      (check) =>
        isRecord(check) &&
        typeof check.name === "string" &&
        typeof check.ok === "boolean" &&
        typeof check.detail === "string",
    ) ||
    !isRecord(value.codex) ||
    typeof value.codex.cli_available !== "boolean" ||
    typeof value.codex.auth_available !== "boolean" ||
    typeof value.codex.process_running !== "boolean" ||
    !isRecord(value.xianyu) ||
    typeof value.xianyu.profile_present !== "boolean" ||
    !["unknown", "verified", "invalid"].includes(
      String(value.xianyu.auth_status),
    ) ||
    typeof value.can_browse_existing_data !== "boolean" ||
    typeof value.can_start_research !== "boolean"
  ) {
    throw invalidResponse("Setup status");
  }
  return value as unknown as SetupStatus;
}

function parseUserSettings(value: unknown): UserSettings {
  if (
    !isRecord(value) ||
    typeof value.setup_completed !== "boolean" ||
    (value.setup_mode !== undefined && !["basic", "ai"].includes(String(value.setup_mode))) ||
    !(value.default_city === null || typeof value.default_city === "string") ||
    !Array.isArray(value.platforms) ||
    !value.platforms.every((platform) => typeof platform === "string") ||
    typeof value.allow_ocr !== "boolean" ||
    !["research", "debug"].includes(String(value.preferred_view))
  ) {
    throw invalidResponse("Settings");
  }
  return value as unknown as UserSettings;
}

function parseDebugSnapshot(value: unknown): DebugSnapshot {
  if (
    !isRecord(value) ||
    !isRecord(value.task) ||
    !Number.isInteger(value.task.id) ||
    !Array.isArray(value.runs) ||
    !value.runs.every(
      (run) =>
        isRecord(run) &&
        Number.isInteger(run.run_id) &&
        Number.isInteger(run.query_count) &&
        Number.isInteger(run.page_snapshot_count) &&
        Number.isInteger(run.listing_snapshot_count),
    ) ||
    !Array.isArray(value.reports) ||
    !value.reports.every(
      (report) => isRecord(report) && Number.isInteger(report.id),
    ) ||
    !isRecord(value.search_coverage) ||
    typeof value.search_coverage.status !== "string" ||
    !Number.isInteger(value.search_coverage.unique_candidates) ||
    !Number.isInteger(value.search_coverage.target_min) ||
    !Number.isInteger(value.search_coverage.target_max) ||
    !Number.isInteger(value.search_coverage.low_gain_streak) ||
    typeof value.search_coverage.suggested_action !== "string" ||
    !Array.isArray(value.search_coverage.runs) ||
    !value.search_coverage.runs.every(
      (run) =>
        isRecord(run) &&
        Number.isInteger(run.run_id) &&
        Number.isInteger(run.new_unique_count),
    ) ||
    !isRecord(value.global_platform_access_events) ||
    value.global_platform_access_events.scope !== "global" ||
    typeof value.global_platform_access_events.warning !== "string" ||
    !Array.isArray(value.global_platform_access_events.events) ||
    !value.global_platform_access_events.events.every(
      (event) =>
        isRecord(event) &&
        Number.isInteger(event.id) &&
        typeof event.platform === "string" &&
        typeof event.operation === "string" &&
        (event.target === null || typeof event.target === "string") &&
        typeof event.attempted_at === "string",
    )
  ) {
    throw invalidResponse("Debug snapshot");
  }
  return value as unknown as DebugSnapshot;
}

export const api = {
  ...checksClient,
  ...conversationClient,
  async getProductImages(taskId: number, listingId: number): Promise<{ listing_id: number; images: { id: number; url: string; created_at: string }[] }> {
    const value = await request<unknown>(`/api/tasks/${taskId}/listings/${listingId}/images`);
    if (!isRecord(value) || value.listing_id !== listingId || !Array.isArray(value.images) ||
        !value.images.every(item => isRecord(item) && Number.isSafeInteger(item.id) && typeof item.url === "string" && typeof item.created_at === "string")) {
      throw invalidResponse("Product images");
    }
    return value as { listing_id: number; images: { id: number; url: string; created_at: string }[] };
  },
  async getSetupStatus(): Promise<SetupStatus> {
    return parseSetupStatus(await request<unknown>("/api/setup/status"));
  },

  async checkEnvironment(): Promise<SetupCheck[]> {
    return request<SetupCheck[]>("/api/setup/check-environment", {
      method: "POST",
    });
  },

  async checkCodex(): Promise<CodexStatus> {
    return request<CodexStatus>("/api/setup/check-codex", { method: "POST" });
  },

  async getSettings(): Promise<UserSettings> {
    return parseUserSettings(await request<unknown>("/api/settings"));
  },

  async updateSettings(patch: SettingsPatch): Promise<UserSettings> {
    return parseUserSettings(
      await request<unknown>("/api/settings", {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    );
  },

  async getTasks(limit = 50, offset = 0): Promise<TaskListResponse> {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    return request<TaskListResponse>(`/api/tasks?${params}`);
  },

  async getTask(taskId: number): Promise<TaskDetail> {
    return request<TaskDetail>(`/api/tasks/${taskId}`);
  },

  async getResearchHistory(taskId: number, cursor?: string): Promise<ResearchHistory> {
    const params = new URLSearchParams({ limit: "10" });
    if (cursor) params.set("cursor", cursor);
    return request<ResearchHistory>(`/api/tasks/${taskId}/research?${params}`);
  },

  async getTaskHistory(taskId: number, cursor: string): Promise<TaskHistory> {
    const params = new URLSearchParams({ limit: "10", cursor });
    return request<TaskHistory>(`/api/tasks/${taskId}/history?${params}`);
  },

  async getAssessment(taskId: number, assessmentId: number): Promise<AssessmentBatch> {
    return request<AssessmentBatch>(`/api/tasks/${taskId}/research/assessments/${assessmentId}`);
  },

  async getCandidates(
    taskId: number,
    limit = 4,
    cursor?: string,
  ): Promise<CandidatePage> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) {
      params.set("cursor", cursor);
    }
    return request<CandidatePage>(`/api/tasks/${taskId}/candidates?${params}`);
  },

  async getMarket(taskId: number): Promise<MarketOverview> {
    return request<MarketOverview>(`/api/tasks/${taskId}/market`);
  },

  async getDebug(taskId: number): Promise<DebugSnapshot> {
    return parseDebugSnapshot(
      await request<unknown>(`/api/tasks/${taskId}/debug`),
    );
  },

  async getListingEvidence(
    taskId: number,
    listingId: number,
  ): Promise<ListingEvidence> {
    const params = new URLSearchParams({ task_id: String(taskId) });
    return request<ListingEvidence>(
      `/api/listings/${listingId}/evidence?${params}`,
    );
  },
};
