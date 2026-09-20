"""Pipeline video artifacts; medical wording comes only from saved verdicts."""
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path

import httpx
import sentry_sdk
from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.http import request
from app.media import run_process
from app.schemas import Passage, Verdict, validate_verdict

VERSION = 2
WIDTH, HEIGHT = 720, 1280
LABELS = {'supports': 'Supported by retrieved evidence', 'contradicts': 'Contradicted by retrieved evidence',
          'uncertain': 'Evidence is uncertain'}


def pages(text, limit=650):
    words, result, current = text.split(), [], ''
    for word in words:
        if current and len(current) + len(word) + 1 > limit:
            result.append(current)
            current = ''
        current = f'{current} {word}'.strip()
    return result + ([current] if current else [])


def storyboard(case):
    result = case['result']
    if result.get('model_mode') != 'live':
        raise ValueError('Narrated medical videos require live analysis')
    claims = result.get('analysis', {}).get('claims', [])
    if not claims:
        raise ValueError('No assessed claims to render')
    scenes = [{'heading': 'A claim is not the evidence.', 'eyebrow': 'HYPECHECK / FACT CHECK',
               'body': f'{len(claims)} spoken claims. A limited literature search. Evidence, in context.',
               'narration': 'This is HypeCheck. Here is what our limited literature search found. This voice is AI generated.',
               'sources': []}]
    references = []
    for index, claim in enumerate(claims, 1):
        item = result.get('claims', {}).get(claim['id'], {})
        if item.get('status') != 'complete' or not item.get('verdict'):
            raise ValueError('All selected claims must have validated verdicts before rendering')
        evidence = [Passage.model_validate(p) for p in item.get('evidence', [])]
        verdict = validate_verdict(Verdict.model_validate(item['verdict']), evidence)
        by_id = {p.id: p for p in evidence}
        refs = []
        for citation in verdict.citations:
            p = by_id[citation.passage_id]
            ref = {'number': len(references) + 1, 'claim_id': claim['id'], 'title': p.title,
                   'url': p.source_url, 'access_type': p.access_type, 'paper_id': p.paper_id,
                   **citation.model_dump()}
            references.append(ref)
            refs.append(ref)
        claim_text = f"Claim {index}. {claim['text']}"
        for part in pages(claim_text):
            scenes.append({'eyebrow': f'CLAIM {index} / {len(claims)}', 'heading': 'What the video says',
                           'body': part, 'narration': part, 'sources': []})
        assessment = verdict.explanation
        for part in pages(assessment):
            scenes.append({'eyebrow': f'CLAIM {index} / EVIDENCE', 'heading': LABELS[verdict.label],
                           'body': part, 'narration': f"{LABELS[verdict.label]}. {part}", 'sources': refs})
        # Limitations are carried verbatim, not dropped to make a stronger-sounding video.
        if verdict.limitations:
            for part in pages(' '.join(verdict.limitations)):
                scenes.append({'eyebrow': f'CLAIM {index} / CONTEXT', 'heading': 'What this cannot tell us',
                               'body': part, 'narration': part, 'sources': refs})
    end = 'This search is not exhaustive. These findings are not personalized medical advice. Read the linked evidence and its limitations before drawing conclusions.'
    omitted = result.get('analysis', {}).get('omitted_claims', 0)
    if omitted:
        end += f' {omitted} additional claims in the original video were not assessed.'
    scenes.append({'eyebrow': 'HYPECHECK / KEEP THE CONTEXT', 'heading': 'Check the source.',
                   'body': end, 'narration': end, 'sources': []})
    if len(scenes) > 30 or sum(len(s['narration']) for s in scenes) > 14000:
        raise ValueError('The cited script exceeds the bounded video budget')
    return scenes, references


def font(size, bold=False):
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    for path in [Path('/usr/share/fonts/truetype/dejavu') / name,
                 Path('/usr/local/share/fonts') / name, Path(name)]:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def wrap(draw, text, face, width):
    lines = []
    current = ''
    for word in text.split():
        test = f'{current} {word}'.strip()
        if draw.textlength(test, font=face) > width and current:
            lines.append(current)
            current = word
        else:
            current = test
        # Split long unbroken strings so they cannot overflow a card.
        while draw.textlength(current, font=face) > width:
            cut = len(current) - 1
            while cut > 1 and draw.textlength(current[:cut], font=face) > width:
                cut -= 1
            lines.append(current[:cut])
            current = current[cut:]
    if current:
        lines.append(current)
    return lines


def card(scene, index, count, path):
    im = Image.new('RGB', (WIDTH, HEIGHT), '#f5f5e9')
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, WIDTH, 16), fill='#bcdb87')
    d.text((54, 62), 'HypeCheck.', font=font(34, True), fill='#233f32')
    d.text((54, 150), scene['eyebrow'], font=font(18, True), fill='#607a53')
    y = 213
    for line in wrap(d, scene['heading'], font(46, True), 612):
        d.text((54, y), line, font=font(46, True), fill='#233f32')
        y += 58
    y += 36
    for size in range(32, 19, -1):
        face = font(size)
        lines = wrap(d, scene['body'], face, 604)
        if y + len(lines) * (size + 12) <= 950:
            break
    else:
        raise ValueError('Video card text does not fit; refusing clipped output')
    for line in lines:
        d.text((58, y), line, font=face, fill='#344c3c')
        y += size + 12
    d.line((54, 990, 666, 990), fill='#ccd7bd', width=2)
    refs = scene['sources']
    if refs:
        numbers = ', '.join(str(r['number']) for r in refs)
        d.text((54, 1010), f'CITED SOURCES [{numbers}]', font=font(17, True), fill='#607a53')
        ref = refs[0]
        title_lines = wrap(d, ref['title'], font(19), 612)
        for i, line in enumerate(title_lines[:2]):
            suffix = '…' if i == 1 and len(title_lines) > 2 else ''
            d.text((54, 1043 + i * 26), line + suffix, font=font(19), fill='#344c3c')
        source = f"{ref['paper_id']} / {ref['access_type'].replace('_', ' ')}"
        d.text((54, 1100), source, font=font(17), fill='#607a53')
    else:
        d.text((54, 1020), 'A limited search. No numerical truth score.', font=font(22), fill='#607a53')
    d.text((54, 1168), 'AI-generated voice / Sources linked with video', font=font(17), fill='#607a53')
    d.text((54, 1200), f'{index + 1:02} / {count:02}', font=font(18, True), fill='#233f32')
    d.rectangle((54, 1240, 54 + int(612 * (index + 1) / count), 1245), fill='#829e5e')
    im.save(path)


