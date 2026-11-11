# `lba` command line reference

Three subcommands: `lba run` (one task), `lba eval` (the eval suite, see [EVALS.md](EVALS.md)) and
`lba mcp` (stdio MCP server).

## Exit codes

| code | meaning | `lba run` | `lba eval` | `lba mcp` |
| --- | --- | --- | --- | --- |
| 0 | success | run status `success` | all gates passed; `--compare` OK; `--list` / `--self-test` OK | server exited normally |
| 1 | the work failed | status `failed`, `timeout`, `stopped` or `error` with any other `error_kind` (`agent_error`, `timeout`, `captcha`, `stopped`, `start_url_blocked`) | a gate failed (`--fail-under`, `--fail-on-violation`), the run was cut short by `--budget-minutes`, or every run errored for a non-infrastructure reason; `--compare` found a regression, new safety violation or missing task (or a warning with `--strict`); `--self-test` failed | not used |
| 2 | usage or configuration error | bad flags, empty task, malformed `--cdp-url` / `--start-url`, unwritable `--trace`, invalid `LBA_*` values or a `config` error raised once the run started (`error_kind` `config`) | bad flags or config (`usage`, `config`); **every run** failed with `config` and nothing else; `--compare` with unreadable or invalid files (`invalid_input`) or an invalid comparison (different task set, too few runs, mostly infra errors) | invalid `LBA_*` configuration, or the `mcp` extra is missing |
| 3 | environment not ready | `chrome_missing`, `preflight`, `cdp_connect` | pre-flight failed (`chrome_missing`, `preflight`); **every run** failed with an infra kind (`chrome_missing`, `preflight`, `cdp_connect`, or `config` mixed with one of those), even with fewer runs than `--max-infra-errors`; or the run was aborted after `--max-infra-errors` consecutive infra errors | not used |
| 130 | interrupted (Ctrl-C) | yes | not used | not used |

A `config` error means the same thing in both commands: fix the configuration (exit 2), whether it was
found before or during the run.

## stdout and stderr

stderr is human text only. It is never machine-parseable and its wording may change; parse stdout
with `--json`, or use the exit code.

| mode | `lba run` | `lba eval` | `lba mcp` |
| --- | --- | --- | --- |
| human (default) | stdout: status / steps / cost / result summary. stderr: logs and `lba run: error: ...` lines | stdout: progress lines (`[PASS]`, `[FAIL]`, `[INFRA]`), summary, and the `--list`, `--self-test` and `--compare` output. stderr: `lba eval: error: ...`, `gate: ...` lines and `reports written to <dir>` | stdout carries only the MCP JSON-RPC stream (stray prints are redirected to stderr). stderr: warnings and errors |
| `-q` / `--quiet` | stdout: as human. stderr: errors only, no logs | stdout: only `--list`, `--self-test` and `--compare` output. stderr: errors and `gate:` lines; no progress, summary or results path | stderr: errors only |
| `--json` | stdout: exactly one JSON document. stderr: errors only (logs off unless `--log-level` is given) | stdout: exactly one JSON document. stderr: all human text (progress, summary, comparison table, results path) | n/a |

## JSON documents

### `lba run --json`

Always one document, on success and failure: the `RunResult` (`run_id`, `task`, `status`, `success`,
`final_result`, `step_count`, `duration_s`, `cost_usd`, `errors`, `blocked_actions`, ...) plus
`error_kind` (`null` on success). Failures before a run starts (usage, config, pre-flight, interrupt)
use the same shape with `status: "error"` (`"stopped"` for Ctrl-C), `success: null` and the problems
in `errors`. `lba run` has a single `error_kind`; several config problems appear as several
entries in `errors`, so it has no `error_kinds`.

### `lba eval --json`

Success (a real run): the results document (`schema_version`, `meta`, `provider`, `model`,
`timestamp`, `summary`, `tasks`, `runs`; see [EVALS.md](EVALS.md)) plus `"out"`, the absolute path
of the results directory. In `summary`, `success_rate` and `mean_score` are `null` when there were no
valid (non-infra) runs, and a `category_pass_rates` entry is `null` for a category with no valid runs.

Failure (usage, config, pre-flight, `--compare` input, all runs infra errors):

```json
{
  "status": "error",
  "error_kind": "chrome_missing",
  "error_kinds": ["chrome_missing", "preflight"],
  "errors": ["...", "..."]
}
```

`error_kind` is the first kind (`usage`, `config`, `invalid_input`, `chrome_missing`, `preflight`,
`cdp_connect`). `error_kinds` lists all distinct kinds in order and is present when the failure can
have several (pre-flight; all runs infra errors). Neither case creates the `--out` directory (a
pre-existing one is left alone). When `--max-infra-errors` aborts a run that had some valid runs, the
results document is printed instead, with exit 3.

Other modes: `--list` prints an array of tasks, `--self-test` an object with `ok`, `tasks` and
`site_problems`, and `--compare` the comparison (`exit_code`, `ok`, `tasks`, `warnings`, `problems`,
`invalid_reasons`; an invalid task has `delta: null`).

### `lba mcp`

No JSON document: the server speaks MCP over stdio. A startup failure prints
`lba mcp: error: ...` on stderr and exits 2.
