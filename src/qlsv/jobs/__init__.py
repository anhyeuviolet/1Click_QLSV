"""Job runner package (Plan 02-03).

Splits into three modules:

- ``runner``    — ``run_job``, the asyncio.Lock-guarded subprocess spawner.
- ``history``   — append-only ring buffer at ``/var/lib/qlsv/jobs.json``
                  (uses ``qlsv._atomic.write_json`` per H-6).
- ``log_stream``— SSE tail-file generator + ``validate_job_id`` regex.

The web routes in ``qlsv.web.services`` and ``qlsv.web.jobs`` are the only
intended callers; tests monkeypatch ``SCRIPT`` / ``JOB_LOG_DIR`` / ``JOBS_FILE``.
"""
