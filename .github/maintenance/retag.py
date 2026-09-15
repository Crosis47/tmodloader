import concurrent.futures, json, re, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
REPO = 'Crosis47/tmodloader'
IMAGE = 'ghcr.io/crosis47/tmodloader'
def run(args, data=None, allow_missing=False):
    result = subprocess.run(args, input=json.dumps(data) if data is not None else None, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        if allow_missing and re.search(r'404|not found|manifest unknown', result.stderr, re.I):
            return None
        raise RuntimeError(f'{args[0:4]} failed: {result.stderr}')
    return result.stdout

def api(path, data=None, method=None):
    args = ['gh', 'api', f'repos/{REPO}/{path}']
    if method: args += ['--method', method]
    if data is not None: args += ['--input', '-']
    return json.loads(run(args, data))

def manifest(tag, missing=False):
    result = run(['docker', 'buildx', 'imagetools', 'inspect', tag, '--format', '{{json .Manifest}}'], allow_missing=missing)
    return json.loads(result) if result else None

def flatten(name):
    pages = json.loads((ROOT / name).read_text(encoding='utf-8-sig'))
    return [item for page in pages for item in page]

def preflight():
    releases = flatten('releases-before.json')
    refs = {item['ref']: item['object'] for item in flatten('refs-before.json')}
    plan = []
    for release in releases:
        match = re.fullmatch(r'(\d+\.\d+\.\d+)\+tml\.(v[\d.]+)\.(stable|preview)', release['tag_name'])
        if not match: continue
        version, tml, channel = match.groups()
        assert tuple(map(int,version.split('.'))) < (3,0,1)
        assert not release['draft'] and not release['immutable']
        assert release['prerelease'] == (channel == 'preview')
        new = version + ('-preview' if channel == 'preview' else '')
        assert not any(r['tag_name'] == new for r in releases), f'Release collision: {new}'
        old_image = f'{version}-tml-{tml.replace(".", "-")}-{channel}'
        digests = re.findall(re.escape(IMAGE) + r'@(sha256:[a-f0-9]{64})', release['body'])
        assert len(set(digests)) == 1
        obj = refs[f'refs/tags/{release["tag_name"]}']
        assert obj['type'] == 'commit', f'Expected lightweight source tag: {obj}'
        existing = refs.get(f'refs/tags/{new}')
        assert existing is None or existing == obj, f'Git tag collision: {new}'
        assert release['target_commitish'] == obj['sha']
        section = f'''## Published images

- GitHub Release tag: `{new}`
- Version tag: `{IMAGE}:{new}`
- Immutable tested digest: `{IMAGE}@{digests[0]}`

```bash
docker pull {IMAGE}:{new}
```

'''
        body, count = re.subn(r'## Published images\n.*?(?=## Validation)', lambda _: section, release['body'], flags=re.S)
        assert count == 1
        (ROOT / f'{new}-notes.md').write_text(body, encoding='utf-8')
        plan.append(dict(id=release['id'], old=release['tag_name'], new=new, old_image=old_image, digest=digests[0], sha=obj['sha'], prerelease=release['prerelease'], body=body))
    assert len({p['new'] for p in plan}) == len(plan)
    def check(p):
        old = manifest(f'{IMAGE}:{p["old_image"]}')
        assert old['digest'] == p['digest'], f'Original digest mismatch: {p["old"]}'
        new = manifest(f'{IMAGE}:{p["new"]}', missing=True)
        assert new is None or new['digest'] == p['digest'], f'Image tag collision: {p["new"]}'
        p['image_exists'] = new is not None
        p['platforms'] = [f'{m["platform"]["os"]}/{m["platform"]["architecture"]}' for m in old.get('manifests', []) if m.get('platform', {}).get('os') == 'linux']
        return p
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        plan = list(pool.map(check, plan))
    baseline = {tag:manifest(f'{IMAGE}:{tag}')['digest'] for tag in ['3.0.1','3.0.1-preview','latest','stable','preview']}
    assert api('releases/latest')['tag_name'] == '3.0.1'
    (ROOT/'plan.json').write_text(json.dumps(dict(releases=plan, baseline=baseline), indent=2),encoding='utf-8')
    rows = ['# Historical release retag plan', '', '| Existing release | New release and image tag | Original commit |', '| --- | --- | --- |']
    for p in plan:
        rows.append(f'| {p["old"]} | {p["new"]} | {p["sha"][:12]} |')
        print(f'{p["old"]} -> {p["new"]}: digest verified', flush=True)
    (ROOT/'plan.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    print(f'Preflight passed for {len(plan)} historical releases; latest and channel baselines saved.', flush=True)

def apply():
    state = json.loads((ROOT/'plan.json').read_text(encoding='utf-8'))
    for p in state['releases']:
        release = api(f'releases/{p["id"]}')
        assert release['tag_name'] in [p['old'],p['new']]
        assert release['target_commitish'] == p['sha']
        current_image = manifest(f'{IMAGE}:{p["new"]}', missing=True)
        if current_image is None:
            run(['docker','buildx','imagetools','create','--prefer-index=false','--tag',f'{IMAGE}:{p["new"]}',f'{IMAGE}@{p["digest"]}'])
        assert manifest(f'{IMAGE}:{p["new"]}')['digest'] == p['digest']
        refs = api(f'git/matching-refs/tags/{p["new"]}')
        exact = [r for r in refs if r['ref'] == f'refs/tags/{p["new"]}']
        if exact:
            assert exact[0]['object']['sha'] == p['sha']
        else:
            api('git/refs',dict(ref=f'refs/tags/{p["new"]}',sha=p['sha']),method='POST')
        result = api(f'releases/{p["id"]}',dict(tag_name=p['new'],name=f'Container v{p["new"]}',body=p['body'],make_latest='false'),method='PATCH')
        assert result['tag_name'] == p['new'] and result['body'] == p['body']
        assert result['prerelease'] == p['prerelease']
        with (ROOT/'applied.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps(dict(tag=p['new'],id=p['id'],digest=p['digest'],url=result['html_url']))+'\n')
        print(f'Published and renamed {p["new"]}; original digest preserved.',flush=True)
    verify()

def verify():
    state = json.loads((ROOT/'plan.json').read_text(encoding='utf-8'))
    def check(p):
        release=api(f'releases/{p["id"]}')
        assert release['tag_name']==p['new'] and release['name']==f'Container v{p["new"]}'
        assert release['body']==p['body'] and release['prerelease']==p['prerelease']
        assert not release['draft']
        assert api(f'git/ref/tags/{p["new"]}')['object']['sha']==p['sha']
        assert api(f'git/ref/tags/{p["old"]}')['object']['sha']==p['sha']
        assert manifest(f'{IMAGE}:{p["new"]}')['digest']==p['digest']
        assert manifest(f'{IMAGE}:{p["old_image"]}')['digest']==p['digest']
        return p['new']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        verified=list(pool.map(check,state['releases']))
    for tag,digest in state['baseline'].items():
        assert manifest(f'{IMAGE}:{tag}')['digest']==digest, f'Moving tag changed: {tag}'
    assert api('releases/latest')['tag_name']=='3.0.1'
    (ROOT/'verification.json').write_text(json.dumps(dict(verified=verified,unchanged=state['baseline'],latest='3.0.1'),indent=2),encoding='utf-8')
    print(f'Verified all {len(verified)} renamed releases, Git refs, image digests, and preserved original tags. 3.0.1 remains latest; channel aliases unchanged.',flush=True)

if __name__ == '__main__':
    {'preflight':preflight,'apply':apply,'verify':verify}[sys.argv[1]]()
