# FrameForge Architecture

FrameForge uses a decoupled, multi-stage pipeline processing architecture to prevent arbitrary limits on video generation.

```mermaid
graph TD
    A[Input Data: JSON Metadata + Brand Assets] --> B[Script Generation Module]
    B --> C{Processing Pipeline}
    
    subgraph Scene Rendering
        C --> D[Cloud TTS / Local Flite]
        C --> E[Visual Rendering: Pillow]
        D --> F[Timing & Sync Calculation]
    end
    
    F --> G[Video Assembly via FFmpeg]
    E --> G
    G --> H[Output: Final MP4 Video]
    H --> I[Web Dashboard Notification / CLI Exit]
```

## Tool/API Choices

* **Google Gemini API**: Used for advanced script generation and high-quality Neural TTS. Selected for its fast inference speed and natural voice prosody.
* **ElevenLabs**: Serves as a premium fallback neural TTS provider.
* **FFmpeg**: Industry standard for robust, frame-accurate video multiplexing and hardware acceleration.
* **Flask**: Provides a lightweight, accessible web dashboard for non-technical users.
