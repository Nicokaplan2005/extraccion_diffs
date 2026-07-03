"""
check_progress.py — consulta HuggingFace y reporta cuántos diffs hay por repo.

Compara contra jobs.json para saber qué porcentaje lleva cada repo.

Variables de entorno:
    HF_TOKEN    — token HuggingFace
    HF_DATASET  — nombre del dataset (ej. nicokaplan/pr-diffs)
"""

import os, sys, json, requests
from pathlib import Path
from collections import defaultdict

HF_TOKEN   = os.environ['HF_TOKEN']
HF_DATASET = os.environ.get('HF_DATASET', 'nicokaplan/pr-diffs')
HF_API     = 'https://huggingface.co'

JOBS_FILE = Path(__file__).parent / 'jobs.json'


def hf_list_files(prefix='pr_diffs'):
    """Lista todos los archivos del dataset bajo prefix/ usando la tree API."""
    url = f'{HF_API}/api/datasets/{HF_DATASET}/tree/main/{prefix}'
    headers = {'Authorization': f'Bearer {HF_TOKEN}'}
    files_by_repo = defaultdict(int)
    page = 0

    while True:
        r = requests.get(url, headers=headers, params={'recursive': 'true', 'p': page}, timeout=60)
        if r.status_code != 200:
            print(f'HF tree API error {r.status_code}: {r.text[:200]}', flush=True)
            break
        data = r.json()
        if not data:
            break
        for entry in data:
            if entry.get('type') == 'file':
                # path: pr_diffs/owner/repo/num.diff → owner/repo
                parts = entry['path'].split('/')
                if len(parts) >= 4:
                    repo = f'{parts[1]}/{parts[2]}'
                    files_by_repo[repo] += 1
        # HF tree API pagina de a 1000 con campo "truncated"
        if not any(e.get('type') == 'directory' for e in data) and len(data) < 1000:
            break
        page += 1

    return dict(files_by_repo)


def main():
    print('Consultando HuggingFace...', flush=True)
    on_hf = hf_list_files()

    with open(JOBS_FILE) as f:
        jobs = json.load(f)

    # Total PRs a bajar por repo (de jobs.json)
    to_download = defaultdict(int)
    for job in jobs:
        for item in job:
            to_download[item['repo']] += len(item['prs'])

    all_repos = sorted(set(list(on_hf.keys()) + list(to_download.keys())))
    total_target = sum(to_download.values())
    total_done   = sum(on_hf.get(r, 0) for r in all_repos)

    print(f'\n## Progreso global: {total_done:,} / {total_target:,} ({total_done/total_target*100:.1f}%)\n')
    print(f'| Repo | En HF | A bajar | % |')
    print(f'|---|---|---|---|')

    for repo in all_repos:
        done   = on_hf.get(repo, 0)
        target = to_download.get(repo, 0)
        pct    = done / target * 100 if target else 100.0
        bar    = '#' * int(pct / 5) + '.' * (20 - int(pct / 5))
        print(f'| {repo} | {done:,} | {target:,} | {pct:.0f}% |')

    print(f'\nTotal en HF: {total_done:,}')
    print(f'Total objetivo: {total_target:,}')
    print(f'Faltantes: {total_target - total_done:,}')


if __name__ == '__main__':
    main()
