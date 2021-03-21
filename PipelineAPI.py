from collections import OrderedDict
from multiprocessing import Pool
from operator import itemgetter
from bs4 import BeautifulSoup
import numpy as np
import requests
import roleml
import json

class PipelineAPI:

    '''
    Gets match data from Riot's API and www.op.gg, processes it, and export to JSON.
    Match data is composed of:
        - Descriptive information for players like their rank, winrate, champion played, etc.
        - Statistics for the match at minute 15, like the number of kills, minions killed, etc.

    Parameters:
        watcher (RiotWatcher's LolWatcher): API watcher.
        file_descriptor (open()'s return): File descriptor to the desired json output file.

    Returns:
        packed_data: An dictionary containing the data.
    '''

    def __init__(self, watcher=None, file_descriptor=None):
        self.watcher = watcher
        self.file_descriptor = file_descriptor

    def run(self, match_id, region):  # run modules/pack data together/save as json
        self.region = region
        match_raw, timeline_raw = self._get_raw_data(match_id)

        if (match_raw and timeline_raw) and len(timeline_raw['frames']) >= 15:
            roles = self._get_roles(match_raw, timeline_raw)
            timeline_data = self._get_timeline_data(timeline_raw)
            frames_data = self._get_process_frames(timeline_raw)
            summoners_stats = self._get_summoners_stats(match_raw)
            packed_data = self._pack_data(match_raw,
                                          roles,
                                          timeline_data,
                                          frames_data,
                                          summoners_stats)
            
            if self.file_descriptor:
                self._save_json(packed_data, self.file_descriptor)
            
            return packed_data

    def _pack_data(self, match_raw, roles, timeline_data, frames_data, summoners_stats):
        packed_data = OrderedDict()
        for i in range(10):  # 10 players
            
            packed_data[f'Player{i+1}'] = self._fetch(
                match_raw['participantIdentities'][i]['player'],
                [
                    'summonerName',
                    'platformId'
                ]
            )
            
            packed_data[f'Player{i+1}'].update(summoners_stats[f'{i+1}'])
            
            packed_data[f'Player{i+1}'].update(
                self._fetch(
                    match_raw['participants'][i],
                    [
                        'participantId',
                        'teamId',
                        'championId'
                    ]
                )
            )
            
            packed_data[f'Player{i+1}']['role'] = roles[i+1]
            packed_data[f'Player{i+1}'].update(timeline_data[i+1])
            packed_data[f'Player{i+1}'].update(frames_data[f'{i+1}'])
            
            if i+1 <= 5:
                packed_data[f'Player{i+1}']['win'] = \
                    1 if match_raw['teams'][0]['win'] == 'Win' else 0
            elif i+1 > 5:
                packed_data[f'Player{i+1}']['win'] = \
                    1 if match_raw['teams'][1]['win'] == 'Win' else 0
        
        return packed_data

    def _get_raw_data(self, match_id):  # pull data from api
        for _ in range(5):  # 5 retries in case of timeout/error
            try:
                m = self.watcher.match.by_id(region=self.region, match_id=match_id)
                t = self.watcher.match.timeline_by_match(
                    region=self.region, match_id=match_id)
                return m, t
            except Exception as e:
                pass
        
        return None, None

    def _get_roles(self, match_raw, timeline_raw):  # predict the role using api data
        return roleml.predict(match_raw, timeline_raw)

    def _get_timeline_data(self, timeline_raw):  # pull timeline data and sort it
        timeline_data = OrderedDict()
        participantFrames_at15min = timeline_raw['frames'][14]['participantFrames']
        
        for i in range(10):  # 10 players
            timeline_data[f'{i+1}'] = self._fetch(
                participantFrames_at15min[f'{i+1}'],
                [
                    'level',
                    'xp',
                    'totalGold',
                    'minionsKilled',
                    'jungleMinionsKilled',
                    'participantId'
                ]
            )
        
        timeline_data = {  # sort keys by value of participantId
            v.get("participantId"): v
            for v in sorted(timeline_data.values(),
                            key=lambda v: v.get("participantId"))
        }
        
        return timeline_data

    def _get_process_frames(self, timeline): # sum events in frames for all players
        frames = timeline['frames'][0:15]  # n frames, 1 min of data per frame
        stats_dict = {
            'kills': 0,
            'assists': 0,
            'deaths': 0,
            'wardPlaced': 0,
            'wardDestroyed': 0,
            'towerDestroyed': 0,
            'inhibitorDestroyed': 0,
            'dragonKilled': 0,
            'riftHeraldKilled': 0
        }
        
        stats = OrderedDict()
        for i in range(10):  # 10 players
            stats[f'{i+1}'] = OrderedDict(stats_dict)
        
        for frame in frames:  # disgusting if statement forest ahead
            for event in frame['events']:

                if event['type'] == 'CHAMPION_KILL':
                    if event.get('killerId') == 0:  # if player died to creep/monster
                        if event.get('victimId') > 5:  # randomly give kill to player
                            stats[f"{np.random.randint(1,6)}"]['kills'] += 1
                            stats[f"{event.get('victimId')}"]['deaths'] += 1
                        elif event.get('victimId') <= 5:  # randomly give kill to player
                            stats[f"{np.random.randint(6,11)}"]['kills'] += 1
                            stats[f"{event.get('victimId')}"]['deaths'] += 1
                    else:  # default case
                        stats[f"{event.get('killerId')}"]['kills'] += 1
                        stats[f"{event.get('victimId')}"]['deaths'] += 1
                        for assistId in event.get('assistingParticipantIds'):
                            stats[f"{assistId}"]['assists'] += 1

                elif event['type'] == 'WARD_PLACED':
                    if event.get('creatorId') == 0:  # don't count champ warding ability
                        pass
                    else:
                        stats[f"{event.get('creatorId')}"]['wardPlaced'] += 1

                elif event['type'] == 'WARD_KILL':
                    if event.get('killerId') == 0:
                        pass
                    else:
                        stats[f"{event.get('killerId')}"]['wardDestroyed'] += 1

                elif event['type'] == 'BUILDING_KILL':
                    if event.get('teamId') == 200:  # team 1 destroyed building
                        if event.get('buildingType') == 'TOWER_BUILDING':
                            if event.get('killerId') == 0:  # if creep destroyed building
                                stats[f"{np.random.randint(1,6)}"]['towerDestroyed'] += 1
                            else:
                                stats[f"{event.get('killerId')}"]['towerDestroyed'] += 1
                        elif event.get('buildingType') == 'INHIBITOR_BUILDING':
                            if event.get('killerId') == 0:
                                stats[f"{np.random.randint(1,6)}"]['inhibitorDestroyed'] += 1
                            else:
                                stats[f"{event.get('killerId')}"]['inhibitorDestroyed'] += 1
                    elif event.get('teamId') == 100:
                        if event.get('buildingType') == 'TOWER_BUILDING':
                            if event.get('killerId') == 0:
                                stats[f"{np.random.randint(6,11)}"]['towerDestroyed'] += 1
                            else:
                                stats[f"{event.get('killerId')}"]['towerDestroyed'] += 1
                        elif event.get(f"{event.get('killerId')}") == 'INHIBITOR_BUILDING':
                            if event.get('killerId') == 0:
                                stats[f"{np.random.randint(6,11)}"]['inhibitorDestroyed'] += 1
                            else:
                                stats[f"{event.get('killerId')}"]['inhibitorDestroyed'] += 1

                elif event['type'] == 'ELITE_MONSTER_KILL':
                    if event.get('killerId') != 0:
                        if event.get('monsterType') == 'DRAGON':
                            stats[f"{event.get('killerId')}"]['dragonKilled'] += 1
                        elif event.get('monsterType') == 'RIFTHERALD':
                            stats[f"{event.get('killerId')}"]['riftHeraldKilled'] += 1
                        else:  # nashor (spawns at 20min, data is 15min max)
                            pass
        
        return stats

    def _get_summoners_stats(self, match_raw):  # scrape from league of graphs
        
        summoners = []
        for i in range(10):  # get list of players name for url
            summoners.append(
                match_raw['participantIdentities'][i]['player']['summonerName'])

        urls = []
        server = self.region.lower()[:-1]
        if server == 'eun':
            server = 'eune'
        for summoner in summoners: # create list of urls
            urls.append('https://www.leagueofgraphs.com/summoner/'+server+'/'+summoner)

        summoners_stats = OrderedDict()
        for i in range(10):
            summoners_stats[f'{i+1}'] = {
                'accountLevel': None,
                'rankDivision': None,
                'wins': None,
                'losses': None,
                'mainRole': None,
                'altRole': None,
                'mainChamp': None,
                'mainChampMasteryLvl': None,
                'mainChampMasteryPts': None
            }
        
        with Pool(None) as p:  # multiprocessing GET request+processing
            processed_html = [p.map(PipelineAPI._scrape, urls)]
        
        for idx, stats in enumerate(processed_html[0]): # fill player dictionary
            summoners_stats[f'{idx+1}']['accountLevel'] = stats[0]
            summoners_stats[f'{idx+1}']['rankDivision'] = stats[1]
            summoners_stats[f'{idx+1}']['wins'] = stats[2]
            summoners_stats[f'{idx+1}']['losses'] = stats[3]
            summoners_stats[f'{idx+1}']['mainRole'] = stats[4]
            summoners_stats[f'{idx+1}']['altRole'] = stats[5]
            summoners_stats[f'{idx+1}']['mainChamp'] = stats[6]
            summoners_stats[f'{idx+1}']['mainChampMasteryLvl'] = stats[7]
            summoners_stats[f'{idx+1}']['mainChampMasteryPts'] = stats[8]

        return (summoners_stats)

    @staticmethod
    def _scrape(url):
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(
            url=url,
            headers=headers
        )
        soup = BeautifulSoup(response.text, 'lxml')

        #account lvl
        try:
            account_lvl = str(soup.find_all('div', class_='bannerSubtitle'))
            account_lvl = account_lvl[account_lvl.find('l ')+1:\
                                        account_lvl.find('-')]
            account_lvl = int(account_lvl.split()[0].strip())
        except:
            account_lvl = None

        try:
        # rank/tiers
            tier_rank = str(soup.find_all('div', class_='txt mainRankingDescriptionText'))
            tier_rank = tier_rank[tier_rank.find('Tier">')+6:tier_rank[48:].find('<')].strip()
            if tier_rank == '':
                tier_rank = 'Unranked'
        except:
            tier_rank = None

        # wins/losses
        try:
            if tier_rank != 'Unranked':
                wins = str(soup.find_all('span', class_='winsNumber'))
                wins = int(wins[wins.find('>')+1:wins.find('</')])

                losses = str(soup.find_all('span', class_='lossesNumber'))
                losses = int(losses[losses.find('>')+1:losses.find('</')])
            else: wins = 1; losses = 1
        except:
            wins = None
            losses = None

        # preferred role
        try:
            main_role = str(soup.find_all('div', class_='txt name')[0])
            main_role = main_role[main_role.find('>')+1:main_role.find('</')].strip().lower()
            if main_role == 'ad carry':
                main_role = 'bot'
            elif main_role == 'jungler':
                main_role = 'jungle'
            elif main_role == 'support':
                main_role = 'supp'
        except:
            main_role = None

        # alt preferred role
        try:
            alt_role = str(soup.find_all('div', class_='txt name')[1])
            alt_role = alt_role[alt_role.find('>')+1:alt_role.find('</')].strip().lower()
            if alt_role == 'ad carry':
                alt_role = 'bot'
            elif alt_role == 'jungler':
                alt_role = 'jungle'
            elif alt_role == 'support':
                alt_role = 'supp'
        except:
            alt_role = None
        
        # get main
        try:
            played_champs = str(soup.find_all('div', class_='name'))
            main_champ = played_champs[played_champs.find('>')+1:\
                                    played_champs.find('</')]
            if main_champ == '[':
                main_champ = None
        except:
            main_champ = None
        try:
            # main mastery/pts
            mastery_main = str(soup.find_all('div', class_='relative requireTooltip')[0])
            mastery_main_lvl = int(mastery_main[mastery_main.find('Level ')+6:\
                                                mastery_main.find('&lt;/')])
            mastery_main_pts = int(mastery_main[mastery_main.find('Points: ')+8:\
                                                mastery_main.find('">')].replace(',',''))
        except:
            mastery_main_lvl = None
            mastery_main_pts = None

        return (account_lvl, tier_rank, wins, losses, main_role, alt_role, 
                main_champ, mastery_main_lvl, mastery_main_pts)

    def _fetch(self, d, ks, orderedDict=True):  # query from a dictionary
        vals = []
        if len(ks) >= 1:
            vals = itemgetter(*ks)(d)
            if len(ks) == 1:
                vals = [vals]
        return OrderedDict(zip(ks, vals))

    def _save_json(self, match_data, file_descriptor):
        file_descriptor.write(json.dumps(match_data,
                                         indent=4,
                                         ensure_ascii=False)+'\n')
