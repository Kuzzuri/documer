repo="$1"
blacklist=('node_modules' 'venv' 'env' 'vendor' 'dist' 'build' 'target' 'temp' 'tmp' 'docs' 'examples' 'test' 'tests' 'locale' '.*' '*.log')

for blacklisted in "${blacklist[@]}"; do
    find "$repo" -name "$blacklisted" -exec rm -rf {} +
done