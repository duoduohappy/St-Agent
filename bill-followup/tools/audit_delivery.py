"""Read-only content review; patterns are indicators, not proof of all possible secrets."""
import base64
import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from delivery_files import delivery_files

sys.stdout.reconfigure(encoding='utf-8')
parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
patterns = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'openai_style_key': re.compile(r'(?<![\w-])sk-[A-Za-z0-9_-]{24,}'),
    'github_style_token': re.compile(r'(?<!\w)(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})'),
    'aws_access_key': re.compile(r'(?<!\w)AKIA[0-9A-Z]{16}(?!\w)'),
    'bearer_value': re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._-]{24,}'),
    'email_address': re.compile(r'(?<!\w)[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?!\w)'),
    'china_mobile': re.compile(r'(?<!\w)(?:\+86[- ]?)?1[3-9][0-9]{9}(?!\w)'),
    'china_identity': re.compile(r'(?<!\w)[1-9][0-9]{5}(?:19|20)[0-9]{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])[0-9]{3}[0-9Xx](?!\w)'),
}
forbidden_names = {'auth.json', '.env', 'id_rsa', 'id_ed25519', 'credentials', 'Cookies', 'Login Data'}
findings = []
files = delivery_files(root)
text_count = db_count = png_count = sidecar_count = 0


def scan(path, text):
    for label, pattern in patterns.items():
        matches = list(pattern.finditer(text))
        if matches:
            findings.append({'file': path.relative_to(root).as_posix(), 'indicator': label, 'count': len(matches),
                             'values_not_printed': True, 'match_sha256': [hashlib.sha256(m.group().encode('utf-8')).hexdigest() for m in matches]})


for path in files:
    if path.name in forbidden_names or path.suffix.lower() in {'.pem', '.key', '.pfx', '.p12'}:
        findings.append({'file': path.relative_to(root).as_posix(), 'indicator': 'credential_filename'})
    if path.name.endswith(('.sqlite-wal', '.sqlite-shm')):
        sidecar_count += 1
        scan(path, path.read_bytes().decode('utf-8', errors='ignore'))
    elif path.suffix == '.sqlite':
        db_count += 1
        c = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
        try:
            tables = [row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for table in tables:
                escaped = '"' + table.replace('"', '""') + '"'
                for row in c.execute('SELECT * FROM ' + escaped):
                    for value in row:
                        if isinstance(value, str):
                            scan(path, value)
        finally:
            c.close()
    elif path.suffix == '.png':
        png_count += 1
        if not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            findings.append({'file': path.relative_to(root).as_posix(), 'indicator': 'invalid_png_header'})
    else:
        data = path.read_bytes()
        encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        text = data.decode(encoding, errors='strict')
        text_count += 1
        scan(path, text)

report = {'reviewed_at_utc': datetime.now(timezone.utc).isoformat(), 'files_reviewed': len(files),
          'text_files': text_count, 'sqlite_databases': db_count, 'png_files': png_count,
          'preserved_personal_database_forensic_companions': sidecar_count,
          'automated_indicator_findings': findings,
          'passed': not findings,
          'scope': '交付白名单内文本逐文件解码、SQLite所有表中字符串字段、凭据文件名和PNG格式检查；未读取应用凭据或其他项目。',
          'manual_context': '业务数据为本项目合成夹具；用户截图为测试控制台/回放界面，不含真实银行资料。绝对路径及TempAdmin系统账号名作为证据运行元数据保留。',
          'limitations': '模式扫描不能数学证明不存在所有形式的秘密；PNG内容依据已查看图像和来源语境审查，未对全图进行OCR。未将正常代码示例或哈希当作真实凭据。',
          'excluded': ['解释器虚拟环境', '浏览器profile', 'Python/测试缓存', '其他项目', '旧压缩包与交付包自身', '干净环境重复源码副本', '非白名单文件'],
          'content_sha256': {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}
output = args.out or root / 'evidence' / ('delivery-content-review-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
if output.exists():
    raise RuntimeError('拒绝覆盖已有审查记录：' + str(output))
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'report': str(output), 'files_reviewed': len(files), 'passed': report['passed'], 'findings': findings}, ensure_ascii=False, indent=2))
sys.exit(0 if report['passed'] else 1)
