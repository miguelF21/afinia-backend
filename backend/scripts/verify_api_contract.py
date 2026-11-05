#!/usr/bin/env python3
"""
AFINIA — Script de Auditoría Automatizada de Paridad OpenAPI v1 vs Flask url_map.
Verifica que las rutas y métodos registrados en Flask coincidan con docs/api/afinia-openapi-v1.yaml.
"""
import os
import sys
import re

# 1. Parsear OpenAPI YAML
openapi_path = os.path.abspath('docs/api/afinia-openapi-v1.yaml')
if not os.path.exists(openapi_path):
    print(f"Error: no se encuentra {openapi_path}")
    sys.exit(1)

with open(openapi_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_paths = False
current_path = None
openapi_ops = []

path_regex = re.compile(r'^  (/[^:]+):\s*$')
method_regex = re.compile(r'^    (get|post|put|delete|patch):\s*$')
op_id_regex = re.compile(r'^\s+operationId:\s*(.+)$')
summary_regex = re.compile(r'^\s+summary:\s*(.+)$')
tag_regex = re.compile(r'^\s+- (.+)$')

current_method = None
current_op_id = None
current_summary = None
current_tag = None
in_tags = False

def push_op():
    global current_method, current_op_id, current_summary, current_tag
    if current_path and current_method:
        openapi_ops.append({
            'method': current_method.upper(),
            'path': current_path,
            'summary': current_summary or '',
            'operationId': current_op_id or '',
            'tag': current_tag or 'Other'
        })
        current_method = None
        current_op_id = None
        current_summary = None
        current_tag = None

for line in lines:
    if line.startswith('paths:'):
        in_paths = True
        continue
    if in_paths:
        if line.startswith('components:'):
            push_op()
            break
        
        m_path = path_regex.match(line)
        if m_path:
            push_op()
            current_path = m_path.group(1).strip()
            continue
            
        m_method = method_regex.match(line)
        if m_method:
            push_op()
            current_method = m_method.group(1).strip()
            in_tags = False
            continue
            
        if current_method:
            if 'tags:' in line:
                in_tags = True
                continue
            if in_tags:
                m_tag = tag_regex.match(line)
                if m_tag:
                    current_tag = m_tag.group(1).strip()
                    in_tags = False
                    continue
            m_op = op_id_regex.match(line)
            if m_op:
                current_op_id = m_op.group(1).strip()
            m_sum = summary_regex.match(line)
            if m_sum:
                current_summary = m_sum.group(1).strip()

push_op()

# 2. Extraer rutas de Flask
sys.path.insert(0, os.path.abspath('backend'))
from app import create_app
from config import Config
app = create_app(Config)

flask_map = {}
for rule in app.url_map.iter_rules():
    methods = rule.methods - {'HEAD', 'OPTIONS'}
    parts = rule.rule.rstrip('/').split('/')
    if not parts or parts == ['']:
        parts = ['']
    norm_parts = []
    for p in parts:
        if p.startswith('<') and p.endswith('>'):
            var = p[1:-1].split(':')[-1]
            norm_parts.append(f"{{{var}}}")
        else:
            norm_parts.append(p)
    norm_rule = '/'.join(norm_parts)
    if not norm_rule:
        norm_rule = '/'
    
    for m in methods:
        flask_map[(m, norm_rule)] = (rule.endpoint, rule.rule)

def normalize_for_compare(p):
    parts = p.rstrip('/').split('/')
    norm = []
    for part in parts:
        if (part.startswith('{') and part.endswith('}')) or (part.startswith('<') and part.endswith('>')):
            norm.append('{PARAM}')
        else:
            norm.append(part)
    res = '/'.join(norm)
    return res if res else '/'

implemented_ops = []
pending_ops = []

for op in openapi_ops:
    m = op['method']
    p = op['path']
    norm_op = normalize_for_compare(p)
    matched = None
    for (fm, fp), (f_ep, f_raw) in flask_map.items():
        if fm == m and normalize_for_compare(fp) == norm_op:
            matched = (fm, fp, f_ep, f_raw)
            break
    if matched:
        implemented_ops.append((op, matched))
    else:
        pending_ops.append(op)

flask_extra = []
for (fm, fp), (f_ep, f_raw) in flask_map.items():
    if f_ep == 'static':
        continue
    norm_fp = normalize_for_compare(fp)
    matched = any(op['method'] == fm and normalize_for_compare(op['path']) == norm_fp for op in openapi_ops)
    if not matched:
        flask_extra.append((fm, f_raw, f_ep))

print(f"TOTAL OPERACIONES OPENAPI: {len(openapi_ops)}")
print(f"OPERACIONES OPENAPI IMPLEMENTADAS EN FLASK: {len(implemented_ops)}")
print(f"OPERACIONES OPENAPI PENDIENTES EN FLASK: {len(pending_ops)}")
print(f"RUTAS EXTRA EN FLASK (FUERA DE OPENAPI): {len(flask_extra)}")

if __name__ == '__main__':
    print("\n--- 1. OPERACIONES IMPLEMENTADAS EN FLASK ---")
    for op, (fm, fp, f_ep, f_raw) in implemented_ops:
        print(f"  [OK] {op['method']:6} {op['path']:42} -> Flask: {f_raw:40} ({f_ep})")
    
    print("\n--- 2. OPERACIONES PENDIENTES EN OPENAPI ---")
    for op in pending_ops:
        print(f"  [PENDIENTE] {op['method']:6} {op['path']:42} [{op['tag']:12}] ({op['operationId']})")
        
    print("\n--- 3. RUTAS FLASK ADICIONALES ---")
    for fm, f_raw, f_ep in flask_extra:
        print(f"  [EXTRA] {fm:6} {f_raw:42} -> {f_ep}")
