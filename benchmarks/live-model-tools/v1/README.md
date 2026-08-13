# OMH-native Hermes Agent model calibration benchmark

`omh_live_model_tool_benchmark/v1` compares baseline and model-family-calibrated
OMH prompts on a pinned synthetic coding corpus.

The live path measures the product under test:

1. resolve the selected model through `omh coding model-route`;
2. build baseline and optimized prompts from the same task, adding only the
   calibration selected by `unit_prompt_protocol.py`;
3. dispatch through the explicit
   `omh coding hermes-child dispatch --confirm-dispatch` boundary;
4. grade the final workspace and machine answer with controller-only validators;
5. read tool, token, and cost metrics from authenticated
   `routing_observation/v1` evidence.

There is no OMO execution path. OMH remains Hermes-native: core OMH makes no
provider call, and the explicit benchmark command launches the local Hermes CLI
under the existing isolated child-process contract.

## Safety and claim boundary

- `fake` is the default offline harness.
- `omh` requires `--allow-paid-live`; it can trigger paid provider calls through
  the local Hermes CLI.
- Prompts are sent over stdin and are never persisted by OMH.
- Missing token or cost telemetry stays `null`; the benchmark never estimates it.
- A completed child process is not a passing task. Controller-only semantic
  validators determine pass/fail.
- Results describe the pinned corpus, OMH version, Hermes version, model IDs, and
  conditions only. They do not establish universal model superiority.

## Commands

```bash
python benchmarks/live-model-tools/v1/bench.py doctor
python benchmarks/live-model-tools/v1/bench.py corpus --verify
python benchmarks/live-model-tools/v1/bench.py smoke

# Explicit paid live smoke:
python benchmarks/live-model-tools/v1/bench.py smoke \
  --harness omh \
  --model qwen3-coder-next \
  --condition optimized \
  --allow-paid-live \
  --max-paid-calls 1
```

Run baseline and optimized matrices separately so every condition uses the same
pinned instances:

```bash
python benchmarks/live-model-tools/v1/bench.py run \
  --harness omh --condition baseline --allow-paid-live --max-paid-calls 240
python benchmarks/live-model-tools/v1/bench.py run \
  --harness omh --condition optimized --allow-paid-live --max-paid-calls 240
```

The manifest currently covers Qwen3-Coder, current DeepSeek, and GLM agent
routes in addition to the existing comparison families. Prompt controls are
version-aware:

- Qwen3-Coder is treated as a non-thinking coding-agent model.
- DeepSeek preserves the distinction between current thinking-mode models and
  legacy R1 guidance.
- GLM can benefit from interleaved reasoning between tool results when the
  Hermes/provider contract exposes and preserves that context.

Provider parameters are not claimed unless Hermes actually exposes them and the
observation records them.
