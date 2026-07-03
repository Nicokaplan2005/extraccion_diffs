"""
upload_existing.py — sube los diffs locales ya descargados a HuggingFace.

Uso:
    python upload_existing.py <diffs_dir>

diffs_dir: directorio raíz con estructura {owner}/{repo}/{pr_num}.diff
           (el pr_diffs/ local)

Variables de entorno:
    HF_TOKEN    — token HuggingFace con permisos write
    HF_DATASET  — nombre del dataset (ej. nicokaplan/pr-diffs)
"""

import os, sys, time, requests
from pathlib import Path

HF_TOKEN   = os.environ['HF_TOKEN']
HF_DATASET = os.environ.get('HF_DATASET', 'nicokaplan/pr-diffs')
HF_API     = 'https://huggingface.co'
BATCH_SIZE = 200
MAX_RETRIES = 5


def hf_upload_files(files_dict):
    url = f'{HF_API}/api/datasets/{HF_DATASET}/upload/main'
    headers = {'Authorization': f'Bearer {HF_TOKEN}'}
    multipart = []
    for path, content in files_dict.items():
        multipart.append(('file', (path, content, 'text/plain')))
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(url, headers=headers, files=multipart, timeout=120)
            if r.status_code in (200, 201):
                return True
            print(f'  HTTP {r.status_code}: {r.text[:200]}', flush=True)
            time.sleep(10)
        except Exception as e:
            print(f'  error ({attempt+1}): {e}', flush=True)
            time.sleep(10 * (attempt + 1))
    return False


def main():
    diffs_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('pr_diffs')
    if not diffs_dir.exists():
        sys.exit(f'ERROR: {diffs_dir} no existe')

    all_files = sorted(diffs_dir.rglob('*.diff'))
    total = len(all_files)
    print(f'Encontrados {total} diffs en {diffs_dir}', flush=True)

    uploaded = 0
    failed = 0
    batch = {}

    for i, path in enumerate(all_files):
        # path relativa dentro del dataset: pr_diffs/owner/repo/num.diff
        rel = path.relative_to(diffs_dir.parent)
        hf_path = rel.as_posix()

        batch[hf_path] = path.read_bytes()

        if len(batch) >= BATCH_SIZE or i == total - 1:
            ok = hf_upload_files(batch)
            if ok:
                uploaded += len(batch)
            else:
                failed += len(batch)
                print(f'  FALLO lote {len(batch)} archivos', flush=True)
            batch = {}

        if (i + 1) % 1000 == 0:
            pct = (i + 1) / total * 100
            print(f'  {i+1}/{total} ({pct:.0f}%) — ok={uploaded} fail={failed}', flush=True)

    print(f'\nFin. uploaded={uploaded} failed={failed}', flush=True)


if __name__ == '__main__':
    main()
