# Feynman Research Runner

This checkout can run Feynman from the repository root through:

```bash
scripts/feynman-research doctor
scripts/feynman-research lit "your literature review topic"
```

The wrapper resolves the repository root and passes it to Feynman with `--cwd`,
so commands run with `<local-path>` as their working directory
even if invoked from elsewhere.

Current local setup checked on 2026-06-06:

- Feynman binary: `<local-path>`
- alphaXiv auth: configured
- authenticated models: 83
- default model: `amazon-bedrock/amazon.nova-2-lite-v1:0`
- web access: Pi web-access, auto route
- session storage: `<local-path>`

Use `FEYNMAN_BIN=/path/to/feynman scripts/feynman-research ...` to override the
binary path.
