"""Copy selected original JSONL lines; never reconstruct tool outputs from memory."""
import argparse
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def export(source, destination, complete_prefix=False):
    source = Path(source)
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    content = source.read_bytes()
    lines = content.splitlines(keepends=True)
    selected, index, excluded = [], [], {}
    started = False
    calls, outputs = set(), set()
    for line_no, raw in enumerate(lines, 1):
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            excluded['incomplete_or_invalid_line'] = excluded.get('incomplete_or_invalid_line', 0) + 1
            continue
        payload = row.get('payload', {})
        if row.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user' and '目前先分析，暂不编码' in json.dumps(payload, ensure_ascii=False):
            started = True
        if not started:
            continue
        item_type = payload.get('type')
        allowed = row.get('type') == 'response_item' and (
            item_type in ('custom_tool_call', 'custom_tool_call_output', 'function_call', 'function_call_output')
            or (item_type == 'message' and payload.get('role') in ('user', 'assistant') and payload.get('channel') != 'analysis')
        )
        if allowed:
            selected.append(raw)
            index.append({'source_line': line_no, 'export_line': len(selected), 'timestamp': row.get('timestamp'), 'type': item_type, 'role': payload.get('role'), 'call_id': payload.get('call_id')})
            if item_type in ('custom_tool_call', 'function_call'):
                calls.add(payload.get('call_id'))
            if item_type in ('custom_tool_call_output', 'function_call_output'):
                outputs.add(payload.get('call_id'))
        else:
            label = row.get('type', '?') + '/' + str(item_type)
            excluded[label] = excluded.get(label, 0) + 1
    if not started or not selected:
        raise ValueError('未找到正式协作起点；拒绝导出其他会话内容')
    original_selected_count = len(selected)
    if complete_prefix:
        pending = set()
        last_closed = 0
        for position, raw in enumerate(selected, 1):
            payload = json.loads(raw)['payload']
            if payload.get('type') in ('custom_tool_call', 'function_call'):
                pending.add(payload.get('call_id'))
            elif payload.get('type') in ('custom_tool_call_output', 'function_call_output'):
                pending.discard(payload.get('call_id'))
            if not pending:
                last_closed = position
        if last_closed == 0:
            raise ValueError('没有调用已闭合的可封存前缀')
        selected = selected[:last_closed]
        index = index[:last_closed]
        calls, outputs = set(), set()
        for raw in selected:
            payload = json.loads(raw)['payload']
            if payload.get('type') in ('custom_tool_call', 'function_call'):
                calls.add(payload.get('call_id'))
            elif payload.get('type') in ('custom_tool_call_output', 'function_call_output'):
                outputs.add(payload.get('call_id'))
    for item, raw in zip(index, selected):
        if raw != lines[item['source_line'] - 1]:
            raise ValueError('导出行与来源原始字节不符')
        item['sha256'] = hashlib.sha256(raw).hexdigest()
    output = b''.join(selected)
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    raw_path = dest / (name + '-visible-original.jsonl')
    raw_path.write_bytes(output)
    manifest = {
        'exported_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_basename': source.name, 'source_bytes_at_snapshot': len(content),
        'source_snapshot_sha256': hashlib.sha256(content).hexdigest(),
        'export_file': raw_path.name, 'export_sha256': hashlib.sha256(output).hexdigest(),
        'selected_original_lines': len(selected), 'index': index,
        'excluded_record_counts_since_start': excluded,
        'unpaired_call_ids_at_snapshot': sorted(x for x in calls - outputs if x),
        'scope': '截至明确截止点，本地日志中用户/助手可见消息及工具调用返回的完整原始记录；不声称平台全量完整。',
        'complete_prefix_requested': complete_prefix,
        'record_label': '完整记录（限定本地来源、可见记录范围和截止点）' if complete_prefix else '历史可见原始记录快照',
        'first_provided_record': index[0],
        'last_provided_record': index[-1],
        'cutoff_beijing': datetime.fromisoformat(index[-1]['timestamp'].replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=8))).isoformat(),
        'source_line_range': [index[0]['source_line'], index[-1]['source_line']],
        'all_provided_lines_byte_verified': True,
        'all_eligible_records_through_cutoff_included': True,
        'visible_records_after_declared_cutoff_not_included': original_selected_count - len(selected),
        'gaps': [
            '截止之后的封存、打包、校验、回复不在提供范围，不循环补入。',
            '隐藏推理、系统/开发者指令、重复事件镜像、正式起点前历史明确排除。',
            '提供来源实际保存的工具内容；不重建来源中不存在的内容。',
            '本地来源以外是否另有平台记录未核实，不推测缺失原因。',
            '未调用子Agent或其他聊天委托，无相应子任务记录。'
        ]
    }
    manifest_path = dest / (name + '-manifest.json')
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'raw': str(raw_path), 'manifest': str(manifest_path), 'lines': len(selected), 'unpaired_calls': manifest['unpaired_call_ids_at_snapshot'], 'cutoff_beijing': manifest['cutoff_beijing'], 'last_source_line': index[-1]['source_line']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('--out', default='evidence/collaboration')
    parser.add_argument('--complete-prefix', action='store_true')
    args = parser.parse_args()
    export(args.source, args.out, args.complete_prefix)
