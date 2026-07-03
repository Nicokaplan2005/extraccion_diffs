"""
download_batch.py — descarga diffs de GitHub y los sube a HuggingFace.

Uso:
    python download_batch.py <job_index>

Variables de entorno:
    GH_TOKEN_1 ... GH_TOKEN_4   — tokens de GitHub (rotan por PR)
    HF_TOKEN                    — token HuggingFace con permisos write
    HF_DATASET                  — nombre del dataset (ej. nicokaplan/pr-diffs)
    MAX_PRS                     — (opcional) limitar a N PRs por job, para tests
"""

import os, sys, time, json, requests
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

GH_TOKENS = [t for t in [
    os.environ.get('GH_TOKEN_1'),
    os.environ.get('GH_TOKEN_2'),
    os.environ.get('GH_TOKEN_3'),
    os.environ.get('GH_TOKEN_4'),
] if t]

if not GH_TOKENS:
    sys.exit('ERROR: no hay GH_TOKEN_* en el entorno')

HF_TOKEN   = os.environ['HF_TOKEN']
HF_DATASET = os.environ.get('HF_DATASET', 'nicokaplan/pr-diffs')
HF_API     = 'https://huggingface.co'

MAX_PRS = int(os.environ['MAX_PRS']) if os.environ.get('MAX_PRS') else None

JOBS_FILE    = Path(__file__).parent / 'jobs.json'
OUT_DIR      = Path('/tmp/diffs')
LOG_FILE     = Path('/tmp/download_log.jsonl')
SUMMARY_FILE = Path('/tmp/job_summary.txt')

SLEEP_BETWEEN = 0.25
MAX_RETRIES   = 5
BATCH_UPLOAD  = 200

# ── Helpers ───────────────────────────────────────────────────────────────────

def gh_headers(token_idx):
    tok = GH_TOKENS[token_idx % len(GH_TOKENS)]
    return {
        'Authorization': f'Bearer {tok}',
        'Accept': 'application/vnd.github.diff',
        'User-Agent': 'pr-diff-downloader/1.0',
    }

def download_diff(owner_repo, pr_num, token_idx):
    url = f'https://api.github.com/repos/{owner_repo}/pulls/{pr_num}'
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=gh_headers(token_idx), timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code in (404, 406, 410):
                # 404: PR no existe, 406: diff no disponible, 410: eliminada
                return None
            if r.status_code in (429, 403):
                wait = int(r.headers.get('Retry-After', 60))
                print(f'  rate limit, sleep {wait}s', flush=True)
                time.sleep(wait)
                continue
            print(f'  HTTP {r.status_code} para {owner_repo}#{pr_num}', flush=True)
            time.sleep(5)
        except Exception as e:
            print(f'  error ({attempt+1}/{MAX_RETRIES}): {e}', flush=True)
            time.sleep(5 * (attempt + 1))
    return None

def hf_upload_batch(files_dict):
    """Sube archivos via HuggingFace Hub commit API."""
    url = f'{HF_API}/api/datasets/{HF_DATASET}/commit/main'
    headers = {'Authorization': f'Bearer {HF_TOKEN}'}

    # Primero hacer pre-upload de los blobs
    operations = []
    for hf_path, content_bytes in files_dict.items():
        # Upload blob
        blob_url = f'{HF_API}/api/datasets/{HF_DATASET}/upload/main'
        for attempt in range(MAX_RETRIES):
            try:
                r = requests.post(blob_url, headers=headers,
                                  files=[('file', (hf_path, content_bytes, 'text/plain'))],
                                  timeout=120)
                if r.status_code in (200, 201):
                    break
                print(f'  blob upload {r.status_code}: {r.text[:100]}', flush=True)
                time.sleep(5)
            except Exception as e:
                print(f'  blob error ({attempt+1}): {e}', flush=True)
                time.sleep(10)
        else:
            return False
    return True

