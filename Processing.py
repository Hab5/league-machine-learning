from sklearn.preprocessing import OrdinalEncoder
from riotwatcher import LolWatcher, ApiError
from collections import OrderedDict
from multiprocessing import Pool
from operator import itemgetter
from bs4 import BeautifulSoup
from pprint import pprint
from tqdm import tqdm
import pandas as pd
import numpy as np
import requests
import roleml
import json
import os

from settings import API_KEY, REGION

class Processing:
    def __init__(self):
        self.champion_mapping = self._get_champion_mapping()

    def run(self):
        df_list = []
        df_viz = []
        n_matches = 20000
        server_list = ['euw', 'eun', 'na', 'jp']

        for server in server_list:
            path = 'data/output_json/'+server+'/'
            for filename in tqdm(os.listdir(path)[:n_matches], 
                             colour='green', desc='Processing '+server.upper()):
                with open(os.path.join(path+filename), 'r') as f:
                    match_data = OrderedDict(json.load(f))
                    try:
                        red_team, tmp_red = self._process_team(
                            [list(match_data.items())[:5][i][1] for i in range(5)]
                        )
                        blue_team, tmp_blue = self._process_team(
                            [list(match_data.items())[5:][i][1] for i in range(5)]
                        )
                        df_list.append(self._evaluate_teams(red_team, blue_team, 
                                                            tmp_red, tmp_blue))
                        df_viz.extend([red_team, blue_team])
                    except (KeyError, ValueError) as e:
                        pass
        return pd.concat(df_list).dropna().reset_index(drop=True),\
               pd.concat(df_viz).dropna().reset_index(drop=True) 

    def _process_team(self, team):
        team = pd.DataFrame(team)
        
        # sort by role, and fix index
        team = team.sort_values(by='role')
        team.index = range(1, len(team.index) + 1)
        
        # calculating winrate
        team['winRate'] = team['wins']/(team['wins']+team['losses'])*100
        
        # fill null values
        team['accountLevel'].fillna(team['accountLevel'].mean(), inplace=True)
        team['rankDivision'].fillna(team['rankDivision'].mode()[0], inplace=True)
        team['wins'].fillna(team['wins'].mean(), inplace=True)
        team['losses'].fillna(team['losses'].mean(), inplace=True)
        team['winRate'].fillna(team['winRate'].mean(), inplace=True)
        team['accountLevel'].fillna(team['accountLevel'].mean(), inplace=True)
        team['mainRole'].fillna(team['role'] if np.random.choice(2, 1, p=[0.4, 0.6])[0] == 1\
                                 else 'nope', inplace=True) # using outcome of calculated
                                                            # distribution of players playing
                                                            # their main roles.
        team['altRole'].fillna(team['role'] if np.random.choice(2, 1, p=[0.25, 0.75])[0] == 1\
                                 else 'nope', inplace=True) # using outcome of calculated
                                                            # distribution of players playing
                                                            # their alt roles.
        team['mainChampMasteryLvl'].fillna(team['mainChampMasteryLvl'].mean(), inplace=True)
        team['mainChampMasteryPts'].fillna(team['mainChampMasteryPts'].mean(), inplace=True)

        # Encode ranks/champions
        team = self._encode(team)
        
        # jungle cs to normal cs
        team['minionsKilled'] = team['minionsKilled'] + team['jungleMinionsKilled']
        team = team.drop('jungleMinionsKilled', axis=1)
        
        #sum/average everything into one row and feature selection
        team_sum = pd.DataFrame({
            'sumAccountLevel'       : [np.sum(team['accountLevel'])],
            'sumGamesPlayed'        : [np.sum(team['wins']+team['losses'])],
            'sumRanks'              : [np.sum(team['rankDivision'])],
            'averageWinrate'        : [np.mean(team['winRate'])],
            'sumPlayingMainRole'    : [np.sum(np.where(team['role']==team['mainRole'], 1, 0))],
            'sumPlayingAltRole'     : [np.sum(np.where(team['role']==team['altRole'], 1, 0))],
            'sumPlayingMain'        : [np.sum(np.where(team['champion']==team['mainChamp'], 1, 0))],
            'sumMainMasteryLvl'     : [np.sum(team['mainChampMasteryLvl'])],
            'sumMainMasteryPts'     : [np.sum(team['mainChampMasteryPts'])],
            'sumKills'              : [np.sum(team['kills'])],
            'sumAssists'            : [np.sum(team['assists'])],
            'sumDeaths'             : [np.sum(team['deaths'])],
            'sumXp'                 : [np.sum(team['xp'])],
            'sumGold'               : [np.sum(team['totalGold'])],
            'sumMinionsKilled'      : [np.sum(team['minionsKilled'])],
            'sumWardsPlaced'        : [np.sum(team['wardPlaced'])],
            'sumWardsDestroyed'     : [np.sum(team['wardDestroyed'])],
            'sumMonstersKilled'     : [np.sum(team['dragonKilled']+team['riftHeraldKilled'])],
            'sumBuildingsDestroyed' : [np.sum(team['towerDestroyed']+team['inhibitorDestroyed'])],
            'win'                   : [np.mean(team['win'])]
            }
        )
        for idx, row in team.iterrows():
            team_sum[f"{row['role']}Champ"] = row['champion']
        return team_sum, team
    
    def _encode(self, team):
        categories=[
            'Unranked',
            'Iron IV', 'Iron III', 'Iron II', 'Iron I',
            'Bronze IV', 'Bronze III', 'Bronze II', 'Bronze I',
            'Silver IV', 'Silver III', 'Silver II', 'Silver I',
            'Gold IV', 'Gold III', 'Gold II', 'Gold I',
            'Platinum IV', 'Platinum III', 'Platinum II', 'Platinum I',
            'Diamond IV', 'Diamond III', 'Diamond II', 'Diamond I',
            'Master',
            'GrandMaster',
            'Challenger'
        ]
        rank_encoder = OrdinalEncoder(categories=[categories])
        team['rankDivision'] = rank_encoder.fit_transform(team[['rankDivision']])
        
        team['champion'] = team['championId'].astype(str).map(self.champion_mapping)

        team.loc[team.mainChamp == 'Wukong', 'mainChamp'] = 'MonkeyKing'
        team.loc[team.mainChamp == 'Nunu &amp; Willump', 'mainChamp'] = 'nunu'
        team['champion'] = team['champion'].str.replace(' ', '')\
                                           .str.replace("'",'')\
                                           .str.replace('.','')\
                                           .str.lower()
        team['mainChamp'] = team['mainChamp'].str.replace(' ','')\
                                             .str.replace("'",'')\
                                             .str.replace('.','')\
                                             .str.lower()

        # have to fill null here as I need the championId mapped
        team['mainChamp'].fillna(team['champion']
                                if np.random.choice(2, 1, p=[0.7, 0.3])[0] == 1 \
                                else 'rumble', inplace=True) # fill using distribution of playingMain
                                                             # rumble lowest pickrate (lazy solution)
                                                            # distribution = 0.31/0.69, rumble (0.8) 
        champ_encoder = OrdinalEncoder(categories=[[champ for champ in self.champion_mapping.values()]])
        team['champion'] = champ_encoder.fit_transform(team[['champion']])
        team['mainChamp'] = champ_encoder.fit_transform(team[['mainChamp']])
        return team
    
    def _evaluate_teams(self, team, enemy_team, tmp_team, tmp_enemy):
        eval_team = pd.DataFrame({
            'accountLevel'       : (team['sumAccountLevel']-enemy_team['sumAccountLevel']).values,
            'ranks'              : (team['sumRanks']-enemy_team['sumRanks']).values,
            'gamesPlayed'        : (team['sumGamesPlayed']-enemy_team['sumGamesPlayed']).values,
            'winrate'            : (team['averageWinrate']-enemy_team['averageWinrate']).values,
            'playingMainRoles'   : (team['sumPlayingMainRole']-enemy_team['sumPlayingMainRole']).values,
            'playingAltRoles'    : (team['sumPlayingAltRole']-enemy_team['sumPlayingAltRole']).values,
            'playingMains'       : (team['sumPlayingMain']-enemy_team['sumPlayingMain']).values,
            'mainMasteryLvl'     : (team['sumMainMasteryLvl']-enemy_team['sumMainMasteryLvl']).values,
            'mainMasteryPts'     : (team['sumMainMasteryPts']-enemy_team['sumMainMasteryPts']).values,
            'kills'              : (team['sumKills']-enemy_team['sumKills']).values, 
            'assists'            : (team['sumAssists']-enemy_team['sumAssists']).values, 
            'deaths'             : (team['sumDeaths']-enemy_team['sumDeaths']).values,
            'xp'                 : (team['sumXp']-enemy_team['sumXp']).values, 
            'gold'               : (team['sumGold']-enemy_team['sumGold']).values, 
            'minionsKilled'      : (team['sumMinionsKilled']-enemy_team['sumMinionsKilled']).values,
            'wardsPlaced'        : (team['sumWardsPlaced']-enemy_team['sumWardsPlaced']).values,
            'wardsDestroyed'     : (team['sumWardsDestroyed']-enemy_team['sumWardsDestroyed']).values,
            'monstersKilled'     : (team['sumMonstersKilled']-enemy_team['sumMonstersKilled']).values,
            'buildingsDestroyed' : (team['sumBuildingsDestroyed']-enemy_team['sumBuildingsDestroyed']).values,
            'winningLane'        : (len(np.where((tmp_team['totalGold'] > tmp_enemy['totalGold']) & 
                                                 (tmp_team['xp'] > tmp_enemy['xp']))[0])),

            'suppChamp'          : team['suppChamp'],
            'botChamp'           : team['botChamp'],
            'midChamp'           : team['midChamp'],
            'jungleChamp'        : team['jungleChamp'],
            'topChamp'           : team['topChamp'],
            'enemySuppChamp'     : enemy_team['suppChamp'],
            'enemyBotChamp'      : enemy_team['botChamp'],
            'enemyMidChamp'      : enemy_team['midChamp'],
            'enemyJungleChamp'   : enemy_team['jungleChamp'],
            'enemyTopChamp'      : enemy_team['topChamp'],
            'win'                : team['win']
            }
        )
        return eval_team

    def _get_champion_mapping(self):
        watcher = LolWatcher(API_KEY)
        versions = watcher.data_dragon.versions_for_region(REGION.lower())
        champions_version = versions['n']['champion']
        champ_list = watcher.data_dragon.champions(champions_version)

        champions = {}
        for champ in champ_list['data']:
            champions[f"{champ_list['data'][champ]['key']}"] = champ.lower().replace(' ', '')
        return champions






