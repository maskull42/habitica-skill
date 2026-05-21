#!/bin/sh
# Install the Habitica skill into Claude Code's personal skills directory.
#
# Default: symlink (edits to the repo stay live). Use --copy to copy instead.
# Usage:
#   ./install.sh            # symlink ~/.claude/skills/habitica -> this repo
#   ./install.sh --copy     # copy the skill instead of symlinking
#   SKILLS_DIR=/path ./install.sh   # override the target skills directory
set -eu

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC="$REPO_DIR/skills/habitica"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.claude/skills}"
DEST="$SKILLS_DIR/habitica"
MODE="symlink"

[ "${1:-}" = "--copy" ] && MODE="copy"

if [ ! -f "$SRC/SKILL.md" ]; then
    echo "error: $SRC/SKILL.md not found; run this from the cloned repo." >&2
    exit 1
fi

mkdir -p "$SKILLS_DIR"

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
    if [ -L "$DEST" ]; then
        echo "Removing existing symlink $DEST"
        rm -f "$DEST"
    else
        echo "error: $DEST already exists and is not a symlink." >&2
        echo "       Remove or rename it, then re-run." >&2
        exit 1
    fi
fi

if [ "$MODE" = "copy" ]; then
    cp -R "$SRC" "$DEST"
    echo "Copied skill to $DEST"
else
    ln -s "$SRC" "$DEST"
    echo "Linked $DEST -> $SRC"
fi

chmod +x "$SRC/scripts/habitica.py" 2>/dev/null || true

cat <<'EOF'

Next steps:
  1. Configure credentials (one of):
       export HABITICA_USER_ID="your-user-id"
       export HABITICA_API_TOKEN="your-api-token"
     or create ~/.config/habitica/credentials (chmod 600) with those KEY=VALUE lines.
     Find both at https://habitica.com/user/settings/api
  2. Restart Claude Code so it picks up the new skill.
  3. Try it:  ask "show my Habitica todos", or run
       python3 ~/.claude/skills/habitica/scripts/habitica.py stats
EOF