def hf_upload_files(files_dict):
    """Sube lote de archivos usando la API de upload de HuggingFace."""
    url = f'{HF_API}/api/datasets/{HF_DATASET}/upload/main'
    headers = {'Authorization': f'Bearer {HF_TOKEN}'}
    multipart = [('file', (path, content, 'text/plain')) for path, content in files_dict.items()]
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(url, headers=headers, files=multipart, timeout=300)
            if r.status_code in (200, 201):
                return True
            print(f'  HF upload HTTP {r.status_code}: {r.text[:200]}', flush=True)
            time.sleep(10)
        except Exception as e:
            print(f'  HF upload error ({attempt+1}): {e}', flush=True)
            time.sleep(10 * (attempt + 1))
    return False

def write_summary(job_idx, downloaded, skipped, failed, total_prs, repos):
    lines = [
        f'## Job {job_idx} — resumen\n',
        f'| | |',
        f'|---|---|',
        f'| PRs asignados | {total_prs} |',
        f'| Descargados y subidos a HF | {downloaded} |',
        f'| No disponibles (404/406) | {skipped} |',
        f'| Fallos de upload | {failed} |',
        f'| Repos | {", ".join(repos)} |',
    ]
    if MAX_PRS:
        lines.insert(1, f'> **TEST MODE**: limitado a {MAX_PRS} PRs por repo\n')
    SUMMARY_FILE.write_text('\n'.join(lines), encoding='utf-8')

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    job_idx = int(sys.argv[1])

    with open(JOBS_FILE) as f:
        jobs = json.load(f)

    if job_idx >= len(jobs):
        sys.exit(f'ERROR: job_idx={job_idx} fuera de rango (hay {len(jobs)} jobs)')

    job = jobs[job_idx]
    total_prs = sum(len(item['prs']) for item in job)

    if MAX_PRS:
        print(f'TEST MODE: max {MAX_PRS} PRs por repo', flush=True)

    print(f'Job {job_idx}: {len(job)} repos, {total_prs} PRs asignados', flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    failed     = 0
    skipped    = 0
    token_idx  = 0
    pending_upload = {}
    repo_names = []

    for item in job:
        repo = item['repo']
        prs  = item['prs'][:MAX_PRS] if MAX_PRS else item['prs']
        repo_names.append(repo)

        print(f'\n── {repo} ({len(prs)} PRs) ──', flush=True)

        for i, pr_num in enumerate(prs):
            hf_path = f'pr_diffs/{repo}/{pr_num}.diff'

            diff_text = download_diff(repo, pr_num, token_idx)
            token_idx += 1

            if diff_text is None:
                skipped += 1
                with open(LOG_FILE, 'a') as lf:
                    lf.write(json.dumps({'repo': repo, 'pr': pr_num, 'status': 'skip'}) + '\n')
            else:
                content_bytes = diff_text.encode('utf-8', errors='replace')
                pending_upload[hf_path] = content_bytes
                downloaded += 1

                local_path = OUT_DIR / repo / f'{pr_num}.diff'
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(content_bytes)

            if len(pending_upload) >= BATCH_UPLOAD:
                ok = hf_upload_files(pending_upload)
                if ok:
                    print(f'  subidos {len(pending_upload)} archivos a HF', flush=True)
                else:
                    failed += len(pending_upload)
                    print(f'  FALLO upload {len(pending_upload)} archivos', flush=True)
                pending_upload = {}

            if (i + 1) % 500 == 0:
                pct = (i + 1) / len(prs) * 100
                print(f'  {repo}: {i+1}/{len(prs)} ({pct:.0f}%) dl={downloaded} skip={skipped}', flush=True)

            time.sleep(SLEEP_BETWEEN)

    if pending_upload:
        ok = hf_upload_files(pending_upload)
        if ok:
            print(f'  subidos {len(pending_upload)} archivos a HF (lote final)', flush=True)
        else:
            failed += len(pending_upload)
            print(f'  FALLO upload lote final {len(pending_upload)} archivos', flush=True)

    print(f'\n=== Job {job_idx} terminado ===', flush=True)
    print(f'  descargados+subidos: {downloaded}', flush=True)
    print(f'  skipped (404/406):   {skipped}', flush=True)
    print(f'  failed upload:       {failed}', flush=True)

    write_summary(job_idx, downloaded, skipped, failed, total_prs, repo_names)

if __name__ == '__main__':
    main()
