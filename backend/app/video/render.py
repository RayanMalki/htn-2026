"""Resumable staged renderer. Run in the worker's cancellable process group."""
import argparse
import hashlib
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import settings
from app.video.plan import VERSION, RenderPlan, atomic_text
from app.video.runtime import probe, valid_media
from app.video.voice import PLAYBACK_SPEED, TONE, alignment_identity


def stage_identity(stage):
    dependencies = {
        'script': ['script.py', 'plan.py'],
        'voice': ['voice.py', 'runtime.py'],
        'cards': ['cards.py', 'cards.mjs'],
        'compose': ['compose.py', 'captions.py', 'post.py', 'runtime.py'],
        'post': ['render.py'], 'captions': ['render.py'],
    }
    from app.video.compose import ENC
    extra = json.dumps(ENC).encode() if stage == 'compose' else b''
    return hashlib.sha256(extra + b''.join((Path(__file__).parent / f).read_bytes()
                                  for f in dependencies[stage])).hexdigest()


def renderer_identity():
    return hashlib.sha256(''.join(stage_identity(s) for s in
        ['script', 'voice', 'cards', 'compose', 'post', 'captions']).encode()).hexdigest()


def fingerprint(case, source_clip, sfx, brainrot, gameplay_path):
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path and Path(path).is_file() else None
    cfg = settings()
    return hashlib.sha256(json.dumps([VERSION, case['id'], case.get('source_url'),
        case['result'].get('analysis'), case['result'].get('claims'), case['result'].get('model_mode'),
        cfg.tts_model, cfg.tts_voice, PLAYBACK_SPEED, TONE, alignment_identity(), digest(source_clip), sfx, brainrot,
        digest(gameplay_path)], sort_keys=True).encode()).hexdigest()[:20]


def timestamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}'


