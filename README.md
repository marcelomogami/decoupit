# DecoupIt

DecoupIt is a local pre-editing and video review tool designed to prepare long
raw recordings before manual editing in Kdenlive.

## Status

The project is currently in the planning stage. There is no implementation or
installable application yet.

## Goal

DecoupIt aims to reduce the repetitive work that happens before creative video
editing:

- generating a lightweight review proxy;
- producing a searchable, time-aligned transcript;
- identifying topics and repeated takes;
- suggesting primary and alternative takes;
- flagging long pauses, interrupted speech, coughs, and other events for
  review;
- classifying segments as primary, alternative, blooper, or discarded;
- exporting subtitles, review reports, and markers for Kdenlive.

The expected workflow is:

```text
raw video
  -> local analysis and review in DecoupIt
  -> SRT, CSV, and Kdenlive markers
  -> precise editing and final rendering in Kdenlive
```

## Product boundaries

DecoupIt is not intended to replace a nonlinear video editor. It will not
provide advanced timeline editing, effects, color grading, music arrangement,
titles, transitions, or final rendering.

Every automated decision must remain reviewable. The original media is treated
as read-only, and all derived artifacts must be reproducible.

## Planned architecture

- Python 3.12 in an isolated environment
- FastAPI backend bound to localhost
- SQLite for project state and review decisions
- Server-rendered HTML with minimal JavaScript
- FFmpeg and ffprobe for media processing
- NVIDIA NVENC for compatible review proxies
- Faster Whisper for local transcription
- Optional WhisperX alignment when additional timestamp precision is needed
- Kdenlive integration through SRT, CSV, and marker JSON exports

Long-running analysis will execute outside the web process with conservative
memory and concurrency limits.

## Privacy

DecoupIt is planned as a local-only personal tool. Video, audio, transcripts,
and review decisions remain on the user's computer. No cloud service or
telemetry is required by the initial design.
