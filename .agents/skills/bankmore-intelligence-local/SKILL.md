---
name: bankmore-intelligence-local
description: Use when starting or validating BankMore Fraud Intelligence locally on Windows, including the SQLite demo, isolated transfer-to-detector-to-MCP integration, Docker/runtime recovery, and API/Angular startup. Captures verified integration procedures, not production fraud efficacy or LLM quality.
---

# BankMore Intelligence local workflow

**Failure pattern:** Windows sandbox permissions can block Python environment bootstrapping, pytest temporary directories, and Angular/esbuild process creation, making environment failures look like application failures.

**Verified by:** During MVP implementation, dependency installation completed through the global pip interpreter targeting the local venv; 12 tests passed, including a real MCP stdio client/server roundtrip exercising all six tools against the authenticated HTTP API. Angular production build passed and the local investigation page was opened. This evidence applies to the SQLite demo, not production integration or model quality.

## Procedure

1. Locate the actual repository. In the original workspace it is nested at `BankMore/BankMore-Challenge`; implementation was on `codex/fraud-intelligence-mvp`. Check the current checkout before executing commands; do not switch branches merely to match this historical name. Commands below run from that repository root unless stated otherwise.

2. Use Python 3.12 and the repository's Node/Angular requirements. Reuse a working `.venv`. For a fresh environment, start with:

   ```powershell
   python -m venv .venv
   .venv/Scripts/python.exe -m pip install -r investigation/requirements.txt
   ```

   If venv creation fails during `ensurepip` but `.venv/Scripts/python.exe` exists, the verified recovery is to use global pip targeting that interpreter:

   ```powershell
   python -m pip --python .venv/Scripts/python.exe install -r investigation/requirements.txt
   ```

   This recovery required an approved execution outside the restricted sandbox in the original session. Preserve the execution environment's permission flow; this skill does not grant permission or authorize changing system Python.

3. Set the module path and prepare the local demo in this order:

   ```powershell
   $env:PYTHONPATH = 'investigation'
   .venv/Scripts/python.exe -m bankmore_intelligence setup-demo
   .venv/Scripts/python.exe -m bankmore_intelligence seed-demo
   .venv/Scripts/python.exe -m bankmore_intelligence serve
   ```

   `setup-demo` creates ignored `investigation/.env.local` and preserves an existing file. Inspect configuration names without logging secret values if an existing environment behaves differently. The default demo uses persistent SQLite `intelligence.db`, lexical retrieval, and a labeled template-generated opinion. It does not call an LLM. The API binds to `127.0.0.1:5010`.

4. In another terminal, from `frontend`, install and verify the UI:

   ```powershell
   npm ci
   npm run build
   npm start -- --host 127.0.0.1
   ```

   Open `http://localhost:4200/ops/investigacao`. The development UI targets the local API at port 5010. Its review credential comes from `INTELLIGENCE_REVIEW_TOKEN` in `investigation/.env.local`; `INTELLIGENCE_MCP_TOKEN` has the assistant's read/draft role. Never copy these values into documentation, tool output, or source. The UI holds the credential only in memory.

5. From the repository root, with the same module path, run the focused suite:

   ```powershell
   $env:PYTHONPATH = 'investigation'
   .venv/Scripts/python.exe -m pytest investigation/tests -q
   ```

   `investigation/tests/test_mcp_protocol.py` verifies an actual SDK client, stdio server, and authenticated HTTP API over loopback, including tool discovery and calls to all six tools. Tests launch subprocesses and use temporary files. Distinguish permission errors from failed assertions; rerun with the required approved execution permissions when the sandbox is the cause. Report current pass/skip results rather than assuming the historical count remains fixed.

## What did not work

- Sandboxed `python -m venv .venv` failed in `ensurepip`; repeatedly retrying the same bootstrap was not the solution. Global pip with `--python` successfully populated the existing local interpreter.
- Restricted Angular dependency/build execution hit esbuild process `EPERM`. The build passed with approved process permissions; changing application code to address that failure would have targeted the wrong cause.
- Pytest under restricted temporary-directory permissions failed on filesystem access. The normal permission-approved run passed; preserve the real tests rather than weakening them or treating inaccessible temporary files as test failures.

## Verification boundaries

- PostgreSQL was subsequently verified after the user started Docker: 13 tests passed with the database configured, and the isolated Kafka/PostgreSQL/API check passed. Read `investigation/README.md` and `VALIDATION.md` for the reproduction commands and exact boundaries; this does not validate the full .NET/PyFlink/PIX stack.
- Ollama completed a structured-output end-to-end path, but its investigation quality had not been accepted when this workflow was captured. Do not present that path as a verified quality baseline or infer quality from schema validity.
- Demo scenarios and test results do not establish fraud-detection efficacy. Consult current source and documentation before enabling external consumers or changing deployment configuration.

