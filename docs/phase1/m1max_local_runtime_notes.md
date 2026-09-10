# M1 Max Local Runtime Notes

Date: 2026-06-16

## Ollama Runtime Repair

The M1 Max canonical run used Ollama `0.30.7`, matching the Pi 5 runtime pin.
The Homebrew `ollama` `0.30.7` bottle installed on this host did not include the
`llama-server` binary that the server attempted to launch. A generation probe
failed with:

```text
error starting llama-server: llama-server binary not found
```

The host already had Homebrew `llama.cpp` installed with:

```text
/opt/homebrew/bin/llama-server -> ../Cellar/llama.cpp/9550/bin/llama-server
```

To restore the Ollama server while keeping the Ollama runtime version pinned at
`0.30.7`, the local host was configured with a compatibility symlink at the path
Ollama checks first:

```bash
ln -sf /opt/homebrew/bin/llama-server \
  /opt/homebrew/Cellar/ollama/0.30.7/libexec/lib/ollama/llama-server
```

Generation was re-tested successfully before the canonical run.

## Powermetrics Privilege

The canonical runner requires repeated `powermetrics` reads. GUI
administrator prompts are not stable enough for a 5 warmup + 20 measured run,
so the host was configured with a narrow sudoers rule:

```text
<your-username> ALL=(root) NOPASSWD: /usr/bin/powermetrics
```

The file was validated with:

```bash
visudo -cf /etc/sudoers.d/signal-bench-powermetrics
```

This allows the runner to use `sudo -n powermetrics` reproducibly without
capturing or storing the macOS password.

## FNB58 Charger-Side Validation

The M1 Max canonical run records powermetrics CPU/GPU/ANE power estimates per
invocation in the JSON artifact. Across measured invocations with valid FNB58
coverage, FNB58 charger-side delivery averaged 2.496 W while the mean
powermetrics CPU+GPU+ANE estimate averaged 4.044 W, for an FNB58/SoC ratio of
0.775 (p50 0.729). On the 512-token throughput task specifically, FNB58
averaged 2.478 W and CPU+GPU+ANE averaged 3.781 W, for a ratio of 0.769 (p50
0.741). This is below direct agreement but above the brief's severe
battery-buffering threshold of 0.5, so the M1 Max headline energy should be
interpreted as a charger-side lower-bound wall measurement, not as total system
or chip energy. The report recorded only preflight battery state (`79%; AC
attached; not charging`), and a post-run reference check also showed 79%, but
the canonical run did not log battery state at both start and end; therefore
battery buffering during individual invocations cannot be ruled in or out from
the canonical artifact alone. powermetrics remains supplementary and is the
better proxy for chip-side power on this sealed target.

The M1 Max runner now preflights this condition and aborts when the battery is
below 100% and not actively charging; the Entry 10 canonical run was affected
by that condition and remains labelled as a charger-side lower-bound result.

The clean M1 Max canonical re-run on 2026-06-17 passed the charging preflight
at 100% battery (`finishing charge`) and produced
`data/phase1/m1max/canonical/phase1-m1max-canonical-20260617T025840Z/`. In
that run the measured FNB58/SoC ratio was near agreement: 1.096 mean / 1.029
p50 overall, and 1.031 mean / 0.969 p50 on the 512-token throughput task. This
supersedes the Entry 10 lower-bound artifact for M1 Max energy comparisons.
