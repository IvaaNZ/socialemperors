import json
import os

from bundle import QUESTS_DIR
from localization import load_catalog


def localize_quest_map(quest, language):
    """Translate the names shown in a quest battle; the quest files stay unchanged."""
    catalog = load_catalog(language)
    if not catalog:
        return quest
    player = quest.get('playerInfo')
    if isinstance(player, dict) and isinstance(player.get('name'), str):
        player['name'] = catalog.get(player['name'], player['name'])
    private = quest.get('privateState')
    for game_map in private.get('maps', []) if isinstance(private, dict) else []:
        if isinstance(game_map, dict) and isinstance(game_map.get('n'), str):
            game_map['n'] = catalog.get(game_map['n'], game_map['n'])
    return quest


def get_quest_map(questid, language='en'):
    file = os.path.join(QUESTS_DIR, str(questid) + ".json")
    if not os.path.exists(file):
        return("", 404)
    with open(file, 'r', encoding='utf-8') as stream:
        d = json.load(stream)
    return(localize_quest_map(d, language), 200)
