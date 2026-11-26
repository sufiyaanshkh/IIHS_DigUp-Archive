# Commonly assumed capabilities — investigation incomplete

This document does **not** certify absence across the entire Desktop
repository. The search covered `Sources`, `shell` and `worker` for terms
including `transcrib`, `whisper`, `diariz`, `speech.to.text`, `speech.recogn`,
`translation`, `translate`, `summari[sz]`, and `chat` in Swift, Rust,
JavaScript and Python files. Results included unrelated graphics translation,
clipboard/chat comments and an ML input chat template; none established any
of the capabilities below. Other spellings, files and call paths remain to be
reviewed. Thus every entry is **UNKNOWN / NEEDS INVESTIGATION**, not proven
absent.

| Assumed capability | Current evidence and remaining work |
|---|---|
| Speech-to-text transcription | No implementation found in the scoped search; inspect all media/model paths and dependencies. |
| Live transcription | No implementation found in the scoped search; inspect runtime and UI completely. |
| Translation | No implementation found in the scoped search; graphical coordinate translation is unrelated. |
| Word-level transcript timestamps | No implementation found in the scoped search; inspect transcript producers and stores before concluding absence. |
| Sentence-level transcript timestamps | Same limitation; media-window timestamps do not establish transcript timestamps. |
| Speaker diarization | No implementation found in the scoped search; inspect all audio/model paths. |
| Transcript phrase search | No implementation found in the scoped search; indexed document/OCR text is not an audio transcript. |
| Automatic document summaries | No implementation found in the scoped search; root/index summaries are not document summaries. |
| AI chat | No implementation found in the scoped search; an embedding processor's chat template does not by itself establish a user-facing chat system. |

Desktop [audio window extraction](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Media+Apple.swift)
and [segment storage](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift)
show coarse audio/video segment locations; neither establishes speech recognition.
Do not treat these assumptions as Desktop parity requirements without evidence.
See the [methodology](DIGUP_AUDIT_METHODOLOGY.md) and
[matrix](DIGUP_ATOMIC_PARITY_MATRIX.md).
