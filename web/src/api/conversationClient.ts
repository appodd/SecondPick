import { ApiError, request } from "./client";
import type { CandidateStatementInput, CandidateStatementBinding, StatementChange } from "./types";
import type { ActionDecisionResponse, ActionRequestDto, HistoryPage, MessageCreationResponse, MessageDto, OperationDetail, OperationDto, TaskCreationResponse, TaskRecord } from "./types";

type Obj = Record<string, unknown>;
const object = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const id = (v: unknown) => Number.isSafeInteger(v) && (v as number) > 0;
const nullableText = (v: unknown) => v === null || typeof v === "string";
const ids = (v: unknown) => Array.isArray(v) && v.every(id) && new Set(v).size === v.length;
const operation = (v: unknown): v is OperationDto => object(v) && id(v.id) && id(v.task_id) &&
  ["queued", "running", "waiting_confirmation", "completed", "failed", "cancelled", "interrupted"].includes(String(v.state)) && nullableText(v.error_code) && nullableText(v.error_detail);
const binding = (v: unknown) => v === undefined || v === null || (object(v) && id(v.id) && id(v.listing_id) && ["seller_reply", "user_observation"].includes(String(v.kind)) &&
  (v.status === undefined || ["active", "withdrawn"].includes(String(v.status))) &&
  (v.revision_id === undefined || (Number.isSafeInteger(v.revision_id) && Number(v.revision_id) >= 0)) &&
  (v.original_listing_id === undefined || v.original_listing_id === null || id(v.original_listing_id)));
const message = (v: unknown): v is MessageDto => object(v) && binding(v.candidate_statement) && id(v.id) && id(v.task_id) && ["user", "assistant", "system"].includes(String(v.role)) && typeof v.content === "string" && typeof v.created_at === "string" && (v.operation_id === null || id(v.operation_id)) && ids(v.candidate_ids) && (v.candidate_ids as number[]).length <= 4;
const action = (v: unknown): v is ActionRequestDto => object(v) && id(v.id) && id(v.task_id) && id(v.operation_id) && typeof v.summary === "string" && typeof v.risk === "string" && ids(v.listing_ids) && Array.isArray(v.actions) && v.actions.length > 0 && v.actions.every(a => ["search", "detail", "media", "ocr"].includes(String(a))) && ["pending", "approved", "rejected"].includes(String(v.state)) && (v.search_query === undefined || nullableText(v.search_query)) && (v.max_pages === undefined || (Number.isInteger(v.max_pages) && Number(v.max_pages) >= 1 && Number(v.max_pages) <= 3));
const task = (v: unknown): v is TaskRecord => object(v) && id(v.id) && ["title", "goal", "original_goal", "effective_goal", "city", "status", "created_at", "updated_at"].every(k => typeof v[k] === "string") && nullableText(v.notes);
function checked<T>(value: unknown, valid: (v: unknown) => boolean): T {
  if (!valid(value)) throw new ApiError({ status: 200, code: "invalid_response", message: "会话数据不完整，请刷新重试。" });
  return value as T;
}
const created = (v: unknown) => object(v) && message(v.message) && operation(v.operation) && v.message.task_id === v.operation.task_id && v.message.operation_id === v.operation.id;
const detail = (v: unknown) => object(v) && operation(v.operation) && Number.isSafeInteger(v.last_event_id) && (v.last_event_id as number) >= 0 && (v.action_request === null || (action(v.action_request) && v.action_request.task_id === v.operation.task_id && v.action_request.operation_id === v.operation.id));
const page = (valid: (v: unknown) => boolean) => (v: unknown) => object(v) && Array.isArray(v.items) && v.items.every(valid) && typeof v.has_more === "boolean" && (v.next_before_id === null || id(v.next_before_id)) && (!v.has_more || id(v.next_before_id));
const json = (value: unknown, method = "POST") => ({ method, body: JSON.stringify(value) });
export const conversationClient = {
  async changeStatement(taskId: number, statementId: number, change: StatementChange) {
    return checked<CandidateStatementBinding>(await request(`/api/tasks/${taskId}/statements/${statementId}`, json(change, "PATCH")),
      v => object(v) && binding(v) && v.id === statementId);
  },
  async analyzeCollection(jobId: number) {
    return checked<OperationDetail>(await request(`/api/browser/jobs/${jobId}/analyze`, { method: "POST" }), detail);
  },
  async createTask(message: string) {
    return checked<TaskCreationResponse>(await request("/api/tasks", json({ message })), v => created(v) && object(v) && task(v.task) && operation(v.operation) && v.task.id === v.operation.task_id);
  },
  async sendMessage(taskId: number, message: string, candidateStatement?: CandidateStatementInput) {
    return checked<MessageCreationResponse>(await request(`/api/tasks/${taskId}/messages`, json({ message, ...(candidateStatement ? { candidate_statement: candidateStatement } : {}) })), v => created(v) && object(v) && operation(v.operation) && v.operation.task_id === taskId);
  },
  async renameTask(taskId: number, title: string) {
    return checked<TaskRecord>(await request(`/api/tasks/${taskId}`, json({ title }, "PATCH")), v => task(v) && v.id === taskId);
  },
  async getMessages(taskId: number, beforeId?: number) {
    return checked<HistoryPage<MessageDto>>(await request(`/api/tasks/${taskId}/messages?limit=50${beforeId ? `&before_id=${beforeId}` : ""}`), page(v => message(v) && v.task_id === taskId));
  },
  async getActionRequests(taskId: number, beforeId?: number) {
    return checked<HistoryPage<ActionRequestDto>>(await request(`/api/tasks/${taskId}/action-requests?limit=50${beforeId ? `&before_id=${beforeId}` : ""}`), page(v => action(v) && v.task_id === taskId));
  },
  async getOperation(operationId: number) {
    return checked<OperationDetail>(await request(`/api/operations/${operationId}`), v => detail(v) && object(v) && operation(v.operation) && v.operation.id === operationId);
  },
  async cancelOperation(operationId: number) {
    return checked<OperationDetail>(await request(`/api/operations/${operationId}/cancel`, { method: "POST" }), detail);
  },
  async decideAction(taskId: number, requestId: number, decision: "approve" | "reject") {
    return checked<ActionDecisionResponse>(await request(`/api/action-requests/${requestId}/${decision}`, json({ task_id: taskId })), v => object(v) && action(v.action_request) && operation(v.operation) && v.action_request.id === requestId && v.action_request.task_id === taskId && v.operation.task_id === taskId && v.action_request.operation_id === v.operation.id);
  },
};
