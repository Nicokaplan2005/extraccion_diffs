#!/bin/bash
# Corre esto una sola vez despues de crear el repo.
# Requiere tener `gh` instalado y autenticado (gh auth login).
#
# Uso:
#   cd extraccion_diffs_github_actions
#   bash setup_secrets.sh <owner/repo>
#
# Ejemplo:
#   bash setup_secrets.sh nicokaplan/pr-diffs-downloader

REPO=${1:?'Usage: setup_secrets.sh <owner/repo>'}

# Lee los tokens de .secrets (no commiteado)
if [ ! -f .secrets ]; then
  echo "ERROR: falta .secrets — copia secrets.example y completa los valores"
  exit 1
fi
source .secrets

gh secret set GH_TOKEN_1 --body "$GH_TOKEN_1" --repo "$REPO"
gh secret set GH_TOKEN_2 --body "$GH_TOKEN_2" --repo "$REPO"
gh secret set GH_TOKEN_3 --body "$GH_TOKEN_3" --repo "$REPO"
gh secret set GH_TOKEN_4 --body "$GH_TOKEN_4" --repo "$REPO"
gh secret set HF_TOKEN   --body "$HF_TOKEN"   --repo "$REPO"

echo "Secrets configurados en $REPO"
