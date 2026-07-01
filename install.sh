#!/usr/bin/env bash
#
# spotify-to-tidal — Install the Spotify → Tidal Migration Skill
#
# Detects installed AI coding tools and installs this skill into each.
# Usage:
#   ./install.sh                  # Interactive (pick tools)
#   ./install.sh --all            # Install to every detected tool
#   ./install.sh --claude         # Claude Code / Claude Desktop only
#   ./install.sh --opencode       # OpenCode only
#   ./install.sh --cursor         # Cursor (native skills) only
#   ./install.sh --codex          # Codex CLI only
#   ./install.sh --cline          # VS Code / Cursor Cline extension only
#   ./install.sh --pi             # Pi coding agent only
#   ./install.sh --help           # Show this help

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_NAME="spotify-to-tidal"

# ── Colours ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ ok ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
err()   { echo -e "${RED}[error]${NC} $*" >&2; }

# ── Detect tools ─────────────────────────────────────────────────────────
detect_tools() {
  TOOLS=()

  # Claude Code & Claude Desktop (share the same personal skills directory)
  if [ -d "$HOME/.claude" ]; then
    TOOLS+=("claude:$HOME/.claude/skills")
  fi

  # OpenCode
  if [ -d "$HOME/.config/opencode" ]; then
    TOOLS+=("opencode:$HOME/.config/opencode/skills")
  fi

  # Cursor (native Agent Skills)
  if [ -d "$HOME/.cursor" ]; then
    TOOLS+=("cursor:$HOME/.cursor/skills")
  fi

  # Codex CLI — gate on a real Codex install, not just the shared .agents
  # folder (that folder is a cross-tool convention several other tools,
  # including Pi, also write to, so its presence alone isn't proof of Codex)
  if command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ]; then
    TOOLS+=("codex:$HOME/.agents/skills")
  fi

  # Cline (VS Code or Cursor extension) — single shared global path,
  # regardless of which editor hosts the extension
  if [ -d "$HOME/.cline" ]; then
    TOOLS+=("cline:$HOME/.cline/skills")
  fi

  # Pi coding agent
  if [ -d "$HOME/.pi" ]; then
    TOOLS+=("pi:$HOME/.pi/agent/skills")
  fi
}

# ── Install to a single target ───────────────────────────────────────────
install_to() {
  local tool_name="$1"
  local target_dir="$2"
  local dest="$target_dir/$SKILL_NAME"

  mkdir -p "$dest"

  # Copy skill files
  cp "$REPO_DIR/SKILL.md" "$dest/" 2>/dev/null || warn "No SKILL.md at root"

  # Copy sub-skill dirs if they exist
  if [ -d "$REPO_DIR/spotify" ]; then
    cp -r "$REPO_DIR/spotify" "$dest/"
  fi
  if [ -d "$REPO_DIR/tidal" ]; then
    cp -r "$REPO_DIR/tidal" "$dest/"
  fi
  if [ -d "$REPO_DIR/reports" ]; then
    cp -r "$REPO_DIR/reports" "$dest/"
  fi

  # Copy README/LICENSE as reference docs (not loaded by the AI, but handy)
  if [ -f "$REPO_DIR/README.md" ]; then
    cp "$REPO_DIR/README.md" "$dest/"
  fi
  if [ -f "$REPO_DIR/LICENSE" ]; then
    cp "$REPO_DIR/LICENSE" "$dest/"
  fi

  ok "Installed to ${BOLD}$tool_name${NC} → $dest"
}

# ── Interactive prompt ───────────────────────────────────────────────────
prompt_yn() {
  local tool_name="$1"
  local default="${2:-y}"
  if [ "$default" = "y" ]; then
    printf "Install to ${BOLD}%s${NC}? [Y/n] " "$tool_name"
  else
    printf "Install to ${BOLD}%s${NC}? [y/N] " "$tool_name"
  fi
  read -r reply
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy] ]] || [[ "$reply" =~ ^[Yy]es$ ]]
}

# ── Main ─────────────────────────────────────────────────────────────────
main() {
  detect_tools

  if [ ${#TOOLS[@]} -eq 0 ]; then
    err "No supported AI tools detected!"
    echo "  Checked:"
    echo "    ~/.claude          (Claude Code / Claude Desktop)"
    echo "    ~/.config/opencode (OpenCode)"
    echo "    ~/.cursor          (Cursor)"
    echo "    codex in PATH, or ~/.codex (Codex CLI)"
    echo "    ~/.cline           (VS Code / Cursor Cline extension)"
    echo "    ~/.pi              (Pi coding agent)"
    echo ""
    echo "Install one of these tools first, then re-run this script."
    exit 1
  fi

  echo ""
  echo -e "${BOLD}Spotify → Tidal Migration Skill — Installer${NC}"
  echo ""
  echo -e "Detected ${#TOOLS[@]} AI tool(s) on this system."
  echo ""

  # ── Parse flags ──────────────────────────────────────────────────────
  local install_all=false
  local install_targets=()

  for arg in "$@"; do
    case "$arg" in
      --all)        install_all=true ;;
      --claude)     install_targets+=("claude") ;;
      --opencode)   install_targets+=("opencode") ;;
      --cursor)     install_targets+=("cursor") ;;
      --codex)      install_targets+=("codex") ;;
      --cline)      install_targets+=("cline") ;;
      --vscode)     install_targets+=("cline") ;; # alias for --cline
      --pi)         install_targets+=("pi") ;;
      --help|-h)
        sed -n '2,/^$/p' "$0" | sed 's/^# //; s/^#$//'
        exit 0
        ;;
      *)
        err "Unknown flag: $arg"
        exit 1
        ;;
    esac
  done

  local installed=0
  local skipped=0

  for entry in "${TOOLS[@]}"; do
    local tool_name="${entry%%:*}"
    local tool_dir="${entry#*:}"

    local do_install=false
    if [ "$install_all" = true ]; then
      do_install=true
    elif [ ${#install_targets[@]} -gt 0 ]; then
      # Check if this tool is in the requested targets
      for target in "${install_targets[@]}"; do
        if [ "$target" = "$tool_name" ]; then
          do_install=true
          break
        fi
      done
    else
      # Interactive mode
      echo -e "  ${CYAN}◉${NC} ${BOLD}$tool_name${NC} found at $tool_dir"
      if prompt_yn "${tool_name}"; then
        do_install=true
      fi
    fi

    if [ "$do_install" = true ]; then
      install_to "$tool_name" "$tool_dir"
      installed=$((installed + 1))
    else
      echo -e "  ${YELLOW}○${NC} Skipped ${BOLD}$tool_name${NC}"
      skipped=$((skipped + 1))
    fi
  done

  echo ""
  echo -e "${GREEN}Done!${NC} Installed to $installed tool(s), skipped $skipped."
  echo ""
  echo -e "Next step:"
  echo -e "  1. Create a working directory with your ${BOLD}spotify-to-tidal.env${NC} check README file on git!"
  echo -e "  2. Open your AI tool in that directory"
  echo -e "  3. Say: ${CYAN}\"Migrate my music from Spotify to Tidal\"${NC}"
  echo ""
  echo -e "See ${BOLD}README.md${NC} for detailed setup instructions."
}

main "$@"