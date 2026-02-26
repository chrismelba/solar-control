#!/bin/bash

# Script to copy solar-control-dev to solar-control and update version
# Usage: ./copy_dev_to_prod.sh

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right directory structure
if [ ! -d "solar-control-dev" ] || [ ! -d "solar-control" ]; then
    print_error "This script must be run from the directory containing both solar-control-dev and solar-control folders"
    exit 1
fi

print_status "Starting copy from solar-control-dev to solar-control..."

# Copy all files except config.yaml
print_status "Copying files from solar-control-dev to solar-control (excluding config.yaml)..."
rsync -av --exclude='config.yaml' solar-control-dev/ solar-control/

print_success "Files copied successfully"

# Update version in config.yaml
print_status "Updating version in config.yaml..."

# Read current version from dev config
DEV_CONFIG="solar-control-dev/config.yaml"
PROD_CONFIG="solar-control/config.yaml"

if [ ! -f "$DEV_CONFIG" ]; then
    print_error "Development config file not found: $DEV_CONFIG"
    exit 1
fi

if [ ! -f "$PROD_CONFIG" ]; then
    print_error "Production config file not found: $PROD_CONFIG"
    exit 1
fi

# Extract current version from prod config (base for the bump)
CURRENT_VERSION=$(grep "^version:" "$PROD_CONFIG" | sed 's/version: //' | tr -d ' "')
if [ -z "$CURRENT_VERSION" ]; then
    print_error "Could not find version in $PROD_CONFIG"
    exit 1
fi

print_status "Current prod version: $CURRENT_VERSION"

# Parse version components
IFS='.' read -ra VERSION_PARTS <<< "$CURRENT_VERSION"
if [ ${#VERSION_PARTS[@]} -ne 3 ]; then
    print_error "Invalid version format: $CURRENT_VERSION (expected x.y.z)"
    exit 1
fi

MAJOR=${VERSION_PARTS[0]}
MINOR=${VERSION_PARTS[1]}

# Increment minor version, reset patch to 0
NEW_MINOR=$((MINOR + 1))
NEW_VERSION="$MAJOR.$NEW_MINOR.0"

print_status "New version: $NEW_VERSION"

# Update version in both prod and dev configs
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^version:.*/version: \"$NEW_VERSION\"/" "$PROD_CONFIG"
    sed -i '' "s/^version:.*/version: \"$NEW_VERSION\"/" "$DEV_CONFIG"
else
    sed -i "s/^version:.*/version: \"$NEW_VERSION\"/" "$PROD_CONFIG"
    sed -i "s/^version:.*/version: \"$NEW_VERSION\"/" "$DEV_CONFIG"
fi

print_success "Version updated to $NEW_VERSION in $PROD_CONFIG"
print_success "Version updated to $NEW_VERSION in $DEV_CONFIG"

# Verify the changes
UPDATED_PROD=$(grep "^version:" "$PROD_CONFIG" | sed 's/version: //' | tr -d ' "')
UPDATED_DEV=$(grep "^version:" "$DEV_CONFIG" | sed 's/version: //' | tr -d ' "')
if [ "$UPDATED_PROD" = "$NEW_VERSION" ] && [ "$UPDATED_DEV" = "$NEW_VERSION" ]; then
    print_success "Version update verified successfully"
else
    print_error "Version update verification failed. Expected: $NEW_VERSION, Got prod: $UPDATED_PROD, dev: $UPDATED_DEV"
    exit 1
fi

print_success "Copy and version update completed successfully!"
print_warning "Please review the changes before committing to git" 