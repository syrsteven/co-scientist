"""Offline request/isolation/capacity audit; no client, credentials or network."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text())


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def main():
    config = read("model-config.json")
    p05 = read("source-p05.parsed-result.json")
    assert p05["execution_mode"] == "real_model" and p05["background_status"] == "saved"
    directed, opened = read("directed.input.json"), read("open.input.json")
    assert directed["neutral_orientation"] == p05["artifact"] and directed["requested_count"] == 1
    assert set(opened) == {
        "goal_context",
        "neutral_overview",
        "source_discovery_capabilities",
        "generic_search_constraints",
    }
    assert opened["goal_context"] == directed["goal_context"]
    assert opened["neutral_overview"] == {
        k: p05["artifact"][k] for k in ["overview", "competing_explanations", "limitations"]
    }
    assert opened["generic_search_constraints"] == {"requested_count": 1, "no_sibling_inputs": True}
    assert opened["source_discovery_capabilities"] == directed["source_discovery_capabilities"]
    sizes = {}
    for name, payload in [("directed", directed), ("open", opened)]:
        messages = read(name + ".messages.json")
        wire = read(name + ".planned-http.json")
        assert json.loads(messages[-1]["content"]) == payload
        assert wire["body"] == {
            "model": config["model"],
            "messages": messages,
            **config["parameters"],
            "n": 1,
            "stream": False,
            "store": False,
        }
        assert wire["timeout_seconds"] == config["timeout_seconds"] == 600
        assert "Codex 初审" not in json.dumps(messages, ensure_ascii=False)
        sizes[name] = len(encode(wire))
    assert sizes == {"directed": 64013, "open": 7014}
    assert sizes["directed"] > config["max_request_bytes"] == 64000
    proposal = read("model-config.capacity-proposal.json")
    assert {k for k in config if config[k] != proposal[k]} == {"max_request_bytes"}
    assert proposal["max_request_bytes"] == 65536 >= sizes["directed"]
    print(
        "Verified unchanged DIRECTED/P05 packet, strict four-key OPEN isolation and identical wire parameters. Original capacity: DIRECTED blocked64013>64000; proposal65536, no model execution."
    )


if __name__ == "__main__":
    main()
