#!/bin/bash
# Aurora Econometrica emergency rollback.
# Usage:
#   bash tools/rollback.sh 1.0.8              # dry-run: print actions
#   bash tools/rollback.sh 1.0.8 --execute    # actually run
#
# Полная документация: memory/reference_econometrica_rollback.md
set -e

VER=$1
DRY=1
[ "$2" = "--execute" ] && DRY=0

if [ -z "$VER" ]; then
  echo "Usage: bash tools/rollback.sh <version> [--execute]"
  echo "  version: 1.0.8 или 1.0.9"
  exit 1
fi

# Маппинг версия → tag + SHA256 (обновлять при каждом stable release)
case "$VER" in
  1.0.8)
    TAG="v1.0.8-econometrica"
    SHA256="7eb506e32a89ccf21de540a75787874741043ea6332e4e930f547857f29df511"
    NOTES="v1.0.8 stable (emergency rollback)."
    ;;
  1.0.9)
    TAG="v1.0.9-rc2"
    SHA256="6ae6524d8a235d087ca641000fa4957d3d6ba102598d4114c538eb62c34cf42d"
    NOTES="v1.0.9 stable (emergency rollback)."
    ;;
  *)
    echo "❌ Unsupported version: $VER. Known: 1.0.8, 1.0.9"
    exit 1
    ;;
esac

URL="https://github.com/Ackold26/aurora-releases/releases/download/$TAG/Aurora.AI.Econometrica_${VER}_x64-setup.exe"

echo "╔════════════════════════════════════════════════════╗"
echo "║         Aurora Econometrica Rollback              ║"
echo "╠════════════════════════════════════════════════════╣"
echo "║  Target version: $VER"
echo "║  Tag:            $TAG"
echo "║  URL:            $URL"
echo "║  SHA256:         ${SHA256:0:16}…"
echo "║  Mode:           $([ $DRY -eq 1 ] && echo 'DRY RUN' || echo 'EXECUTE')"
echo "╚════════════════════════════════════════════════════╝"
echo ""
echo "Actions to perform:"
echo ""
echo "1) Mark v1.0.9-rc2 / v1.0.10-rc1 as pre-release (hide from clients):"
echo "   gh release edit <current-stable-tag> --repo Ackold26/aurora-releases --prerelease=true"
echo ""
echo "2) Supabase UPDATE both product keys:"
cat <<EOF
   UPDATE app_versions SET
     version = '$VER',
     download_url = '$URL',
     checksum = 'sha256:$SHA256',
     release_notes = '$NOTES',
     min_version = '1.0.0'
   WHERE product IN ('aurora-econometrica-gui', 'econometrica');
EOF
echo ""
echo "3) Update rosst-updates/aurora-econometrica-gui/latest.json + aurora-econometrica/latest.json"
echo "   to point at $URL with SHA $SHA256"
echo ""
echo "4) Commit + push rosst-updates"
echo ""
echo "5) Verify via curl (wait 30-90s for GH Pages cache):"
echo "   curl -s https://ackold26.github.io/rosst-updates/aurora-econometrica-gui/latest.json | grep version"
echo ""
echo "6) Notify clients via email/chat about rollback (template in runbook)"
echo ""

if [ $DRY -eq 1 ]; then
  echo "⚠ This was a DRY RUN. No changes made."
  echo "  To execute: bash tools/rollback.sh $VER --execute"
  echo "  Full runbook: memory/reference_econometrica_rollback.md"
  exit 0
fi

echo "🚨 EXECUTE mode is placeholder — manual steps required."
echo "   Automatic execution of Supabase/GitHub actions not implemented yet."
echo "   Follow steps 1-6 above manually using runbook."
echo ""
echo "   Reason: rollback touches prod systems (auto-update servers), manual"
echo "   review of each step is safer than automated destructive action."
