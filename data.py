from dataclasses import dataclass

ARROW = "arrow"
DYNAMITE = "dynamite"
BULL1 = "bull1"
BULL2 = "bull2"
BEER = "beer"
GATLING = "gatling"

DICE_FACES = [ARROW, DYNAMITE, BULL1, BULL2, BEER, GATLING]

FACE_LABELS = {
    ARROW: "🏹 箭",
    DYNAMITE: "💥 炸藥",
    BULL1: "🎯1",
    BULL2: "🎯2",
    BEER: "🍺 啤酒",
    GATLING: "🔫 格林機槍",
}

ROLE_CN = {
    "sheriff": "警長",
    "deputy": "副警長",
    "outlaw": "歹徒",
    "renegade": "叛徒",
}

ROLE_GOAL_CN = {
    "sheriff": "消滅所有歹徒與叛徒。",
    "deputy": "保護警長，協助警長獲勝。",
    "outlaw": "消滅警長。",
    "renegade": "成為最後一名存活者。",
}

@dataclass(frozen=True)
class Character:
    key: str
    cn: str
    en: str
    hp: int
    ability: str

CHARACTERS = [
    Character("bart_cassidy", "巴特・卡西迪", "Bart Cassidy", 8,
              "受到玩家射擊或格林機槍傷害時，可改拿 1 支箭來避免 1 點傷害；不能用於印第安人或炸藥，也不能拿走箭池最後 1 支箭。"),
    Character("black_jack", "黑傑克", "Black Jack", 8,
              "可以重擲炸藥；但目前骰面若已有 3 個以上炸藥，就不能再重擲。"),
    Character("calamity_janet", "災星珍妮特", "Calamity Janet", 8,
              "🎯1 與 🎯2 可以互相當作另一種距離使用。"),
    Character("el_gringo", "艾爾・格林哥", "El Gringo", 7,
              "當其他玩家使你失去 1 點以上生命時，該玩家必須拿 1 支箭；印第安人與炸藥不觸發。"),
    Character("jesse_jones", "傑西・瓊斯", "Jesse Jones", 9,
              "你的生命值剩 4 或更少時，對自己使用每個啤酒可回復 2 點生命。"),
    Character("jourdonnais", "喬杜奈斯", "Jourdonnais", 7,
              "每次印第安人攻擊最多只失去 1 點生命。"),
    Character("kit_carlson", "基特・卡爾森", "Kit Carlson", 7,
              "最終骰面中每個格林機槍符號，都可移除任意玩家 1 支箭。"),
    Character("lucky_duke", "幸運公爵", "Lucky Duke", 8,
              "你的回合可以多重擲 1 次，整回合最多擲 4 次。"),
    Character("paul_regret", "保羅・雷格雷特", "Paul Regret", 9,
              "你不會受到格林機槍造成的生命傷害。"),
    Character("pedro_ramirez", "佩德羅・拉米雷斯", "Pedro Ramirez", 8,
              "每失去 1 點生命，可以丟掉自己 1 支箭。"),
    Character("rose_doolan", "蘿絲・杜蘭", "Rose Doolan", 9,
              "射擊距離可多 1：🎯1 可打距離 1～2，🎯2 可打距離 2～3。"),
    Character("sid_ketchum", "席德・凱徹姆", "Sid Ketchum", 8,
              "回合開始時，可讓任意一名玩家回復 1 點生命，也可以選自己。"),
    Character("slab_the_killer", "殺手斯萊布", "Slab the Killer", 8,
              "每回合 1 次，可消耗 1 個啤酒，讓 1 個 🎯1 或 🎯2 對同一目標造成 2 點傷害。"),
    Character("suzy_lafayette", "蘇西・拉法葉", "Suzy Lafayette", 8,
              "回合最終骰面若沒有任何 🎯1 或 🎯2，回復 2 點生命。"),
    Character("vulture_sam", "禿鷹山姆", "Vulture Sam", 9,
              "每當其他玩家被淘汰，你回復 2 點生命。"),
    Character("willy_the_kid", "威利小子", "Willy the Kid", 8,
              "只需要 2 個格林機槍符號就能發動格林機槍。"),
]

CHAR_BY_KEY = {c.key: c for c in CHARACTERS}