# class SparseProcessing:
#     def __init__(self):
#         self.df = None
    
#     def run(self):
#         df_list = []
#         n_matches = 10000
        
#         for filename in tqdm(os.listdir('data/output_json/euw/')[:n_matches], colour='green', desc='Processing JSON'):
#             with open(os.path.join('data/output_json/euw/', filename), 'r') as f:
#                 match_data = json.load(f)
#                 try:
#                     red_team, blue_team = self._get_teams(match_data)
#                     df_list.append(self._process_match(red_team, blue_team))
#                 except (ValueError, KeyError):
#                         pass
                    
#         self._assemble_dataframe(df_list)
#         self._process_dataframe()
#         return self.df
    
#     def _get_teams(self, match_data):
#         red_team_list = [list(match_data.items())[:5][i][1] for i in range(5)]
#         blue_team_list = [list(match_data.items())[5:][i][1] for i in range(5)]
#         red_team = pd.DataFrame(red_team_list)
#         blue_team = pd.DataFrame(blue_team_list)
#         return red_team, blue_team

#     def _process_match(self, red_team, blue_team):
#         # sort by role and fix index
#         red_team = red_team.sort_values(by='role')
#         blue_team = blue_team.sort_values(by='role')
#         red_team.index = range(1, len(red_team.index) + 1)
#         blue_team.index = range(1, len(blue_team.index) + 1)

