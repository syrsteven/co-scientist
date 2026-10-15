"""Offline official tokenizers, calibrated API overhead, and lossless packets."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from functools import lru_cache
from typing import Any

from co_scientist.domain.continuous_execution import ContinuousPolicy


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@lru_cache(maxsize=4)
def deepseek_encoding(path: str, sha: str):
    import deepseek_recipe as recipe

    from co_scientist.release.resources import resource_path

    local = resource_path(path)
    if hashlib.sha256(local.read_bytes()).hexdigest() != sha:
        raise ValueError("TOKENIZER_IDENTITY_MISMATCH")
    return recipe.DeepseekV41Encoding().with_tokenizer(recipe.Tokenizer.from_file(str(local)))


@lru_cache(maxsize=4)
def openai_encoding(path: str, sha: str):
    import base64

    import tiktoken

    from co_scientist.release.resources import resource_path

    data = resource_path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError("TOKENIZER_IDENTITY_MISMATCH")
    ranks = {base64.b64decode(token): int(rank) for token, rank in
             (line.split() for line in data.splitlines() if line)}
    # Exact regex and special token IDs from OpenAI tiktoken0.14.0
    # openai_public.o200k_base; load the frozen local BPE file without HTTP.
    pattern = "|".join([  # noqa: FLY002 - preserve official tokenizer regex construction
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*", r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+"])
    return tiktoken.Encoding(name="o200k_base", pat_str=pattern, mergeable_ranks=ranks,
                            special_tokens={"<|endoftext|>": 199999, "<|endofprompt|>": 200018})


def input_tokens(body: dict, policy: ContinuousPolicy) -> tuple[int, str]:
    if body["model"] == "deepseek-flash":
        import deepseek_recipe as recipe

        converted = recipe.ChatCompletionRequest(body).convert(recipe.ConversionOptions())
        return len(deepseek_encoding(policy.deepseek_tokenizer_path,
                                    policy.deepseek_tokenizer_sha256).encode(converted.conversation)), "deepseek-recipe-v41"
    if body["model"] != "gpt-6.1-sol":
        raise ValueError("TOKENIZER_MODEL_NOT_REGISTERED")
    # tiktoken currently has no official gpt-6.1-sol mapping. This is an
    # explicitly selected, empirically calibrated estimator, never a fallback.
    encoding = openai_encoding(policy.openai_tokenizer_path, policy.openai_tokenizer_sha256)
    text = canonical({k: body[k] for k in ("input", "text") if k in body}).decode()
    return len(encoding.encode(text, disallowed_special=())), "tiktoken-o200k-calibrated"


def lossless_packet(value: Any) -> dict:
    """Intern repeated complete objects; every byte-bearing value is recoverable."""
    objects: dict[str, Any] = {}

    def encode(node):
        if isinstance(node, dict):
            if len(canonical(node)) >= 2048:
                key = hashlib.sha256(canonical(node)).hexdigest()
                if key in objects:
                    return {"$context_ref": key}
                objects[key] = {k: encode(v) for k, v in node.items()}
                return {"$context_ref": key}
            return {k: encode(v) for k, v in node.items()}
        if isinstance(node, list):
            return [encode(v) for v in node]
        return node

    root = encode(value)
    packet = {"version": "lossless-source-context-packet-v1", "root": root, "objects": objects,
              "original_sha256": hashlib.sha256(canonical(value)).hexdigest()}
    if unpack_packet(packet) != value:
        raise ValueError("context packet lost scientific input")
    return packet


def unpack_packet(packet: dict) -> Any:
    def decode(node):
        if isinstance(node, dict):
            if set(node) == {"$context_ref"}:
                return decode(packet["objects"][node["$context_ref"]])
            return {k: decode(v) for k, v in node.items()}
        if isinstance(node, list):
            return [decode(v) for v in node]
        return node
    value = decode(packet["root"])
    if hashlib.sha256(canonical(value)).hexdigest() != packet["original_sha256"]:
        raise ValueError("context packet identity mismatch")
    return value


def plan_context(body: dict, execution: dict, *, attempt: int = 1,
                 length_failures: int = 0, correction: str | None = None) -> tuple[dict, dict]:
    policy = ContinuousPolicy.model_validate(execution["continuous_policy"])
    adjusted = copy.deepcopy(body)
    messages_key = "input" if body["model"] == "gpt-6.1-sol" else "messages"
    output_key = "max_output_tokens" if messages_key == "input" else "max_tokens"
    original = hashlib.sha256(canonical(body)).hexdigest()
    if correction:
        adjusted[messages_key].append({"role": "user", "content": correction})
    count, tokenizer = input_tokens(adjusted, policy)
    source_count = 0
    for message in adjusted[messages_key]:
        try:
            doc = json.loads(message.get("content", ""))
            source_count = max(source_count, len(doc.get("input", {}).get("model_input", {})
                                               .get("retrieval_result", {}).get("sources", [])))
        except (ValueError, AttributeError):
            continue
    budget = policy.outputs[execution["role"]].budget(count, source_count, attempt, length_failures)
    budget = min(budget, execution["runtime"]["max_output_tokens"])
    margin = max(policy.safety_tokens, math.ceil(count * policy.safety_fraction))
    window = execution["capability"]["max_context_tokens"]
    adjustment = "none"
    if count + margin + budget > window or count + margin > execution["runtime"]["max_input_tokens"]:
        for message in adjusted[messages_key]:
            if message["role"] != "user":
                continue
            try:
                doc = json.loads(message["content"])
            except ValueError:
                continue
            message["content"] = json.dumps({"instruction": "Resolve each $context_ref through objects to read the complete original input. No scientific information has been summarized or removed.",
                "context_packet": lossless_packet(doc)}, ensure_ascii=False)
        adjustment = "lossless-source-context-packet-v1"
        count, tokenizer = input_tokens(adjusted, policy)
        margin = max(policy.safety_tokens, math.ceil(count * policy.safety_fraction))
    adjusted[output_key] = budget
    wire = canonical(adjusted)
    if len(wire) > policy.transport_body_bytes:
        raise ValueError("HTTP_BODY_CAPACITY_EXCEEDED")
    if count + margin > execution["runtime"]["max_input_tokens"] or count + margin + budget > window:
        raise ValueError("TOKEN_CONTEXT_CAPACITY_EXCEEDED: scientific input retained")
    plan = {"version": "context-plan-v1", "model": body["model"], "api": execution["capability"]["api"],
            "tokenizer": tokenizer, "calibration_hash": policy.calibration_hash,
            "estimated_input_tokens": count, "safety_margin": margin, "output_budget": budget,
            "context_window": window, "wire_bytes": len(wire), "wire_sha256": hashlib.sha256(wire).hexdigest(),
            "original_body_sha256": original, "adjustment": adjustment,
            "attempt": attempt, "length_failures": length_failures}
    return adjusted, plan


def validate_plan(body: dict, execution: dict, plan: dict) -> None:
    policy = ContinuousPolicy.model_validate(execution["continuous_policy"])
    count, name = input_tokens(body, policy)
    expected_margin = max(policy.safety_tokens, math.ceil(count * policy.safety_fraction))
    output = body.get("max_tokens", body.get("max_output_tokens"))
    if (plan["wire_sha256"] != hashlib.sha256(canonical(body)).hexdigest()
            or plan["estimated_input_tokens"] != count or plan["tokenizer"] != name
            or plan["safety_margin"] != expected_margin or plan["output_budget"] != output
            or plan["context_window"] != execution["capability"]["max_context_tokens"]
            or plan["calibration_hash"] != policy.calibration_hash
            or plan["model"] != execution["capability"]["model"]
            or plan["api"] != execution["capability"]["api"]
            or not 0 < output <= execution["runtime"]["max_output_tokens"]
            or count + expected_margin > execution["runtime"]["max_input_tokens"]
            or count + expected_margin + output > plan["context_window"]
            or len(canonical(body)) > policy.transport_body_bytes):
        raise ValueError("CONTEXT_PLAN_IDENTITY_MISMATCH")


def persist_plan(transport, plan: dict, kind: str = "context-plan-v1") -> None:
    from co_scientist.runtime.transport_observability import current_external_call_observation

    ctx = current_external_call_observation()
    key = (ctx.external_call_id if ctx else plan["wire_sha256"]) + ":" + kind
    transport.artifacts.persist_raw(key, canonical(plan), "application/json",
        request_fingerprint=plan["wire_sha256"], run_id=ctx.run_id if ctx else transport.identity,
        task_id=ctx.task_id if ctx else key, execution_context_fingerprint=plan["original_body_sha256"])


def record_usage_observation(transport, plan: dict, raw: bytes) -> None:
    """Derived measurements after durable capture; never synthesize usage."""
    try:
        envelope = json.loads(raw)
        usage = envelope["usage"]
        actual = usage.get("input_tokens", usage.get("prompt_tokens"))
        output = usage.get("output_tokens", usage.get("completion_tokens"))
        if type(actual) is not int or actual < 0 or type(output) is not int or output < 0:
            return
    except (ValueError, KeyError, TypeError):
        return
    observation = {"version": "token-usage-observation-v1", "wire_sha256": plan["wire_sha256"],
        "model": envelope.get("model"), "estimated_input_tokens": plan["estimated_input_tokens"],
        "actual_input_tokens": actual, "actual_output_tokens": output,
        "input_error": plan["estimated_input_tokens"]-actual,
        "within_reserved_margin": actual <= plan["estimated_input_tokens"]+plan["safety_margin"],
        "reasoning_tokens": usage.get("output_tokens_details", {}).get("reasoning_tokens"),
        "cached_tokens": usage.get("input_tokens_details", usage.get("prompt_tokens_details", {})).get("cached_tokens")}
    persist_plan(transport, {**observation, "wire_sha256": plan["wire_sha256"],
        "original_body_sha256": plan["original_body_sha256"]}, "token-usage-observation-v1")