ROLE_SETS = {
    4: ["sheriff", "renegade", "outlaw", "outlaw"],
    5: ["sheriff", "renegade", "outlaw", "outlaw", "deputy"],
    6: ["sheriff", "renegade", "outlaw", "outlaw", "outlaw", "deputy"],
    7: ["sheriff", "renegade", "outlaw", "outlaw", "outlaw", "deputy", "deputy"],
    8: ["sheriff", "renegade", "renegade", "outlaw", "outlaw", "outlaw", "deputy", "deputy"],
}

THREE_PLAYER_ROLES = ["deputy", "outlaw", "renegade"]
THREE_PLAYER_TARGET = {
    "deputy": "renegade",
    "renegade": "outlaw",
    "outlaw": "deputy",
}

# Expansion characters are indexed but are only dealt when their module is enabled.
SALOON_CHARACTERS = [
    Character("jose_delgado", "荷西・德爾加多", "José Delgado", 7, "使用大嘴巴時保留五顆普通骰，共六顆骰；使用膽小鬼仍為五顆。"),
    Character("tequila_joe", "龍舌蘭喬", "Tequila Joe", 7, "使用膽小鬼時保留五顆普通骰，共六顆骰；使用大嘴巴仍為五顆。"),
    Character("apache_kid", "阿帕契小子", "Apache Kid", 9, "擲出箭頭時，可改拿其他玩家持有的酋長箭。"),
    Character("bill_noface", "無臉比爾", "Bill Noface", 9, "箭頭只在最後一次擲骰確定後處理。"),
    Character("elena_fuente", "艾蓮娜・富恩特", "Elena Fuente", 7, "每次擲出一支以上箭頭時，可把其中一支箭交給任意玩家。"),
    Character("vera_custer", "薇拉・卡斯特", "Vera Custer", 7, "每次受到準心1或準心2造成的傷害，少失去1點生命。"),
    Character("doc_holyday", "霍利戴醫生", "Doc Holyday", 8, "一回合使用三個以上準心符號時，回復2點生命。"),
    Character("molly_stark", "莫莉・史塔克", "Molly Stark", 8, "其他玩家即將失血時，可以代為承受；不能承受超過自己當前生命的傷害。"),
]
CHAR_BY_KEY.update({c.key: c for c in SALOON_CHARACTERS})

# Undead or Alive, modules 1–3. Keep the two Duel faces in the list:
# a Duel die has a 2/6 chance of returning fire.
DUEL = "duel"
WHISKEY = "whiskey"
DUEL_FACES = (ARROW, DYNAMITE, GATLING, WHISKEY, DUEL, DUEL)
FACE_LABELS.update({DUEL: "⚔️ 決鬥", WHISKEY: "🥃 威士忌"})
UNDEAD_CHARACTERS = [
    Character("belle_star", "貝爾・史塔", "Belle Star", 8, "每次擲骰後，可把1個炸藥改成格林機槍；已擲出3個以上炸藥時不能使用。"),
    Character("chuck_wengam", "查克・溫甘", "Chuck Wengam", 8, "自己回合限1次，可失去1血，將1顆骰子轉成該骰任一面；已擲出3個以上炸藥時不能改炸藥。"),
    Character("greg_digger", "葛雷格・迪格", "Greg Digger", 7, "每個威士忌符號可以使用2次。"),
    Character("herb_hunter", "赫伯・杭特", "Herb Hunter", 8, "自己回合中，其他玩家若累計失去2血以上，必須再抽1枚決鬥傷口。"),
    Character("pat_brennan", "帕特・布倫南", "Pat Brennan", 8, "回合開始，可將1張憤怒卡從一位玩家移給另一位玩家，包括自己。"),
    Character("pixie_pete", "皮克西・皮特", "Pixie Pete", 9, "每次抽憤怒卡時，抽2張選1張，另一張洗回牌庫。"),
    Character("sam_the_healer", "治療師山姆", "Sam the Healer", 7, "自己回合每使用1個決鬥符號，可讓任意玩家回復1血；別人回合中回擊不觸發。"),
    Character("sean_mallory", "尚恩・馬洛里", "Sean Mallory", 8, "自己回合限1次，可重擲1顆決鬥骰；在別人的回合不能使用。"),
]
CHAR_BY_KEY.update({c.key: c for c in UNDEAD_CHARACTERS})
