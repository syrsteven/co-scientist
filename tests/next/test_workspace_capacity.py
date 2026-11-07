"""Local byte bounds only; no inference about provider token context."""
import json
from pathlib import Path

from co_scientist_next.reading_model import OpenAIChat
from co_scientist_next.store import encode

ROOT=Path(__file__).resolve().parents[2]


def test_workspace_profiles_support_complete_observed_size_without_changing_request():
    config=json.loads((ROOT/'docs/workbench/reading-model.json').read_text())
    old={**config,'max_request_bytes':262144}
    messages=[{'role':'user','content':'x'*646000}]
    request=OpenAIChat(config,None).request(messages)
    assert request==OpenAIChat(old,None).request(messages)
    size=len(encode(request).encode())
    assert old['max_request_bytes']<size<config['max_request_bytes']
    assert request['body']['messages']==messages
    assert request['body']['max_completion_tokens']==32768
    assert 'temperature' not in request['body']
    assert config['timeout_seconds']==600
    responses=json.loads((ROOT/'docs/workbench/responses-model.json').read_text())
    assert responses['max_request_bytes']==config['max_request_bytes']==2000000
