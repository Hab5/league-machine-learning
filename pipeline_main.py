from riotwatcher import LolWatcher, ApiError
from PipelineAPI import PipelineAPI
from pprint import pprint
from tqdm import tqdm
import pandas as pd
import json
import os

from settings import API_KEY, REGION

JSON_EXPORT_PATH = 'data/raw_output_json/'+REGION.lower()[:-1]+'.json'
JSON_SPLIT_PATH = 'data/output_json/'+REGION.lower()[:-1]+'/'+REGION.lower()[:-1]
MATCHES_ID_PATH = 'data/matches_id/id_'+REGION.lower()[:-1]+'.json'

def get_match_ids(path):
    with open(path, 'r') as f:
        match_id_list = json.loads(f.read())
    return match_id_list

def main():
    watcher = LolWatcher(API_KEY, timeout=10)
    match_id_list = get_match_ids(path=MATCHES_ID_PATH)

    with open(JSON_EXPORT_PATH, 'a', encoding='utf8') as f:
        pipeline = PipelineAPI(watcher=watcher, file_descriptor=f)
        for match_id in tqdm(match_id_list, colour='green'):
            pipeline.run(match_id=match_id, region=REGION)
    
    script_arguments = JSON_EXPORT_PATH+' '+JSON_SPLIT_PATH
    os.system("split -l 322 -a 5 -d --additional-suffix='.json' "+script_arguments)

if __name__ == '__main__':
    main()