def render_case(case, out_dir, *, sfx=True, brainrot=False, gameplay_path=None, source_clip=None, log=print):
    from app.video import captions, cards, compose, script, voice

    script.eligible_claims(case)
    render_started = time.monotonic()
    reused = []
    root = Path(out_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    artifact = fingerprint(case, source_clip, sfx, brainrot, gameplay_path)
    folder = root / artifact
    folder.mkdir(parents=True, exist_ok=True)
    checkpoint = folder / 'checkpoint.json'
    try:
        saved = json.loads(checkpoint.read_text())
    except (OSError, ValueError):
        saved = {}
    plan = None

    def reusable(stage):
        nonlocal plan
        record = saved.get(stage)
        if not record or record.get('identity') != stage_identity(stage):
            return False
        try:
            for name, digest in record['files'].items():
                path = folder / name
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    return False
            plan = RenderPlan.model_validate(record['plan'])
            return True
        except (OSError, ValueError, KeyError):
            return False

    def progress(stage):
        atomic_text(root / 'progress.json', json.dumps({'stage': stage, 'artifact': artifact,
                    'selected_claim_id': plan.selected_claim_id if plan else None}))
        log(f'  {stage}')

    def commit(stage, files, started):
        plan.stage = stage
        plan.timings[stage] = round(time.monotonic() - started, 3)
        plan.save(folder / 'plan.json')
        saved[stage] = {'identity': stage_identity(stage), 'plan': plan.model_dump(), 'files': {
            str(Path(p).relative_to(folder)): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files}}
        atomic_text(checkpoint, json.dumps(saved))

    prepared_cards = None
    stages_valid = True
    for name in ['script', 'voice', 'cards', 'compose', 'post', 'captions']:
        if stages_valid and reusable(name):
            reused.append(name)
            continue
        stages_valid = False
        # Once a stage is invalid, downstream records must never be reused on a later retry.
        for stale in ['script', 'voice', 'cards', 'compose', 'post', 'captions'][
                ['script', 'voice', 'cards', 'compose', 'post', 'captions'].index(name):]:
            saved.pop(stale, None)
        atomic_text(checkpoint, json.dumps(saved))
        progress(name)
        started = time.monotonic()
        if name == 'script':
            plan = script.build_plan(case, folder, source_clip=source_clip)
            plan.sfx, plan.brainrot, plan.gameplay_path = sfx, brainrot, gameplay_path
            files = []
        elif name == 'voice':
            # Layout depends on text, not narration duration. Prepare it while
            # provider requests and serial alignment run, then merge by scene order.
            with ThreadPoolExecutor(max_workers=1) as executor:
                def layout(card_plan):
                    layout_started = time.monotonic()
                    result = cards.render_cards(card_plan, folder)
                    return result, round(time.monotonic() - layout_started, 3)
                future = executor.submit(layout, plan.model_copy(deep=True))
                plan = voice.synthesize(plan, folder)
                prepared_cards, layout_seconds = future.result()
                plan.timings['card_layout'] = layout_seconds
            files = [plan.voice.audio_path]
        elif name == 'cards':
            if prepared_cards is None:
                plan = cards.render_cards(plan, folder)
            else:
                for scene, card in zip(plan.scenes, prepared_cards.scenes, strict=True):
                    scene.card_png, scene.focus_box = card.card_png, card.focus_box
            files = [s.card_png for s in plan.scenes]
        elif name == 'compose':
            # Captions are applied AFTER optional split-screen layout.
            plan = compose.compose(plan, folder, final=True)
            files = [plan.output_path]
        elif name == 'post':
            # Sound effects and optional layout are included in the final compose pass.
            pass
            files = [plan.output_path]
        else:
            pages = captions.pages(plan)
            if plan.source_clip and plan.source_transcript:
                pages.insert(0, {'start': 0, 'end': plan.source_duration, 'text': plan.source_transcript})
            # Original speech uses a separate VTT cue; do not burn a potentially long
            # segment transcript into a word-sized caption card.
            target = folder / 'response.mp4'
            if Path(plan.output_path) != target:
                shutil.copyfile(plan.output_path, target.with_suffix('.part.mp4'))
                target.with_suffix('.part.mp4').replace(target)
                plan.output_path = str(target)
            vtt = ['WEBVTT\n']
            for p in pages:
                text = p['text'].replace('&', '&amp;').replace('<', '&lt;').replace('-->', '→')
                vtt.append(f"{timestamp(p['start'])} --> {timestamp(p['end'])}\n{text}\n")
            atomic_text(folder / 'captions.vtt', '\n'.join(vtt))
            files = [target, folder / 'captions.vtt']
        commit(name, files, started)
    if not valid_media(plan.output_path, video=True, duration=plan.duration, size=(720, 1280)):
        raise RuntimeError('Final video did not pass media validation.')
    info = probe(plan.output_path)
    if not {'video', 'audio'} <= {s['codec_type'] for s in info['streams']}:
        raise RuntimeError('Final video is missing its audio or video stream.')
    duration = float(info['format']['duration'])
    if not 44.9 <= duration <= 120.1 or plan.voice.engine != 'openai':
        raise RuntimeError('Final video does not meet the narration or duration contract.')
    video = {'status': 'ready', 'stage': 'complete', 'version': VERSION, 'artifact': artifact,
             'selected_claim_id': plan.selected_claim_id, 'selected_claim': plan.claim,
             'duration_seconds': round(duration, 3), 'width': plan.width, 'height': plan.height,
             'voice': settings().tts_voice, 'model': settings().tts_model, 'ai_voice': True,
             'voice_speed': PLAYBACK_SPEED, 'renderer_identity': renderer_identity(),
             'caption_timing': plan.voice.timings_from, 'source_caption_timing': 'segment',
             'sfx': sfx, 'brainrot': brainrot, 'stage_timings': plan.timings,
             'reused_stages': reused, 'render_wall_seconds': round(time.monotonic() - render_started, 3),
             'url': f"/api/cases/{case['id']}/video", 'captions_url': f"/api/cases/{case['id']}/video/captions",
             'sources_url': f"/api/cases/{case['id']}/video/sources"}
    manifest = {'video': video, 'source_url': case.get('source_url'), 'selected_claim_id': plan.selected_claim_id,
                'claim': plan.claim, 'finding': plan.finding.model_dump(),
                'scenes': [s.model_dump(exclude={'card_png'}) for s in plan.scenes],
                'references': [e.model_dump() for e in plan.evidence]}
    atomic_text(folder / 'manifest.json', json.dumps(manifest, indent=2))
    atomic_text(root / 'result.json', json.dumps(video))
    progress('complete')
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case_json')
    parser.add_argument('out_dir')
    parser.add_argument('--source-clip')
    parser.add_argument('--gameplay')
    parser.add_argument('--brainrot', action='store_true')
    parser.add_argument('--no-sfx', action='store_true')
    args = parser.parse_args()
    root = Path(args.out_dir).resolve()
    try:
        render_case(json.loads(Path(args.case_json).read_text()), root, source_clip=args.source_clip,
                    gameplay_path=args.gameplay, brainrot=args.brainrot, sfx=not args.no_sfx)
    except Exception as exc:
        from app.video.script import ScriptBudgetError
        from app.video.voice import NarrationError
        code = 'script_budget_exceeded' if isinstance(exc, ScriptBudgetError) else 'render_failed'
        message = str(exc) if isinstance(exc, (ScriptBudgetError, NarrationError)) else 'Video rendering failed. Retry to resume saved stages.'
        atomic_text(root / 'error.json', json.dumps({'code': code, 'message': message}))
        raise


if __name__ == '__main__':
    main()
