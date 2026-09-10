# Phase 1 Host VLM Feasibility Note

Date: 2026-06-08

## Finding

VLM execution is deferred for this host-only brief.

The current Phase 1 harness contract is text-generation only:
`GenerationRequest` carries a prompt and decode parameters, and
`Phase1Workload` contains text `PromptCase` entries. Adding VLM support cleanly
requires extending the workload/request schema to carry image assets, media
metadata, and VLM-specific scoring inputs.

The host runtimes do not currently provide a clean no-rework VLM path:

- Ollama has only local text models installed: `qwen2.5:7b`,
  `llama3.2:latest`, and `nemotron-3-nano:4b`.
- llama.cpp now provides `llama-mtmd-cli`, but no pinned local multimodal model
  and matching projector artifact are staged in the repo or Ollama store.

## Decision

Do not force VLM into this brief. The second-runtime objective is satisfied by
running the pinned SLM through Ollama and llama.cpp. VLM should be added in a
separate change that introduces:

- a multimodal workload/request schema,
- pinned image fixtures,
- a pinned small VLM plus projector or runtime-native equivalent,
- VLM scoring criteria,
- and per-runtime adapter support for image inputs.

Until then, Phase 1 host reports should describe the current host slice as SLM
coverage, with VLM coverage deferred.
