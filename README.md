# PR Diffs Downloader

Descarga 426,199 diffs de GitHub y los sube al dataset HuggingFace `nicokaplan/pr-diffs`.

## Setup (una sola vez)

### 1. Crear el repo en GitHub

Crear un repo nuevo (puede ser privado). Subir este directorio completo como contenido del repo:

```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/<tu-user>/<repo-name>.git
git push -u origin main
```

### 2. Configurar secrets en GitHub

En Settings → Secrets and variables → Actions → New repository secret:

| Secret | Valor |
|--------|-------|
| `GH_TOKEN_1` | ghp_eaLetk8... |
| `GH_TOKEN_2` | ghp_8jE9Av... |
| `GH_TOKEN_3` | ghp_t8JvgB... |
| `GH_TOKEN_4` | ghp_IeFzUX... |
| `HF_TOKEN` | hf_LyNjLz... |

### 3. Crear el dataset en HuggingFace (si no existe)

En https://huggingface.co/new-dataset: nombre `pr-diffs`, tipo Dataset, visibilidad pública o privada.

---

## Correr los workflows

### Descargar los 426,199 diffs nuevos

En Actions → "Download PR Diffs" → Run workflow.

- `job_start`: 0 (default)
- `job_end`: 43 (default, corre los 44 jobs en paralelo)

Cada job baja ~10k PRs en ~3-5 horas. Los 44 corren en paralelo simultáneamente.

Para rerunear solo algunos jobs (ej. los que fallaron):
- `job_start`: 5
- `job_end`: 8

### Subir los diffs locales existentes (~50k)

Los 49,962 diffs que ya tenemos están excluidos de `jobs.json` (no se re-descargan).
Para subirlos a HuggingFace corrés esto directo desde la máquina local:

```bash
cd "C:/Users/nicok/Luno/early_grapes/code agent"
HF_TOKEN=<tu_token> HF_DATASET=nicokaplan/pr-diffs \
python extraccion_diffs_github_actions/scripts/upload_existing.py pr_diffs/
```

---

## Estructura del dataset en HuggingFace

```
pr_diffs/
  rails/rails/
    1234.diff
    5678.diff
  kubernetes/kubernetes/
    ...
```

---

## jobs.json

El archivo `scripts/jobs.json` tiene 44 entradas. Cada entrada es una lista de `{repo, prs}`.
Total: 426,199 PRs distribuidos en jobs de ~10k cada uno.