## Verified Docker recovery and connector test

If Docker works but registry downloads of pgvector/Kafka fail with EOF, do not reset
Docker or modify unrelated containers. The verified fallback builds
`investigation/docker/pgvector.Dockerfile` into `bankmore-pgvector:pg16`, using the
official PostgreSQL base and PGDG extension package. Set process environment
`INTELLIGENCE_POSTGRES_IMAGE=bankmore-pgvector:pg16` before Compose commands.

Use `investigation/compose.yml` plus `investigation/compose.integration.yml` and
`--env-file investigation/.env.local`. Build the `intelligence-api` image; start
`intelligence-db` and `intelligence-kafka` with `up -d --build --wait`; then run
`run --rm intelligence-integration-test`. The broker build downloads official
Apache Kafka 3.9.1 and validates SHA-512. The check creates/removes its own random
database and uses a private Kafka network; no banking ledger is involved.

Passing evidence: Kafka delivery, PostgreSQL snapshots, duplicate handling, durable
offsets, malformed/conflicting event quarantine, restart, authenticated report API,
and assistant review denied with HTTP 403. Stop only the test broker afterward.

## Verified transfer → detector → MCP workflow

**Failure pattern:** Docker Hub layer EOFs plus incompatible PyFlink/Beam runtime
dependencies can prevent a real detector from running even though the investigation
unit and protocol tests pass.

**Verified by:** `investigation/scripts/check_live_mcp.py` passed against isolated
`bankmore-live`: actual .NET API/outbox, Kafka, PyFlink/XGBoost, banking worker,
PostgreSQL/pgvector, six MCP tools and Ollama. Control transfer was settled; the
ML-rejected transfer had zero ledger movements; assistant review returned 403.
See `investigation/LIVE_VALIDATION.md` and `live-evidence.json` for the bounded result.

1. Use `investigation/compose.live.yml` for this specific integration, not the
   previous `compose.integration.yml` consumer-only test. Secrets remain in ignored
   `investigation/.env.local`; never print or copy their values into documentation.
2. Identify the process bound to port 5010 before stopping it. An earlier native
   `python -m bankmore_intelligence serve` may occupy the port. The live API replaces
   it at the same port; the SQLite database is preserved. Never stop unrelated apps.
3. Build/start with `docker compose --env-file investigation/.env.local -f
   investigation/compose.live.yml up -d --build --wait`. Use the documented pgvector
   fallback image override if the default pull fails. This stack has separate banks,
   volumes, network and loopback account/transfer ports 5100/5101.
4. Run `index-knowledge` inside `intelligence-api`; do not run `seed-demo`. The live
   runner creates fresh fictitious accounts through HTTP and receives detector
   events, rather than publishing pre-decided alerts itself.
5. Verify ML logs show a Redis connection. The ML app initializes that connection
   at startup; if Redis was initially unavailable, restart only this test ML service
   after correcting Redis, then verify before interpreting the integration result.
6. Run `.venv/Scripts/python.exe investigation/scripts/check_live_mcp.py`. A passing
   result requires real Ollama output and persisted MCP report, plus correct ledger
   outcomes. Inspect the source before running: it creates new local test accounts.
7. The existing Angular page at `/ops/investigacao` and the documented stdio MCP
   config now point to the integrated API. Refresh the queue after the API switch.

### Ruled-out approaches

- Repeated pulls of official Flink/Redis images hit Docker Hub layer EOFs. The local
  fallback builds actual project code on an available Microsoft SDK base.
- Debian's Python 3.11 could not install pemja 0.3.0 build dependencies (NumPy
  1.21.4). The passing PyFlink environment uses managed Python 3.10.19 via uv.
- New setuptools removed `pkg_resources`, needed by Apache Beam in PyFlink 1.18.
  Pinning setuptools 80.9.0 fixed startup. Java 17 support here is experimental;
  do not present this validation runtime as a production recommendation.
- Redis packaged by apt enabled protected mode and rejected peer containers. The
  isolated compose config permits its private peers without publishing a host port.
- FastMCP's unstructured list result is one text block per item, including zero
  blocks for an empty list. Do not unconditionally read `content[0]` for list tools.

This test uses JSON transport and the project's synthetically trained XGBoost.
It does not validate Avro, the PIX/DICT/SPI flow, real customer data, fraud labels,
or semantic correctness of the model's hypotheses. The original GIF predates this
integration; do not silently describe that recording as the newly validated flow.
