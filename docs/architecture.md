# Architecture

## Pipeline diagram

```mermaid
flowchart LR
    subgraph INPUT["1. INPUT"]
        A1[Web form /\nCLI JSON /\nProduct data]
        A2[Logo + product images]
    end

    subgraph QUEUE["2. QUEUE (unbounded)"]
        B1[(jobs/*.json\nstatus store)]
        B2[InProcessQueue\nqueue.Queue - no max size]
        B3[Worker pool\nN threads/processes]
    end

    subgraph PROCESSING["3. PROCESSING - per job"]
        C1[ScriptGenerator\nproduct -> list[Scene]\n(1 intro + 1/feature + audience + CTA)]
        C2[TTSPipeline\ncloud provider -> flite fallback\nper-scene voiceover .wav]
        C3[SceneRenderer\nPillow -> on-brand 1920x1080 PNG]
        C4[VideoRenderPipeline\ncloud provider -> ffmpeg zoompan fallback\nper-scene silent .mp4 timed to VO]
        C5[Assembler\nmux audio, chapter + concat -c copy,\noptional music bed, .srt captions]
    end

    subgraph OUTPUT["4. OUTPUT"]
        D1[outputs/&lt;slug&gt;_&lt;job&gt;.mp4]
        D2[outputs/&lt;slug&gt;_&lt;job&gt;.srt]
    end

    subgraph DELIVERY["5. NOTIFICATION / DELIVERY"]
        E1[jobs/&lt;job&gt;.json\nstatus=completed]
        E2[Webhook POST\nif notify_webhook set]
        E3[Web dashboard\n/status/&lt;job&gt; polls + shows video]
    end

    A1 --> B1
    A2 --> C3
    B1 --> B2 --> B3
    B3 --> C1 --> C2 --> C3 --> C4 --> C5
    C5 --> D1
    C5 --> D2
    D1 --> E1
    D2 --> E1
    E1 --> E2
    E1 --> E3
```

## Why each stage is built this way

**Input.** `core/models.ProductInput` is a plain dataclass built from either
a JSON file (CLI) or a multipart form (web UI). Nothing about the schema
assumes a fixed number of features or a fixed video length - `features`
is just a list, and its length is what drives everything downstream.

**Queue.** Submitting a job (`job_queue.submit(product)`) writes a
`status="queued"` record to `jobs/<job_id>.json` and puts the product on
an in-memory `queue.Queue`, then returns immediately. A small pool of
worker threads (`VIDEO_BOT_WORKERS` env var, default 2) drains it. This
is what decouples "how many videos have been requested" from "how many
are rendering right now" - see `docs/scaling.md` for the full argument.

**Processing.**
1. `ScriptGenerator` turns the product into an ordered list of `Scene`
   objects: intro, one per feature, an audience beat, a CTA. A
   `TemplateScriptGenerator` (deterministic, offline) is the default; an
   `LLMScriptGenerator` stub shows where a real Claude/GPT call would
   slot in for punchier copy without touching anything downstream.
2. `TTSPipeline` renders each scene's voiceover line to a `.wav`. Default
   provider is ffmpeg's built-in `flite` filter (fully offline). A cloud
   TTS stub is first in the provider chain so a real deployment can
   prefer higher-quality voices and only fall back to local synthesis on
   error/rate-limit.
3. `SceneRenderer` (Pillow) draws a 1920x1080 on-brand slide per scene:
   gradient background from the product's brand color, heading/body
   text, optional logo and product image.
4. `VideoRenderPipeline` turns each slide into a short silent clip with a
   Ken Burns zoom, using ffmpeg's `zoompan` filter, timed exactly to that
   scene's voiceover duration. Same provider-chain pattern as TTS: a
   cloud text-to-video stub could go first.
5. `Assembler` muxes each clip with its voiceover, concatenates
   everything (batched into chapters for very long storyboards, see
   `docs/scaling.md`), optionally lays a soft synthesized ambient bed
   under the mix, and writes an `.srt` caption sidecar timed against the
   real per-scene durations.

**Output.** One `.mp4` (H.264/AAC) and one `.srt` per job, in `outputs/`.

**Delivery.** The same `jobs/<job_id>.json` status file that the queue
uses for progress tracking is updated to `status="completed"` with the
final paths, a webhook POST fires if the caller supplied one, and the
web dashboard's `/status/<job_id>` page polls that file every 1.5s and
shows/download-links the video the moment it's ready.