async def speech(text, output):
    cfg = settings()
    if not cfg.openai_api_key:
        raise RuntimeError('OPENAI_API_KEY is required for narrated video')
    with sentry_sdk.start_span(op='gen_ai.request', name='Generate video narration') as span:
        span.set_data('gen_ai.request.model', cfg.tts_model)
        async with httpx.AsyncClient(timeout=35) as client:
            response = await request(client, 'POST', 'https://api.openai.com/v1/audio/speech',
                headers={'Authorization': f'Bearer {cfg.openai_api_key}'},
                json={'model': cfg.tts_model, 'voice': cfg.tts_voice, 'input': text,
                      'instructions': 'Read the supplied text exactly, clearly and calmly as an evidence explainer. Do not add words.',
                      'response_format': 'mp3'})
        output.write_bytes(response.content)


async def media_info(path):
    raw = await run_process('ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json',
                            str(path), timeout=5)
    info = json.loads(raw)
    duration = float(info['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Generated media has invalid duration')
    return duration, info


def timestamp(seconds):
    millis = round(seconds * 1000)
    return f'{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02}.{millis % 1000:03}'


async def render_video(case):
    cfg = settings()
    scenes, references = storyboard(case)
    digest = hashlib.sha256(json.dumps([VERSION, scenes, cfg.tts_model, cfg.tts_voice], sort_keys=True).encode()).hexdigest()[:20]
    root = cfg.media_root / case['id'] / 'video'
    folder = root / digest
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'response.mp4'
    manifest_file = folder / 'manifest.json'
    if target.exists() and manifest_file.exists():
        return json.loads(manifest_file.read_text())['video']
    voice_gate = asyncio.Semaphore(3)
    render_gate = asyncio.Semaphore(2)

    async def scene_job(index, scene):
        audio = folder / f'{index:02}.mp3'
        png = folder / f'{index:02}.png'
        clip = folder / f'{index:02}.mp4'
        if not audio.exists():
            async with voice_gate:
                tmp = audio.with_suffix('.part.mp3')
                await speech(scene['narration'], tmp)
                await media_info(tmp)
                tmp.replace(audio)
        duration, _ = await media_info(audio)
        await asyncio.to_thread(card, scene, index, len(scenes), png)
        if not clip.exists():
            async with render_gate:
                tmp = clip.with_suffix('.part.mp4')
                await run_process('ffmpeg', '-nostdin', '-y', '-v', 'error', '-loop', '1', '-framerate', '24',
                    '-i', str(png), '-i', str(audio), '-t', str(duration + 0.25),
                    '-af', 'apad', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-threads', '2',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2',
                    '-movflags', '+faststart', str(tmp), timeout=60)
                await media_info(tmp)
                tmp.replace(clip)
        clip_duration, _ = await media_info(clip)
        return clip_duration

    async with asyncio.TaskGroup() as group:
        jobs = [group.create_task(scene_job(i, scene)) for i, scene in enumerate(scenes)]
    durations = [job.result() for job in jobs]
    concat = folder / 'concat.txt'
    concat.write_text(''.join(f"file '{i:02}.mp4'\n" for i in range(len(scenes))))
    temporary = folder / 'response.part.mp4'
    await run_process('ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', str(concat),
                      '-c', 'copy', '-movflags', '+faststart', str(temporary), timeout=20)
    duration, info = await media_info(temporary)
    if not {'video', 'audio'} <= {s['codec_type'] for s in info['streams']}:
        raise ValueError('Rendered video must contain video and narration')
    os.replace(temporary, target)
    subtitles = ['WEBVTT\n']
    start = 0
    for scene, length in zip(scenes, durations, strict=True):
        scene['start'] = round(start, 3)
        scene['end'] = round(start + length, 3)
        # Sentence-sized captions use proportional timings; scene timing comes from actual audio.
        parts = pages(scene['narration'], 100)
        weight = sum(len(p) for p in parts)
        cursor = start
        for part in parts:
            end = cursor + length * len(part) / weight
            subtitles.append(f'{timestamp(cursor)} --> {timestamp(end)}\n{part.replace("-->", "→").replace("<", "&lt;")}\n')
            cursor = end
        start += length
    (folder / 'captions.vtt').write_text('\n'.join(subtitles))
    video = {'status': 'ready', 'version': VERSION, 'artifact': digest,
             'duration_seconds': round(duration, 3), 'width': WIDTH, 'height': HEIGHT,
             'voice': cfg.tts_voice, 'ai_voice': True, 'caption_timing': 'approximate',
             'url': f"/api/cases/{case['id']}/video", 'captions_url': f"/api/cases/{case['id']}/video/captions",
             'sources_url': f"/api/cases/{case['id']}/video/sources"}
    manifest = {'video': video, 'source_url': case['source_url'], 'scenes': scenes, 'references': references}
    manifest_file.write_text(json.dumps(manifest, indent=2))
    return video
