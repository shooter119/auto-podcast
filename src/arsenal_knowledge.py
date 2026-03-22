"""
阿森纳俱乐部长期记忆库
包含球员名称、俱乐部事实、昵称等长期不变的信息
在 pipeline 启动时加载，供脚本生成和相关性判断使用
"""

from pathlib import Path
import json
import logging

logger = logging.getLogger("auto-podcast")

# 长期记忆文件路径
KNOWLEDGE_FILE = Path(__file__).parent.parent / "knowledge" / "arsenal_facts.json"

# 默认记忆（内置基础信息，防止文件丢失时崩溃）
DEFAULT_KNOWLEDGE = {
    "club": {
        "name_en": "Arsenal FC",
        "name_cn": "阿森纳",
        "nickname": "枪手",
        "stadium_en": "Emirates Stadium",
        "stadium_cn": "酋长球场",
        "founded": 1886,
        "manager_en": "Mikel Arteta",
        "manager_cn": "阿尔特塔",
        "colors": ["红白", "Red/White"],
        "league": "Premier League",
        "country": "英格兰"
    },
    "player_names": {
        # 一线队核心球员：中英文 + 常见昵称
        "mikel_arteta": {
            "en": ["Mikel Arteta", "Arteta"],
            "cn": "阿尔特塔",
            "nicknames": ["塔帅", "阿尔特塔"],
            "position": "主教练"
        },
        "bukayo_saka": {
            "en": ["Bukayo Saka", "Saka"],
            "cn": "萨卡",
            "nicknames": ["萨卡", "Saka"],
            "position": "右边锋/左边锋"
        },
        "martin_odegaard": {
            "en": ["Martin Ødegaard", " Odegaard"],
            "cn": "厄德高",
            "nicknames": ["厄德高", "奥德高"],
            "position": "进攻型中场"
        },
        "leandro_trossard": {
            "en": ["Leandro Trossard", "Trossard"],
            "cn": "特罗萨德",
            "nicknames": ["特罗萨德"],
            "position": "左边锋/前锋"
        },
        "kai_havertz": {
            "en": ["Kai Havertz", "Havertz"],
            "cn": "哈弗茨",
            "nicknames": ["哈弗茨", "哈子"],
            "position": "前锋/中场"
        },
        "gabriel_jesus": {
            "en": ["Gabriel Jesus", "Jesus"],
            "cn": "热苏斯",
            "nicknames": ["耶稣", "小耶稣", "热苏斯"],
            "position": "前锋"
        },
        "ben_white": {
            "en": ["Ben White", "White"],
            "cn": "本·怀特",
            "nicknames": ["怀特", "本怀特"],
            "position": "右后卫/中卫"
        },
        "william_saliba": {
            "en": ["William Saliba", "Saliba"],
            "cn": "萨利巴",
            "nicknames": ["萨利巴", "小萨"],
            "position": "中卫"
        },
        "gabriel_magalhaes": {
            "en": ["Gabriel Magalhaes", "Gabriel"],
            "cn": "加布里埃尔",
            "nicknames": ["加布", "加布里埃尔"],
            "position": "中卫"
        },
        "oleksandr_zinchenko": {
            "en": ["Oleksandr Zinchenko", "Zinchenko"],
            "cn": "津琴科",
            "nicknames": ["津琴科"],
            "position": "左后卫/中场"
        },
        "declan_rice": {
            "en": ["Declan Rice", "Rice"],
            "cn": "赖斯",
            "nicknames": ["赖斯", "大米"],
            "position": "后腰/中卫"
        },
        "thomas_partey": {
            "en": ["Thomas Partey", "Partey"],
            "cn": "帕蒂",
            "nicknames": ["帕蒂"],
            "position": "后腰"
        },
        "jorginho": {
            "en": ["Jorginho", "Jorginho"],
            "cn": "若日尼奥",
            "nicknames": ["若日尼奥", "若鸟"],
            "position": "后腰"
        },
        "david_rayna": {
            "en": ["David Raya", "Raya"],
            "cn": "拉亚",
            "nicknames": ["拉亚"],
            "position": "门将"
        },
        "ramsdale": {
            "en": ["Aaron Ramsdale", "Ramsdale"],
            "cn": "拉姆斯代尔",
            "nicknames": ["拉姆斯代尔", "阿龙"],
            "position": "门将"
        },
        "tomi_timber": {
            "en": ["Jurrien Timber", "Timber"],
            "cn": "廷伯",
            "nicknames": ["廷伯", "小廷"],
            "position": "右后卫/左后卫/中卫"
        },
        "riccardo_calafiori": {
            "en": ["Riccardo Calafiori", "Calafiori"],
            "cn": "卡拉菲奥里",
            "nicknames": ["卡拉菲奥里"],
            "position": "左后卫/中卫"
        },
        "gabriel_martinelli": {
            "en": ["Gabriel Martinelli", "Martinelli"],
            "cn": "马丁内利",
            "nicknames": ["马丁内利", "小马"],
            "position": "左边锋"
        },
        "mikel_merino": {
            "en": ["Mikel Merino", "Merino"],
            "cn": "梅里诺",
            "nicknames": ["梅里诺"],
            "position": "中场"
        }
    },
    "rivals": {
        "tottenham": {
            "name_en": "Tottenham Hotspur",
            "name_cn": "热刺",
            "relation": "北伦敦德比死敌"
        },
        "chelsea": {
            "name_en": "Chelsea",
            "name_cn": "切尔西",
            "relation": "伦敦德比对手"
        },
        "manchester_city": {
            "name_en": "Manchester City",
            "name_cn": "曼城",
            "relation": "主要争冠对手"
        },
        "liverpool": {
            "name_en": "Liverpool",
            "name_cn": "利物浦",
            "relation": "主要争冠对手"
        },
        "manchester_united": {
            "name_en": "Manchester United",
            "name_cn": "曼联",
            "relation": "传统豪门对手"
        }
    },
    "terminology": {
        "xG": "期望进球，衡量射门质量的统计指标",
        "PPDA": "每回合防守压迫次数",
        " Gegenpress": "高位逼抢",
        "Carabao Cup": "联赛杯（英格兰足球联盟杯）",
        "North London Derby": "北伦敦德比（阿森纳vs热刺）",
        "COYG": "Come On You Gunners! 阿森纳球迷口号",
        "The Gunners": "枪手，阿森纳的昵称"
    }
}


