# Video stack decisions

What each stage of the rebuttal renderer uses, what was considered, and what was verified. Written Saturday night of the event. Every number that could be wrong carries the URL it came from. Where something could not be verified it says so.

The one rule behind every choice: the visual authority of this video comes from the artifacts being real. A real clip, a real paper page, a real highlighted sentence. Anything that makes a journal page look invented destroys the credibility the whole product rests on.

## Voice

| Engine | What was verified | Verdict |
|---|---|---|
| **ElevenLabs** | `POST /v1/text-to-speech/{voice_id}/with-timestamps`, header `xi-api-key`, body `text`, `model_id` (default `eleven_multilingual_v2`), `voice_settings`, `output_format` (default `mp3_44100_128`, also PCM and WAV). The response carries `alignment.characters`, `character_start_times_seconds`, `character_end_times_seconds`, and a `normalized_alignment` with the same shape. ([endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps), [auth](https://elevenlabs.io/docs/api-reference/authentication)) | **First choice.** Best voice, and the timestamps mean captions come free, no second pass. It is also a sponsor track |
| **OpenAI speech** | `POST https://api.openai.com/v1/audio/speech`, models `gpt-4o-mini-tts`, `tts-1`, `tts-1-hd`, voices alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer, verse, marin, cedar (they recommend marin or cedar), formats mp3, opus, aac, flac, wav, pcm. **No timestamps in the response.** ([guide](https://developers.openai.com/api/docs/guides/text-to-speech)) `tts-1` is $15.00 per million characters, `tts-1-hd` $30.00, `gpt-4o-mini-tts` $0.60 per million input tokens and $12.00 per million output tokens ([pricing](https://developers.openai.com/api/docs/pricing)) | **Second choice.** A 900 character script is about a cent. Needs whisper for word timings |
| **macOS `say`** | On this machine, 37 English voices. Zero cost, offline, no key | **Fallback that can never rate limit you at 2 AM.** It sounds robotic, the video lab proved it |
| **Kokoro** | Apache 2.0, 82 million parameters, `pip install kokoro`, needs `espeak-ng`, PyTorch and soundfile. English, Spanish, French, Hindi, Italian, Japanese, Portuguese, Mandarin ([repo](https://github.com/hexgrad/kokoro)) | Good quality for free, but PyTorch on an 8 GB laptop mid-hackathon is a memory gamble. Not this weekend |
| **Piper** | MIT. **The repository was archived on October 6, 2025** and development moved to `OHF-Voice/piper1-gpl` ([repo](https://github.com/rhasspy/piper)) | Skip |
| **Gemini text to speech** | Two models listed, and both show "Free of charge" on the free tier ([pricing](https://ai.google.dev/pricing)) | Worth knowing. If the team already has a Gemini key it is a free voice with no separate signup. No timestamps documented |

**Engine order in the code:** ElevenLabs when `ELEVENLABS_API_KEY` is set, then OpenAI when `OPENAI_API_KEY` is set, then macOS `say`, then a silent track so a render never fails for lack of a voice.

**ElevenLabs free tier, and the caveat:** 10,000 credits a month, **no commercial licence**, text to speech and sound effects included. Starter is $6 a month for 30,000 credits and the commercial licence ([pricing](https://elevenlabs.io/pricing)). A 45 second script runs 600 to 900 characters, so the free tier is roughly a dozen renders. Cache every generated voice file so a re-render does not spend again.

**The MLH offer:** `https://mlh.link/elevenlabs` resolved to the ElevenLabs documentation landing page with no hackathon-specific offer visible, and a web search found none. **Could not be verified.** Ask the MLH table what the code is and what it unlocks.

## Captions

| Source of word timings | Accuracy | Cost |
|---|---|---|
| **ElevenLabs alignment** | Exact, per character, from the engine that made the audio | Free with the voice call |
| **whisper.cpp on the rendered audio** | Good. `-ml 1` (or `--max-len 1`) gives word level segments, output as json, srt or vtt. Models: tiny 75 MiB, base 142 MiB, small 466 MiB ([repo](https://github.com/ggml-org/whisper.cpp)). The base English model is already on this machine and transcribes a 40 second clip in about 2 seconds | One local pass |
| **Proportional estimate** | Rough. Splits each sentence's duration by word length | Nothing |

**Rule:** transcribe the audio you actually rendered, never derive timings from the script text. The voice engine pauses where it pauses.

**Style that reads on a phone:** two to four words per caption page, high contrast, large, centered in the middle band of the frame. TikTok's own specification says safe zones "vary based on ad caption length and any additional formats used" and only publishes them as downloadable templates ([spec](https://ads.tiktok.com/help/article?aid=9626)). Meta's Reels specification page returned 404 during this check. **Exact safe-zone percentages could not be verified from an official text source.** Working rule until someone opens the template: keep captions and any number that matters inside the middle 60 percent vertically and away from the right 15 percent, where the like, comment and share buttons sit.

## Compositor

**ffmpeg.** Chosen for the repository, and the reason is plain: it is installed in continuous integration already, it renders the 45 second lab video in 27 seconds on this laptop, it has no licence question, and the whole pipeline stays in Python.

**Remotion** was measured in the video lab and its motion is clearly better: the highlight sweeps at reading speed and each reveal lands on the voice cue. It renders in 80 seconds on this laptop, needs 582 MB of packages plus a browser, and its licence is the problem. The free licence covers "an organization or team of individuals with up to 3 people", plus anyone "evaluating whether the Remotion Software is a good fit, and are not yet using it in a commercial way" ([licence FAQ](https://www.remotion.dev/docs/license/faq), [licence](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md)). This team is four. The evaluation clause probably fits a hackathon, and their FAQ says to contact them for confirmation. If it turns out paid, automatic rendering falls under "Remotion for Automators" at $0.01 per render with a $100 per month minimum, and the per-seat Creators plan is $25 a month with a three seat minimum ([pricing](https://www.remotion.pro/license)). Not the $25 per seat total the original plan assumed.

If Remotion confirms the evaluation reading in writing, it is a worthwhile upgrade for the signature paper shot. Until then the repository does not depend on it.

## Transitions and sound

**Transitions:** ffmpeg's `xfade` filter. This build supports 59 transition types. The renderer uses `fade` into the freeze, `smoothup` to pull the paper out, `circleopen` onto the finding, `fadeblack` for the close. Cuts land on narration beats, not on decoration.

**Sound effects, default: synthesized.** A whoosh is shaped noise, a thud is a decaying low sine, a pop is a click of high noise, all generated by ffmpeg from `aevalsrc` and `sine` in under a second. Nothing to download, nothing to license, nothing that can go missing on the venue network.

Downloaded packs are fine as an upgrade, with these terms verified:

- **Freesound**: three licences, CC0 ("you can do pretty much what you want with the sound"), CC-BY ("you should always mention the original creators"), CC-BY-NC (no earning money with the work). An account is required to download ([FAQ](https://freesound.org/help/faq/)). Filter to CC0 and skip the attribution problem.
- **Pixabay**: commercial use allowed, no attribution required, modification allowed, no standalone redistribution, no misleading use ([licence](https://pixabay.com/service/license-summary/)).
- **ElevenLabs sound generation**: `POST https://api.elevenlabs.io/v1/sound-generation`, body `text`, optional `duration_seconds` from 0.5 to 30 and `prompt_influence` from 0 to 1 ([endpoint](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert)). Credit cost per generation was not stated on the page. This is the sponsor-track option: a "whoosh, short, cinematic" prompt in, an mp3 out, and it counts as more of their stack in use.

## The split-screen layer

The format on TikTok: the content sits in the top half or so, a muted gameplay clip loops in the bottom, captions sit near the seam. The renderer's `brainrot` flag builds exactly that, the rebuttal scaled onto a blurred copy of itself in the top 760 pixels and the gameplay cropped to fill the bottom 520.

**The licensing reality:** Subway Surfers is a copyrighted game. Stock sites list hundreds of "Subway Surfers gameplay" clips ([Pixabay search](https://pixabay.com/videos/search/subway%20surfer%20gameplay/), [Pexels search](https://www.pexels.com/search/videos/subway%20surfers%20gameplay/)), but an uploader cannot license a game they do not own, so a capture of the actual game is not covered by the site's licence no matter what the upload page says. From those same searches, pick a **lookalike endless runner or an original 3D render**, which is what a lot of the results are. The code composites whatever sits at the gameplay path and uses a Mandelbrot zoom as the stand-in when nothing is there.

## Platform specifications

**Instagram Reels through the API**, verified from the reference: MOV or MP4, "no edit lists, moov atom at the front of the file", HEVC or H.264 video, AAC audio at 128 kbps, 48 kHz maximum sample rate, mono or stereo, 23 to 60 frames per second, variable bitrate at 25 Mbps maximum, progressive scan, closed group of pictures, maximum width 1920 pixels, aspect ratio "between 0.01:1 and 10:1 but we recommend 9:16", duration 3 seconds to 15 minutes, 300 MB maximum, and the file **must be on a public server** because the API fetches it by URL ([reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media)).

**TikTok through the API**, verified from the media transfer guide: MP4 recommended, WebM and MOV accepted, H.264 recommended, H.265, VP8 and VP9 accepted, 23 to 60 frames per second, 360 to 4096 pixels on each side, up to 10 minutes through the API with actual limits set per account, 4 GB maximum, chunks of 5 to 64 MB ([guide](https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide)). TikTok's ad specification adds 9:16 vertical, at least 540 by 960 pixels, at least 516 kbps ([spec](https://ads.tiktok.com/help/article?aid=9626)).

**What the renderer produces:** 720 by 1280, 30 frames per second, H.264 with `-movflags +faststart` (that is the moov atom at the front), AAC at 160 kbps, 44.1 kHz. That satisfies both platforms. Rendering at 1080 by 1920 costs 2.25 times the pixel work per frame for a difference nobody judging a five minute demo can see on a phone.

## Generated video

Verified prices per second of output:

| Service | Price | Source |
|---|---|---|
| Sora 2 | $0.10 at 720p. Sora 2 pro $0.50 at 1024p, $0.70 at 1080p. Batch is half | [pricing](https://developers.openai.com/api/docs/pricing) |
| Veo 3.1 | Standard $0.40 at 720p and 1080p, Fast $0.10 at 720p, Lite $0.05 at 720p. No free tier | [pricing](https://ai.google.dev/pricing) |
| Runway Gen-4.5 | 60 credits per 5 seconds. On the $12 plan with 625 credits that is about $0.23 a second, on the $76 plan about $0.10 | [pricing](https://runway.com/pricing) |
| Kling | Not verified this session | |

A 45 second rebuttal at the cheapest tier is $4.50 per render, and renders get redone many times. That is the small reason not to use it. The large reason: this project composites real material, the real clip, the real paper page, the real highlighted sentence. The instant a judge sees a journal page that looks invented, the credibility premise collapses. Generated footage is acceptable for a five second opener, pre-rendered once, and never for an evidence shot.
