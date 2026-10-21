from enum import StrEnum


class RunState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    NEEDS_ATTENTION = "needs_attention"
    STOPPING = "stopping"
    COMPLETED = "completed"
    COMPLETED_PARTIAL = "completed_partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    RESULT_RECEIVED = "result_received"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    NEEDS_ATTENTION = "needs_attention"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExternalCallState(StrEnum):
    HTTP_CAPTURE_STARTED_V2 = "http_capture_started_v2"
    HTTP_CAPTURE_FAILED_V2 = "http_capture_failed_v2"
    DOMAIN_RAW_PERSIST_FAILED_V2 = "domain_raw_persist_failed_v2"
    HTTP_RESPONSE_CAPTURED_V2 = "http_response_captured_v2"
    ACCOUNTING_INCOMPLETE_V2 = "accounting_incomplete_v2"
    PLANNED = "planned"
    STARTED = "started"
    RAW_RESPONSE_PERSISTED = "raw_response_persisted"
    VALIDATED = "validated"
    AGENT_RESULT_SUBMITTED = "agent_result_submitted"
    DOMAIN_RESULT_APPLIED = "domain_result_applied"
    FAILED_BEFORE_RESPONSE = "failed_before_response"
    RAW_PERSIST_FAILED = "raw_persist_failed"
    VALIDATION_FAILED = "validation_failed"
    SUBMISSION_FAILED = "submission_failed"
    DOMAIN_APPLY_FAILED = "domain_apply_failed"