def load_arsenal_knowledge() -> dict:
    """加载阿森纳长期记忆，失败时返回默认记忆"""
    try:
        if KNOWLEDGE_FILE.exists():
            data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
            logger.info(f"长期记忆已加载: {len(data.get('player_names', {}))} 名球员, {len(data.get('rivals', {}))} 个对手")
            return data
        else:
            logger.info("长期记忆文件不存在，使用内置默认记忆")
            KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _save_default_knowledge()
            return DEFAULT_KNOWLEDGE
    except Exception as e:
        logger.warning(f"长期记忆加载失败，使用默认: {e}")
        return DEFAULT_KNOWLEDGE


def _save_default_knowledge():
    """保存默认记忆到文件（初始化时调用）"""
    try:
        KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        KNOWLEDGE_FILE.write_text(json.dumps(DEFAULT_KNOWLEDGE, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"默认长期记忆已保存到 {KNOWLEDGE_FILE}")
    except Exception as e:
        logger.warning(f"无法保存默认记忆: {e}")


def get_player_cn_name(en_name_or_nickname: str, knowledge: dict = None) -> str | None:
    """根据英文名或昵称查找对应中文名"""
    if knowledge is None:
        knowledge = load_arsenal_knowledge()

    search = en_name_or_nickname.lower()
    for player_key, player_data in knowledge.get("player_names", {}).items():
        en_names = [n.lower() for n in player_data.get("en", [])]
        nicknames = [n.lower() for n in player_data.get("nicknames", [])]
        if search in en_names or search in nicknames:
            return player_data["cn"]
    return None


def build_name_aliases(knowledge: dict = None) -> dict[str, str]:
    """
    构建所有名称→中文名的映射表（用于快速查找）
    返回 {"saka": "萨卡", "萨卡": "萨卡", "Bukayo Saka": "萨卡", ...}
    """
    if knowledge is None:
        knowledge = load_arsenal_knowledge()

    aliases = {}
    for player_key, player_data in knowledge.get("player_names", {}).items():
        cn = player_data["cn"]
        for en in player_data.get("en", []):
            aliases[en.lower()] = cn
        for nickname in player_data.get("nicknames", []):
            aliases[nickname.lower()] = cn
    return aliases


# 初始化时保存默认记忆文件
_save_default_knowledge()
