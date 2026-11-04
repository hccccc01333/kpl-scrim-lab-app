"""Minimal parsed sources for testing collection prerequisites, without network/OCR."""
from copy import deepcopy
import channel_store as c
from collection_contract import PAGE_TYPES


def complete_collection(channel):
    if not channel.get('official'):
        c.attach_official(channel, 'camp-test', {}, {'schema':'camp-replay-v1','match':{},'economy':{},'events':{},'positions':{}})
    group = deepcopy((channel['sources'].get('screenshot') or {}).get('group') or {'players':[], 'match':{}})
    group['pages'] = [{'pageType':key} for key in PAGE_TYPES]
    c.attach_screenshot(channel, group, ['fixture-'+key for key in PAGE_TYPES])
    if not channel['sources']['video'].get('files'):
        c.attach_video(channel, {'name':'single-recording.json'}, {'lineups':{},'timeline':[]})
    return channel
