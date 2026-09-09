# Five-provider CLI

The execute/worker path supports OpenAI, DeepSeek, Qwen, Gemini and Claude.
Each Run freezes one provider and model. Role-level model mixing and cross-run
scientific evaluation are not implemented yet.

| Provider | Key environment variable | Model environment variable | Profile suffix |
|---|---|---|---|
| openai | OPENAI_API_KEY | CO_SCIENTIST_OPENAI_MODEL | online |
| deepseek | DEEPSEEK_API_KEY | CO_SCIENTIST_DEEPSEEK_MODEL | deepseek |
| qwen | DASHSCOPE_API_KEY | CO_SCIENTIST_QWEN_MODEL | qwen |
| gemini | GEMINI_API_KEY | CO_SCIENTIST_GEMINI_MODEL | gemini |
| claude | ANTHROPIC_API_KEY | CO_SCIENTIST_CLAUDE_MODEL | claude |

Use an API-accessible model ID, not a chat subscription name. Qwen currently uses
the mainland China DashScope endpoint; use a matching region credential.
Native adapters request at most 8192 output tokens. Model support for JSON mode
varies; incompatible models fail through the existing durable retry mechanism.

## DeepSeek and OpenAI

From the repository root, activate the installed environment:

```bash
source .venv/bin/activate
```

Set credentials in your local terminal environment (do not commit them).
Then set explicit model IDs:

```bash
export CO_SCIENTIST_DEEPSEEK_MODEL='YOUR_DEEPSEEK_MODEL_ID'
export CO_SCIENTIST_OPENAI_MODEL='YOUR_OPENAI_MODEL_ID'

co-scientist run execute --run-id lens-deepseek-001 \
  --goal examples/lens_regeneration_goal.yaml \
  --profile configs/profiles/core_preview_deepseek.yaml \
  --provider deepseek --data-dir .co-scientist-deepseek

co-scientist run execute --run-id lens-openai-001 \
  --goal examples/lens_regeneration_goal.yaml \
  --profile configs/profiles/core_preview_online.yaml \
  --provider openai --data-dir .co-scientist-openai
```

Both use live PubMed, the same goal and budget/review/stop settings.
Actual literature and generated hypotheses may differ across runs; these are
initial functional trials, not a controlled scientific benchmark.

```bash
co-scientist run status lens-deepseek-001 --data-dir .co-scientist-deepseek
co-scientist worker run lens-deepseek-001 --data-dir .co-scientist-deepseek
co-scientist run export lens-deepseek-001 --data-dir .co-scientist-deepseek \
  --output lens-deepseek-001-export
```

Use a new run ID for a new experiment; retain the same data directory to resume.
Exports must target new directories. Terminal failed runs require a new run ID.
Raw provider envelopes are persisted before scientific JSON parsing. Invalid or
truncated scientific output is rejected. Usage records contain provider token counts;
USD remains unpriced and must not be interpreted as free usage.

## API references

- DeepSeek JSON: https://api-docs.deepseek.com/guides/json_mode/
- Gemini: https://ai.google.dev/api/generate-content
- Claude: https://platform.claude.com/docs/en/api/http/messages/create

Live provider success is only established by an actual credentialed Run.
