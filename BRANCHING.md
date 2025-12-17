# Branching Strategy

## Branches

- **main** - Production-ready code. Railway deploys from this branch. Never push directly without testing.
- **dev** - Development branch for testing new features and experiments. Safe to break.

## Workflow

### Working on New Features/Experiments

```bash
# 1. Switch to dev branch
git checkout dev

# 2. Pull latest changes
git pull origin dev

# 3. Make your changes, test, commit
git add .
git commit -m "Your commit message"

# 4. Push to dev
git push origin dev

# 5. Test thoroughly on dev branch
# Run tests, try features, make sure nothing breaks
```

### Moving Tested Features to Production

```bash
# 1. Switch to main
git checkout main

# 2. Pull latest
git pull origin main

# 3. Merge dev into main
git merge dev

# 4. Push to main (triggers Railway deployment)
git push origin main
```

### Quick Commands Reference

```bash
# See what branch you're on
git branch

# Switch to dev for experiments
git checkout dev

# Switch to main for production
git checkout main

# Create a feature branch off dev
git checkout dev
git checkout -b feature/my-new-feature

# Discard all changes and reset to last commit
git reset --hard HEAD

# See what changed
git status
git diff
```

## Best Practices

1. **Always develop on dev branch** - Keep main stable
2. **Test on dev first** - Make sure everything works before merging to main
3. **Small commits** - Commit often with clear messages
4. **Pull before push** - Always pull latest changes before pushing

## Current Branch Setup

- main → Production (Railway deployment)
- dev → Testing & experiments (safe to break)