#         # fill null values
#         red_team['rankDivision'].fillna(red_team['rankDivision'].mode(), inplace=True)
#         red_team['winRate'] = red_team['winRate'].astype(float)
#         red_team['winRate'].fillna(round(red_team['winRate'].mean()), inplace=True)
        
#         blue_team['rankDivision'].fillna(blue_team['rankDivision'].mode()[0], inplace=True)
#         blue_team['winRate'] = blue_team['winRate'].astype(float)
#         blue_team['winRate'].fillna(round(blue_team['winRate'].mean()), inplace=True)
        
#         # both teams in one df
#         both_team = pd.concat([red_team, blue_team])
        
        
#         # get rid of useless features
#         both_team = both_team.drop(['summonerName', 'platformId', 'participantId', 'teamId', 'level'], axis=1)
        
#         # jungle cs to normal cs
#         both_team['minionsKilled'] = both_team['minionsKilled'] + both_team['jungleMinionsKilled']
#         both_team = both_team.drop('jungleMinionsKilled', axis=1)

#         return both_team

#     def _assemble_dataframe(self, df_list):
#         self.df = pd.concat(df_list).dropna()

#     def _encode_dataframe(self):
#         categories=[
#             'Iron 4', 'Iron 3', 'Iron 2', 'Iron 1',
#             'Bronze 4', 'Bronze 3', 'Bronze 2', 'Bronze 1',
#             'Silver 4', 'Silver 3', 'Silver 2', 'Silver 1',
#             'Gold 4', 'Gold 3', 'Gold 2', 'Gold 1',
#             'Platinum 4', 'Platinum 3', 'Platinum 2', 'Platinum 1',
#             'Diamond 4', 'Diamond 3', 'Diamond 2', 'Diamond 1',
#             'Master',
#             'Grandmaster',
#             'Challenger'
#         ]

