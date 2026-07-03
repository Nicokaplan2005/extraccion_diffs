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
from queue import Queue
from threading import Thread, Lock
from huggingface_hub import HfApi, CommitOperationAdd

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

MAX_RETRIES  = 3
BATCH_UPLOAD = 300   # subir a HF cada N archivos
N_THREADS    = len(GH_TOKENS)  # un thread por token

# ── Contadores compartidos ────────────────────────────────────────────────────

lock         = Lock()
results      = {'downloaded': 0, 'skipped': 0, 'failed': 0}
pending_hf   = {}   # {hf_path: content_bytes} — se drena cada BATCH_UPLOAD

# ── Helpers ───────────────────────────────────────────────────────────────────

def gh_headers(token_idx):
    return {
        'Authorization': f'Bearer {GH_TOKENS[token_idx % len(GH_TOKENS)]}',
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
                return None
            if r.status_code in (429, 403):
                wait = int(r.headers.get('Retry-After', 60))
                print(f'  [{token_idx}] rate limit {wait}s', flush=True)
                time.sleep(wait)
                continue
            time.sleep(3)
        except Exception as e:
            time.sleep(3 * (attempt + 1))
    return None

_hf_api = HfApi(token=HF_TOKEN)

def hf_upload_files(files_dict):
    operations = [
        CommitOperationAdd(path_in_repo=path, path_or_fileobj=content)
        for path, content in files_dict.items()
    ]
    for attempt in range(MAX_RETRIES):
        try:
            _hf_api.create_commit(
                repo_id=HF_DATASET,
                repo_type='dataset',
                operations=operations,
                commit_message=f'upload {len(operations)} diffs',
            )
            return True
        except Exception as e:
            print(f'  HF error ({attempt+1}): {e}', flush=True)
            time.sleep(10 * (attempt + 1))
    return False

def flush_pending():
    """Toma los archivos pendientes y los sube a HF. Llamar con lock adquirido."""
    global pending_hf
    if not pending_hf:
        return
    batch = dict(pending_hf)
    pending_hf = {}
    # Soltar lock mientras se hace el upload (puede tardar)
    lock.release()
    ok = hf_upload_files(batch)
    lock.acquire()
    if ok:
        print(f'  subidos {len(batch)} archivos a HF', flush=True)
    else:
        results['failed'] += len(batch)
        print(f'  FALLO upload {len(batch)} archivos', flush=True)

# ── Worker ────────────────────────────────────────────────────────────────────

def worker(token_idx, queue):
    global pending_hf
    while True:
        try:
            repo, pr_num = queue.get_nowait()
        except Exception:
            break

        hf_path   = f'pr_diffs/{repo}/{pr_num}.diff'
        diff_text = download_diff(repo, pr_num, token_idx)

        with lock:
            if diff_text is None:
                results['skipped'] += 1
                with open(LOG_FILE, 'a') as lf:
                    lf.write(json.dumps({'repo': repo, 'pr': pr_num, 'status': 'skip'}) + '\n')
            else:
                content_bytes = diff_text.encode('utf-8', errors='replace')
                pending_hf[hf_path] = content_bytes
                results['downloaded'] += 1

                local_path = OUT_DIR / repo / f'{pr_num}.diff'
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(content_bytes)

                if len(pending_hf) >= BATCH_UPLOAD:
                    flush_pending()

        queue.task_done()

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

    print(f'Job {job_idx}: {len(job)} repos, {total_prs} PRs | {N_THREADS} threads', flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Llenar la queue con todos los (repo, pr_num)
    queue = Queue()
    repo_names = []
    for item in job:
        repo = item['repo']
        prs  = item['prs'][:MAX_PRS] if MAX_PRS else item['prs']
        repo_names.append(repo)
        for pr_num in prs:
            queue.put((repo, pr_num))

    total_queued = queue.qsize()
    print(f'PRs en queue: {total_queued}', flush=True)

    start = time.time()

    # Lanzar un thread por token
    threads = [Thread(target=worker, args=(i, queue), daemon=True) for i in range(N_THREADS)]
    for t in threads:
        t.start()

    # Reportar progreso cada 30s desde el main thread
    last_report = start
    while any(t.is_alive() for t in threads):
        time.sleep(5)
        now = time.time()
        if now - last_report >= 30:
            with lock:
                dl = results['downloaded']
                sk = results['skipped']
            elapsed = now - start
            rate = (dl + sk) / elapsed * 60 if elapsed > 0 else 0
            remaining = total_queued - dl - sk
            print(f'  progreso: {dl+sk}/{total_queued} ({rate:.0f}/min) | dl={dl} skip={sk} | ~{remaining/rate:.0f}min restantes' if rate > 0 else f'  progreso: {dl+sk}/{total_queued}', flush=True)
            last_report = now

    for t in threads:
        t.join()

    # Subir lo que quedó pendiente
    with lock:
        flush_pending()

    elapsed = time.time() - start
    rate = (results['downloaded'] + results['skipped']) / elapsed * 60

    print(f'\n=== Job {job_idx} terminado en {elapsed/60:.1f} min ===', flush=True)
    print(f'  velocidad: {rate:.0f} PRs/min', flush=True)
    print(f'  descargados+subidos: {results["downloaded"]}', flush=True)
    print(f'  skipped (404/406):   {results["skipped"]}', flush=True)
    print(f'  failed upload:       {results["failed"]}', flush=True)

    lines = [
        f'## Job {job_idx} — resumen\n',
        f'| | |',
        f'|---|---|',
        f'| PRs asignados | {total_prs} |',
        f'| Velocidad | {rate:.0f} PRs/min |',
        f'| Descargados y subidos a HF | {results["downloaded"]} |',
        f'| No disponibles (404/406) | {results["skipped"]} |',
        f'| Fallos de upload | {results["failed"]} |',
        f'| Repos | {", ".join(repo_names)} |',
    ]
    if MAX_PRS:
        lines.insert(1, f'> **TEST MODE**: limitado a {MAX_PRS} PRs por repo\n')
    SUMMARY_FILE.write_text('\n'.join(lines), encoding='utf-8')

if __name__ == '__main__':
    main()
