"""Explicit packaging allowlist; shared by final content review and archiving."""
ROOT_FILES = {'.gitignore', 'README.md', 'DESIGN.md', 'TESTING.md', 'CONTRIBUTIONS.md',
              'COLLABORATION.md', 'PERSONAL_ACCEPTANCE.md', 'DELIVERY.md',
              'requirements.txt', 'requirements-original.txt', 'config.example.json'}
FOLDERS = {'followup', 'tests', 'tools', 'fixtures', 'evidence'}
EXCLUDED_PARTS = {'__pycache__', '.pytest_cache', '.git', 'delivery', '.venv', 'venv', 'node_modules', 'browser-profile'}
EXTENSIONS = {'.py', '.json', '.jsonl', '.md', '.txt', '.sqlite', '.html', '.png'}


def included(root, path):
    parts = path.relative_to(root).parts
    if any(part in EXCLUDED_PARTS for part in parts):
        return False
    if path.name.endswith(('.sqlite-wal', '.sqlite-shm')):
        # Original evidence companions are related artifacts, not cache debris.
        return len(parts) > 2 and parts[0] == 'evidence' and parts[1] == 'personal-review-20261022-164553-252' and path.is_file()
    if path.name.endswith('.pyc'):
        return False
    if parts[0] == 'evidence' and len(parts) > 2 and parts[1].startswith('clean-') and parts[2] == 'workspace':
        return False
    if len(parts) == 1:
        return path.name in ROOT_FILES and path.is_file()
    if parts[0] not in FOLDERS or not path.is_file():
        return False
    if path.suffix.lower() not in EXTENSIONS:
        raise ValueError('交付白名单内出现未审查文件类型：' + str(path.relative_to(root)))
    return True


def delivery_files(root):
    return sorted(path for path in root.rglob('*') if included(root, path))
