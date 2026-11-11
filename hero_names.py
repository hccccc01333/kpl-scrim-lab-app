"""Hero identity comes from the printed name, never a default-skin portrait."""
import re


def edit_distance(a, b):
    row = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(next_row[-1]+1, row[j]+1, row[j-1]+(x != y)))
        row = next_row
    return row[-1]


def resolve_name(readings, entries):
    """A near dictionary match is a suggestion, not an accepted OCR field."""
    valid = []
    for r in readings:
        text = re.sub(r'[^\u4e00-\u9fff]', '', r['raw'])
        if 2 <= len(text) <= 5 and r['confidence'] >= .5:
            valid.append({**r, 'text': text})
    candidates = []
    for entry in entries:
        if entry['kind'] != 'hero':
            continue
        matching = []
        for r in valid:
            distance = edit_distance(r['text'], entry['name'])
            # Single-character corrections need a shared character and same length.
            if distance == 0 or (distance == 1 and len(r['text']) == len(entry['name']) and set(r['text']) & set(entry['name'])):
                matching.append((distance, r))
        if not matching:
            continue
        distance, best = min(matching, key=lambda pair: (pair[0], -pair[1]['confidence']))
        candidates.append({'id': entry['id'], 'name': entry['name'], 'icon': entry.get('icon'),
                           'source':'name-ocr', 'distance':distance, 'raw':best['raw'],
                           'textConfidence':best['confidence'], 'evidence':best['raw'],
                           'needsReview':True})
    candidates.sort(key=lambda c:(c['distance'], -c['textConfidence'], c['name']))
    exact = [c for c in candidates if c['distance'] == 0]
    accepted = exact[0] if len(exact) == 1 and exact[0]['textConfidence'] >= .8 else None
    return {'readings': readings, 'candidates':candidates[:5], 'accepted':accepted,
            'status':'exact' if accepted else 'uncertain' if candidates else 'unreadable'}
