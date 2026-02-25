#!/usr/bin/env bash
# scripts/fly-setup.sh — First-time Fly.io setup for CallMe/Pronto
#
# Prerequisites:
#   brew install flyctl   (or see https://fly.io/docs/flyctl/install/)
#   fly auth login
#
# Usage:
#   ./scripts/fly-setup.sh
#
# This script:
#   1. Creates the Fly app (if not exists)
#   2. Creates a persistent volume for SQLite
#   3. Imports secrets from your local .env file
#   4. Deploys the app

set -euo pipefail

APP_NAME="callme-pronto"
REGION="lhr"

echo "🚀 CallMe/Pronto — Fly.io Setup"
echo "================================"
echo ""

# ── Check flyctl is installed ────────────────────────────────────
if ! command -v fly &>/dev/null; then
    echo "❌ flyctl not found. Install it:"
    echo "   brew install flyctl"
    echo "   or: curl -L https://fly.io/install.sh | sh"
    exit 1
fi

# ── Check logged in ─────────────────────────────────────────────
if ! fly auth whoami &>/dev/null; then
    echo "🔑 Not logged in to Fly.io. Running 'fly auth login'..."
    fly auth login
fi

echo "✅ Logged in as: $(fly auth whoami)"
echo ""

# ── Create app (idempotent) ──────────────────────────────────────
if fly apps list | grep -q "$APP_NAME"; then
    echo "✅ App '$APP_NAME' already exists"
else
    echo "📦 Creating app '$APP_NAME' in region $REGION..."
    fly apps create "$APP_NAME" --machines
    echo "✅ App created"
fi
echo ""

# ── Create volume (idempotent) ───────────────────────────────────
if fly volumes list -a "$APP_NAME" 2>/dev/null | grep -q "callme_data"; then
    echo "✅ Volume 'callme_data' already exists"
else
    echo "💾 Creating 1GB volume 'callme_data' in $REGION..."
    fly volumes create callme_data --size 1 --region "$REGION" -a "$APP_NAME" -y
    echo "✅ Volume created"
fi
echo ""

# ── Import secrets from .env ─────────────────────────────────────
ENV_FILE="${1:-.env}"
if [[ -f "$ENV_FILE" ]]; then
    echo "🔐 Importing secrets from $ENV_FILE..."
    # Read .env, skip comments and blank lines, set as Fly secrets
    SECRETS=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip comments and blank lines
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        # Skip lines without =
        [[ "$line" != *"="* ]] && continue
        KEY="${line%%=*}"
        VALUE="${line#*=}"
        # Only import known secret keys (not DATABASE_URL, SEED_DEMO, etc.)
        case "$KEY" in
            CALLME_API_KEY|CALLME_ENCRYPTION_KEY|\
            TWILIO_ACCOUNT_SID|TWILIO_AUTH_TOKEN|\
            TWILIO_API_KEY_SID|TWILIO_API_KEY_SECRET|\
            TWILIO_PHONE_NUMBER|\
            DEEPGRAM_API_KEY|\
            ELEVENLABS_API_KEY|ELEVENLABS_VOICE_ID|\
            OPENAI_API_KEY|\
            CALLME_FALLBACK_NUMBER|\
            GOOGLE_CLIENT_ID|GOOGLE_CLIENT_SECRET)
                SECRETS="$SECRETS $KEY=$VALUE"
                echo "   ✓ $KEY"
                ;;
        esac
    done < "$ENV_FILE"

    if [[ -n "$SECRETS" ]]; then
        # shellcheck disable=SC2086
        fly secrets set $SECRETS -a "$APP_NAME"
        echo "✅ Secrets imported"
    else
        echo "⚠️  No secrets found in $ENV_FILE"
    fi
else
    echo "⚠️  No .env file found at '$ENV_FILE'. Set secrets manually:"
    echo "   fly secrets set CALLME_API_KEY=your-key -a $APP_NAME"
fi
echo ""

# ── Deploy ───────────────────────────────────────────────────────
echo "🚢 Deploying to Fly.io..."
fly deploy --ha=false -a "$APP_NAME"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "🌐 Your app is live at: https://$APP_NAME.fly.dev"
echo ""
echo "Next steps:"
echo "  • Open https://$APP_NAME.fly.dev in your browser"
echo "  • Log in with demo@callme.ai / your CALLME_API_KEY"
echo "  • Set your Twilio webhook to: https://$APP_NAME.fly.dev/twilio/incoming"
echo ""
echo "Useful commands:"
echo "  fly logs -a $APP_NAME          # View logs"
echo "  fly ssh console -a $APP_NAME   # SSH into the machine"
echo "  fly deploy --ha=false          # Re-deploy after changes"
echo "  fly secrets list -a $APP_NAME  # List configured secrets"
