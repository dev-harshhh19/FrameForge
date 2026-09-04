# How this design avoids hard caps on video count, length, and frequency

The assignment specifically warns against just *claiming* "no limits."
Here is exactly what in the code backs that claim, mapped to the three
axes it asks about.

## 1. No cap on video **count**

- `core/queue_manager.InProcessQueue` wraps a plain `queue.Queue()`, which
  has no `maxsize` set. `submit()` never checks a counter against a
  limit - it writes a status file and enqueues. A burst of 500 submit
  calls returns 500 job ids immediately; nothing rejects request #201.
- Every job's state lives in its own file, `jobs/<job_id>.json`, so the
  number of concurrently-tracked jobs is bounded only by disk, not by an
  in-memory structure that would need pre-sized capacity.
- Because rendering is decoupled from submission, "how fast can users ask
  for videos" and "how fast can we make them" are two different numbers.
  The queue absorbs the difference instead of one throttling the other.

## 2. No cap on video **length**

- `ScriptGenerator.generate()` produces exactly `1 + len(features) + (1 if
  target_audience) + 1` scenes - there is no `[:N]` truncation of the
  features list anywhere in the codebase. Feed it 3 features or 300 and
  it produces 3 or 300 feature scenes.
- Per-scene duration is *derived*, not configured: `scene.duration` comes
  from `TTSResult.duration_sec`, i.e. however long ffmpeg/flite actually
  took to say that line. `LocalKenBurnsProvider.render_clip` renders the
  video clip to match that exact duration (`-t {duration_sec}`). There is
  no `MAX_SCENE_SECONDS` constant.
- The one place a "cap-shaped" number appears is `CHAPTER_SIZE = 12` in
  `core/assembler.py`, and it is explicitly *not* a limit - it's a
  batching unit. `concat_in_chapters()` groups clips into chapters of 12,
  stream-copies (`-c copy`, no re-encode) each chapter, then stream-copies
  the chapters together into the final file. A 500-scene storyboard just
  means ~42 chapter-concat calls instead of 1 - constant memory per call,
  linear total time, same output. Raising or removing `CHAPTER_SIZE`
  only changes how the work is batched, never whether it completes.
- Using stream-copy concatenation (rather than re-encoding the whole
  timeline at the end) means cost scales with *added* content, not with
  *total accumulated* content - there's no quadratic blowup as videos get
  longer.

## 3. No cap on generation **frequency**

- Nothing in the codebase implements a rate limiter, a per-hour quota, or
  a cooldown between jobs. The practical ceiling is whatever the *local*
  machine's CPU/ffmpeg throughput allows, which is a horizontal-scaling
  problem, not a policy limit:
  - Increase `VIDEO_BOT_WORKERS` to use more CPU cores on one machine.
  - Run additional worker processes (even on other machines) pointed at
    the same `jobs/`/`work outputs/` paths (e.g. a shared volume, or swap
    `InProcessQueue` for Celery + Redis/SQS - the `submit`/`worker_loop`
    interface is the same shape either way, see the module docstring in
    `queue_manager.py`).
- The one place frequency limits *do* legitimately exist is **outside**
  this codebase: any cloud TTS/text-to-video API has its own rate limits.
  That's handled, not ignored:
  - `TTSPipeline` and `VideoRenderPipeline` (in `tts_providers.py` /
    `video_providers.py`) wrap a *chain* of providers with retry +
    exponential backoff (`max_retries`, `backoff_base`). A 429 or timeout
    from the primary (cloud) provider triggers a retry, and if that
    provider keeps failing, the pipeline automatically falls through to
    the next provider in the chain - by default, the fully local
    ffmpeg/flite renderer, which has no external quota at all.
  - This means a spike in demand that exhausts a cloud provider's quota
    degrades gracefully to local rendering instead of failing the job.

## What would need to change for real production scale

This design is honest about being a single-box reference implementation.
For real production volume, the parts to swap (interfaces already drawn
to make this a small diff, not a rewrite):

| Piece | Here | Production swap |
|---|---|---|
| Queue | `queue.Queue` in one process | Celery / RQ + Redis or SQS |
| Workers | Python threads | Separate worker containers/pods, autoscaled on queue depth |
| Storage | local `outputs/`/`jobs/` folders | S3/GCS for video files, Postgres/DynamoDB for job status |
| TTS/video providers | local ffmpeg | Real cloud provider as primary, local renderer kept as the fallback tier (chain already supports this) |