#         encoder = OrdinalEncoder(categories=[categories])
#         self.df['rankDivision'] = encoder.fit_transform(self.df[['rankDivision']])

#         champions = self._get_champions_list()
#         self.df['champion'] = self.df['championId'].astype(str).map(champions)
#         self.df.drop('championId', axis=1, inplace=True)
        
#         # df = df.drop('champ', axis=1)
#         self.df = pd.get_dummies(self.df, columns=['role','champ'], prefix_sep='_')
#         self.df['won'] = self.df['win']
#         self.df.drop(['win'], axis=1, inplace=True)

#     def _process_dataframe(self):
        
#         self._encode_dataframe()

#         tmp = 0
#         team_list = []
#         n_teams = self.df.shape[0]/5
#         for i in range(int(n_teams)):
#             iloc = int((i+1)*(self.df.shape[0]/(n_teams)))
#             team_list.append(self.df.iloc[tmp:iloc])
#             temp = iloc
        
#         df_list = []
#         for team in tqdm(team_list, colour='red', desc='Processing DATA'):
#             won = team.iloc[0]['won']
#             team.drop(['won'], axis=1, inplace=True)
#             tmp = pd.DataFrame(pd.concat([team.iloc[[i]].add_suffix(f'_{i+1}') for i in range(0,5)], axis=1).max()).T
#             tmp['won'] = won
#             df_list.append(tmp)
#         self.df = pd.concat(df_list)
    
#     def _get_champions_list(self):
#         watcher = LolWatcher('RGAPI-24f2622e-8e72-4963-96a0-7bf7f5ac7086')
#         versions = watcher.data_dragon.versions_for_region('euw1')
#         champions_version = versions['n']['champion']
#         champ_list = watcher.data_dragon.champions(champions_version)

#         champions = {}
#         for champ in champ_list['data']:
#             champions[f"{champ_list['data'][champ]['key']}"] = champ
#         return champions