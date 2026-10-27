import sys
import asyncio
import json
import mimetypes
import os
import random
import socket
import string
import urllib.request
from pathlib import Path


# Configure UTF-8 for console output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import websockets
from websockets.http11 import Response
from websockets.datastructures import Headers


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CARDS_FILE = BASE_DIR / "cards.json"

# Load cards database
with open(CARDS_FILE, "r", encoding="utf-8") as f:
    CARDS_DB = json.load(f)

# Global Rooms State: room_code -> Room
ROOMS = {}

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def generate_room_code():
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        if code not in ROOMS:
            return code

class Player:
    def __init__(self, player_id, name, avatar, ws=None):
        self.id = player_id
        self.name = name
        self.avatar = avatar
        self.ws = ws
        self.is_connected = True
        self.is_exiled = False
        self.hand = {}  # category -> {card_data, revealed: bool}
        self.special_condition = None
        self.voted_for = None
        self.immunity_this_round = False

# Official Bunker 3.3 Exile Schedule per Player Count (N: {round: exiles})
EXILE_SCHEDULE = {
    2:  {1: 0, 2: 0, 3: 0, 4: 0, 5: 1},  # 1 in bunker, 1 exiled at round 5
    3:  {1: 0, 2: 0, 3: 0, 4: 1, 5: 1},  # 1 in bunker, 2 exiled
    4:  {1: 0, 2: 0, 3: 0, 4: 1, 5: 1},  # 2 in bunker, 2 exiled
    5:  {1: 0, 2: 0, 3: 1, 4: 1, 5: 1},  # 2 in bunker, 3 exiled
    6:  {1: 0, 2: 0, 3: 1, 4: 1, 5: 1},  # 3 in bunker, 3 exiled
    7:  {1: 0, 2: 1, 3: 1, 4: 1, 5: 1},  # 3 in bunker, 4 exiled
    8:  {1: 0, 2: 1, 3: 1, 4: 1, 5: 1},  # 4 in bunker, 4 exiled
    9:  {1: 0, 2: 1, 3: 1, 4: 1, 5: 2},  # 4 in bunker, 5 exiled (2 exiles in R5)
    10: {1: 0, 2: 1, 3: 1, 4: 1, 5: 2},  # 5 in bunker, 5 exiled
    11: {1: 0, 2: 1, 3: 1, 4: 2, 5: 2},  # 5 in bunker, 6 exiled
    12: {1: 0, 2: 1, 3: 1, 4: 2, 5: 2},  # 6 in bunker, 6 exiled
    13: {1: 0, 2: 1, 3: 2, 4: 2, 5: 2},  # 6 in bunker, 7 exiled
    14: {1: 0, 2: 1, 3: 2, 4: 2, 5: 2},  # 7 in bunker, 7 exiled
    15: {1: 0, 2: 2, 3: 2, 4: 2, 5: 2},  # 7 in bunker, 8 exiled
    16: {1: 0, 2: 2, 3: 2, 4: 2, 5: 2},  # 8 in bunker, 8 exiled
}

def get_exiles_for_round(total_players: int, round_num: int) -> int:
    if total_players in EXILE_SCHEDULE:
        return EXILE_SCHEDULE[total_players].get(round_num, 0)
    if round_num == 1:
        return 0
    bunker_capacity = max(1, total_players // 2)
    total_exiles_needed = total_players - bunker_capacity
    if round_num < 5:
        return 1 if total_exiles_needed >= (5 - round_num) else 0
    return max(0, total_exiles_needed)

class Room:
    def __init__(self, code, host_id):
        self.code = code
        self.host_id = host_id
        self.players = {}  # player_id -> Player
        self.status = "lobby"  # "lobby", "in_game", "voting", "vote_results", "finale"
        self.round = 1
        self.max_rounds = 5
        self.phase = "lobby"
        self.catastrophe = None
        self.bunker_threat_pairs = []  # list of {bunker: {...}, threat: {...}, revealed: bool}
        self.turn_order = []  # list of player_ids
        self.active_turn_index = 0
        self.timer_seconds = 0
        self.timer_task = None
        self.timer_paused = False
        self.log = []
        self.votes = {}  # target_id -> list of voter names (for reveal)
        self.last_exiled = None
        self.ai_analysis = None
        self.ai_loading = False

    def get_bunker_capacity(self):
        return max(1, len(self.players) // 2)

    def get_exiles_for_current_round(self):
        return get_exiles_for_round(len(self.players), self.round)

    def has_voting_in_round(self, round_num=None):
        r = round_num if round_num is not None else self.round
        return get_exiles_for_round(len(self.players), r) > 0

    def stop_timer(self):
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
        self.timer_task = None
        self.timer_paused = False

    def start_timer(self, seconds, auto_phase_on_zero=None):
        self.stop_timer()
        self.timer_seconds = seconds
        self.timer_paused = False
        self.timer_task = asyncio.create_task(self._timer_loop(auto_phase_on_zero))

    async def _timer_loop(self, auto_phase_on_zero):
        try:
            while self.timer_seconds > 0:
                await asyncio.sleep(1)
                if not self.timer_paused:
                    self.timer_seconds -= 1
                    await broadcast_timer_tick(self)

            if auto_phase_on_zero == "voting" and self.phase == "debate":
                if self.has_voting_in_round(self.round):
                    self.phase = "voting"
                    for p in self.players.values():
                        p.voted_for = None
                    self.add_log(f"🗳️ Время дебатов истекло! Начинается тайное голосование Раунда {self.round}.")
                else:
                    self.add_log(f"⚖️ Время обсуждения Раунда {self.round} истекло. В этом раунде никто не изгоняется — переход к Раунду {self.round + 1}!")
                    advance_round(self)
                await broadcast_room(self)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Timer loop error: {e}]")

    def add_log(self, text):


        self.log.append(text)
        if len(self.log) > 40:
            self.log.pop(0)

    def get_active_player_id(self):
        if not self.turn_order:
            return None
        valid_players = [pid for pid in self.turn_order if not self.players[pid].is_exiled]
        if not valid_players:
            return None
        return self.turn_order[self.active_turn_index % len(self.turn_order)]

    def sanitize_for(self, viewer_id):
        players_data = []
        for pid in self.turn_order if self.turn_order else list(self.players.keys()):
            p = self.players.get(pid)
            if not p:
                continue
            is_self = (p.id == viewer_id)
            
            # Format hand
            sanitized_hand = {}
            for cat, card_obj in p.hand.items():
                if card_obj.get("revealed", False) or p.is_exiled or is_self:
                    sanitized_hand[cat] = {
                        **card_obj,
                        "revealed": card_obj.get("revealed", False) or p.is_exiled
                    }
                else:
                    sanitized_hand[cat] = {
                        "category": cat,
                        "revealed": False
                    }

            # Special condition
            spec = None
            if is_self and p.special_condition:
                spec = p.special_condition

            players_data.append({
                "id": p.id,
                "name": p.name,
                "avatar": p.avatar,
                "is_host": (p.id == self.host_id),
                "is_connected": p.is_connected,
                "is_exiled": p.is_exiled,
                "is_active_turn": (p.id == self.get_active_player_id() and self.status == "in_game" and self.phase == "turns"),
                "has_voted": (p.voted_for is not None),
                "hand": sanitized_hand,
                "special_condition": spec
            })

        # Sanitize bunker threat pairs
        pairs_data = []
        for i, pair in enumerate(self.bunker_threat_pairs):
            if pair["revealed"]:
                pairs_data.append({
                    "round": i + 1,
                    "revealed": True,
                    "bunker": pair["bunker"],
                    "threat": pair["threat"]
                })
            else:
                pairs_data.append({
                    "round": i + 1,
                    "revealed": False
                })

        return {
            "room_code": self.code,
            "host_id": self.host_id,
            "my_id": viewer_id,
            "status": self.status,
            "round": self.round,
            "max_rounds": self.max_rounds,
            "phase": self.phase,
            "bunker_capacity": self.get_bunker_capacity(),
            "total_players": len(self.players),
            "survivors_count": sum(1 for p in self.players.values() if not p.is_exiled),
            "round_has_voting": self.has_voting_in_round(),
            "round_exiles_count": self.get_exiles_for_current_round(),
            "catastrophe": self.catastrophe,
            "bunker_threat_pairs": pairs_data,
            "active_player_id": self.get_active_player_id(),
            "timer_seconds": self.timer_seconds,
            "timer_paused": self.timer_paused,
            "players": players_data,
            "log": self.log[-15:],
            "last_exiled": self.last_exiled,
            "votes_summary": self.votes if self.phase == "vote_results" else None,
            "ai_analysis": self.ai_analysis,
            "ai_loading": self.ai_loading
        }


async def broadcast_timer_tick(room):
    msg = json.dumps({
        "type": "timer_tick",
        "seconds": room.timer_seconds,
        "paused": room.timer_paused
    })
    for pid, player in list(room.players.items()):
        if player.ws and player.is_connected:
            try:
                await player.ws.send(msg)
            except Exception:
                player.is_connected = False

async def broadcast_room(room):

    for pid, player in list(room.players.items()):
        if player.ws and player.is_connected:
            try:
                payload = {
                    "type": "state_update",
                    "state": room.sanitize_for(pid)
                }
                await player.ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception:
                player.is_connected = False

def init_game(room):
    room.status = "in_game"
    room.round = 1
    room.phase = "turns"
    room.last_exiled = None
    room.votes = {}
    room.ai_analysis = None
    room.ai_loading = False


    # Pick Catastrophe
    room.catastrophe = random.choice(CARDS_DB["catastrophes"])

    # Pick 5 Bunker cards and 5 Threats
    bunker_deck = random.sample(CARDS_DB["bunker"], k=min(5, len(CARDS_DB["bunker"])))
    threat_deck = random.sample(CARDS_DB["threats"], k=min(5, len(CARDS_DB["threats"])))

    room.bunker_threat_pairs = []
    for i in range(5):
        room.bunker_threat_pairs.append({
            "bunker": bunker_deck[i],
            "threat": threat_deck[i],
            "revealed": (i == 0) # Round 1 pair starts revealed!
        })

    # Prepare Decks for players
    p_keys = list(room.players.keys())
    random.shuffle(p_keys)
    room.turn_order = p_keys
    room.active_turn_index = 0

    n = len(p_keys)
    prof_deck = random.sample(CARDS_DB["professions"], k=n)
    bio_deck = random.sample(CARDS_DB["biology"], k=n)
    hlth_deck = random.sample(CARDS_DB["health"], k=n)
    hob_deck = random.sample(CARDS_DB["hobbies"], k=n)
    lug_deck = random.sample(CARDS_DB["luggage"], k=n)
    fct_deck = random.sample(CARDS_DB["facts"], k=n)
    spc_deck = random.sample(CARDS_DB["special_conditions"], k=n)

    for i, pid in enumerate(p_keys):
        p = room.players[pid]
        p.is_exiled = False
        p.voted_for = None
        p.immunity_this_round = False
        p.hand = {
            "profession": {**prof_deck[i], "category": "profession", "revealed": False},
            "biology": {**bio_deck[i], "category": "biology", "revealed": False},
            "health": {**hlth_deck[i], "category": "health", "revealed": False},
            "hobby": {**hob_deck[i], "category": "hobby", "revealed": False},
            "luggage": {**lug_deck[i], "category": "luggage", "revealed": False},
            "fact": {**fct_deck[i], "category": "fact", "revealed": False}
        }
        p.special_condition = {**spc_deck[i], "played": False}

    bunker_capacity = room.get_bunker_capacity()
    room.add_log(f"🚨 ТРЕВОГА! Началась катастрофа: «{room.catastrophe['name']}»")
    room.add_log(f"🛡️ Вместимость бункера: {bunker_capacity} из {len(p_keys)} выживших (половина участников).")
    room.add_log(f"📦 Раунд 1: открыт отсек Бункера «{bunker_deck[0]['name']}» и Угроза «{threat_deck[0]['name']}»")
    room.add_log(f"🎤 Очередь игрока {room.players[room.get_active_player_id()].name} — в 1-м раунде вскройте Профессию! (В 1-м раунде изгнания нет)")
    room.start_timer(45)

def next_player_turn(room):
    non_exiled = [pid for pid in room.turn_order if not room.players[pid].is_exiled]
    if not non_exiled:
        return

    # Check if all non-exiled players have revealed a card in this round
    curr_target_revealed = room.round
    unrevealed_exist = False
    for pid in non_exiled:
        p = room.players[pid]
        rev_count = sum(1 for c in p.hand.values() if c.get("revealed", False))
        if rev_count < curr_target_revealed:
            unrevealed_exist = True
            break

    if not unrevealed_exist:
        # All players opened cards for this round -> Move to debate phase
        room.phase = "debate"
        exiles = room.get_exiles_for_current_round()
        if exiles > 0:
            room.add_log(f"⚖️ Раунд {room.round}: Все карты вскрыты! Фаза открытых дебатов перед голосованием (будет изгнан: {exiles}).")
        else:
            room.add_log(f"⚖️ Раунд {room.round}: Все карты вскрыты! Фаза обсуждения (по правилам в этом раунде никто не изгоняется).")
        room.start_timer(60, auto_phase_on_zero="voting")
    else:
        # Move to next player who needs to reveal
        for _ in range(len(room.turn_order)):
            room.active_turn_index = (room.active_turn_index + 1) % len(room.turn_order)
            curr_pid = room.get_active_player_id()
            p = room.players[curr_pid]
            rev_count = sum(1 for c in p.hand.values() if c.get("revealed", False))
            if not p.is_exiled and rev_count < curr_target_revealed:
                break
        active_p = room.players[room.get_active_player_id()]
        room.add_log(f"👉 Ход переходит к: {active_p.name}. Выберите карту для вскрытия!")
        room.start_timer(45)


def resolve_voting(room):
    # Collect votes only from NON-EXILED players
    vote_counts = {}
    voter_map = {}
    for pid, p in room.players.items():
        if not p.is_exiled and p.voted_for:
            target = p.voted_for
            if target in room.players and not room.players[target].is_exiled:
                vote_counts[target] = vote_counts.get(target, 0) + 1
                if target not in voter_map:
                    voter_map[target] = []
                voter_map[target].append(p.name)

    room.votes = {
        room.players[tid].name: {
            "count": cnt,
            "voters": voter_map.get(tid, [])
        } for tid, cnt in vote_counts.items() if tid in room.players
    }

    if not vote_counts:
        room.stop_timer()
        room.add_log("⚖️ Голоса не были поданы. Никто не изгнан в этом раунде.")
        advance_round(room)
        return

    num_exiles = max(1, room.get_exiles_for_current_round())
    sorted_candidates = sorted(
        vote_counts.keys(),
        key=lambda tid: (vote_counts[tid], random.random()),
        reverse=True
    )
    to_exile_ids = sorted_candidates[:min(num_exiles, len(sorted_candidates))]

    exiled_names = []
    for exiled_id in to_exile_ids:
        exiled_player = room.players[exiled_id]
        exiled_player.is_exiled = True
        exiled_names.append(exiled_player.name)
        # In Bunker, exiled player reveals all remaining cards!
        for cat, c in exiled_player.hand.items():
            c["revealed"] = True

    room.last_exiled = ", ".join(exiled_names)
    room.stop_timer()
    room.phase = "vote_results"
    room.add_log(f"❌ ИЗГНАНИЕ: {room.last_exiled} покидает(ют) Бункер по итогам голосования!")
    room.add_log(f"📢 Все карты {room.last_exiled} вскрыты. Изгнанные участники больше не участвуют в голосовании.")

def advance_round(room):
    if room.round >= room.max_rounds:
        # Move to FINALE!
        room.stop_timer()
        room.status = "finale"
        room.phase = "finale"
        # Reveal 6th card for survivors
        for p in room.players.values():
            if not p.is_exiled:
                for c in p.hand.values():
                    c["revealed"] = True
        room.add_log("🏁 Раунд 5 завершён! Выжившие входят в Бункер. Начинается ФИНАЛ!")
    else:
        room.round += 1
        room.phase = "turns"
        # Reveal new Bunker + Threat pair
        if room.round - 1 < len(room.bunker_threat_pairs):
            room.bunker_threat_pairs[room.round - 1]["revealed"] = True
            b_name = room.bunker_threat_pairs[room.round - 1]["bunker"]["name"]
            t_name = room.bunker_threat_pairs[room.round - 1]["threat"]["name"]
            room.add_log(f"📦 Раунд {room.round}: Вскрыты отсек «{b_name}» и Угроза «{t_name}»!")

        # Reset votes and turn index
        for p in room.players.values():
            p.voted_for = None
            p.immunity_this_round = False
        
        # Advance turn order
        room.active_turn_index = (room.round - 1) % len(room.turn_order)
        # Ensure active player is not exiled
        while room.players[room.get_active_player_id()].is_exiled:
            room.active_turn_index = (room.active_turn_index + 1) % len(room.turn_order)

        active_p = room.players[room.get_active_player_id()]
        room.add_log(f"🎤 Раунд {room.round}: Первым карту открывает {active_p.name}.")
        room.start_timer(45)

def procedural_ai_analysis(cat, survivors, exiled, revealed_bunkers, revealed_threats):

    if not survivors:
        return {
            "survival_percent": 0,
            "status": "ВЫМИРАНИЕ",
            "title": "Пустой бункер",
            "verdict": "В бункер никто не вошёл. Гермошлюзы запечатаны на 365 дней за гробовой тишиной.",
            "timeline": [],
            "mvp": {"name": "Никто", "reason": "Бункер остался необитаем."},
            "troublemaker": {"name": "Никто", "reason": "Никто не выжил."},
            "epilogue": "Через 365 дней автоматика открыла шлюз, но навстречу солнцу вылетел лишь сухой подземный сквозняк."
        }

    score = 45
    medics = [s for s in survivors if any(w in s['profession'].lower() for w in ['врач', 'хирург', 'вирусолог', 'диагност'])]
    techs = [s for s in survivors if any(w in s['profession'].lower() for w in ['инженер', 'химик', 'слесарь', 'электрик', 'хакер', 'робот', 'конструктор'])]
    fighters = [s for s in survivors if any(w in s['profession'].lower() for w in ['военный', 'спасатель', 'охотник', 'егерь', 'ликвидатор', 'пожарный'])]
    fertile = [s for s in survivors if 'фертилен' in s['biology'].lower() or 'фертильна' in s['biology'].lower() or 'беременна' in s['biology'].lower()]

    score += len(medics) * 14
    score += len(techs) * 12
    score += len(fighters) * 10
    score += min(len(fertile) * 8, 16)

    # Health penalties and perks
    for s in survivors:
        hlth = s['health'].lower()
        if any(w in hlth for w in ['рак', 'диабет', 'астма', 'зависимость', 'туберкулез', 'викодин']):
            score -= 6
        if any(w in hlth for w in ['идеально', 'иммунитет', 'регенерация']):
            score += 5

    score = max(15, min(94, score + random.randint(-4, 6)))

    status = "ПОЛНЫЙ УСПЕХ" if score >= 70 else ("ЧАСТИЧНЫЙ УСПЕХ" if score >= 40 else "КОЛОНИЯ ВЫМЕРЛА")
    title = "Операция «Новый рассвет»" if score >= 70 else ("Борьба за выживание" if score >= 40 else "Трагедия в изоляции")

    mvp = random.choice(medics or techs or fighters or survivors)
    troublemakers = [s for s in survivors if s != mvp]
    troublemaker = random.choice(troublemakers) if troublemakers else mvp

    cat_name = cat.get("name", "Глобальная катастрофа")
    bunker_feature = revealed_bunkers[0] if revealed_bunkers else "аварийные запасы"

    return {
        "survival_percent": score,
        "status": status,
        "title": title,
        "verdict": f"Бортовой ИИ смоделировал 365 дней изоляции. Вероятность успешного выживания колонии составила {score}%. " +
                   (f"Ключевым фактором спасения стала сплочённая работа специалистов." if score >= 50 else "Команда столкнулась с острой нехваткой критических ресурсов."),
        "timeline": [
            {
                "period": "Месяцы 1–3: Обустройство и быт",
                "event": f"{mvp['name']} в роли «{mvp['profession']}» помог наладить быт и настроить {bunker_feature}. Раздача пайков прошла успешно."
            },
            {
                "period": "Месяцы 4–6: Отражение кризиса",
                "event": f"Бункер столкнулся с угрозой. Ситуацию стабилизировал инвентарь: {mvp['luggage']} и своевременные действия команды."
            },
            {
                "period": "Месяцы 7–9: Психологический барьер",
                "event": f"Обострились скрытые факторы ({troublemaker['fact']}). Напряжение в отсеках росло, но группа сохранила дисциплину."
            },
            {
                "period": "Месяцы 10–12: Рождение будущего и финал",
                "event": f"Запасы фильтров подошли к концу, но к моменту разгерметизации колония сохранила ядро выживших для нового мира."
            }
        ],
        "mvp": {
            "name": mvp["name"],
            "reason": f"Профессиональные навыки ({mvp['profession']}) и багаж сыграли решающую роль в поддержании систем жизнеобеспечения."
        },
        "troublemaker": {
            "name": troublemaker["name"],
            "reason": f"Особенность здоровья ({troublemaker['health']}) и черты характера создавали дополнительную нагрузку на команду."
        },
        "epilogue": f"Через 365 дней зашипели пневматические приводы и тяжелая бронедверь Бункера медленно отворилась. "
                    f"На фоне последствий катаклизма «{cat_name}» выжившие сделали свой первый вдох очистившегося воздуха. "
                    f"Человечество получило второй шанс."
    }

def generate_bunker_ai_analysis(room, api_key_override=None):
    api_key = (api_key_override or os.environ.get("GEMINI_API_KEY", "")).strip()

    cat = room.catastrophe or {"name": "Глобальный катаклизм", "desc": "Поверхность непригодна для жизни."}
    survivors = []
    exiled = []
    for p in room.players.values():
        p_info = {
            "name": p.name,
            "avatar": p.avatar,
            "profession": p.hand.get("profession", {}).get("name", "Неизвестно"),
            "biology": p.hand.get("biology", {}).get("name", "Неизвестно"),
            "health": p.hand.get("health", {}).get("name", "Неизвестно"),
            "hobby": p.hand.get("hobby", {}).get("name", "Неизвестно"),
            "luggage": p.hand.get("luggage", {}).get("name", "Неизвестно"),
            "fact": p.hand.get("fact", {}).get("name", "Неизвестно")
        }
        if p.is_exiled:
            exiled.append(p_info)
        else:
            survivors.append(p_info)

    revealed_bunkers = [p["bunker"]["name"] for p in room.bunker_threat_pairs if p.get("revealed")]
    revealed_threats = [p["threat"]["name"] for p in room.bunker_threat_pairs if p.get("revealed")]

    if api_key:
        try:
            prompt = f"""
Ты — аналитический, реалистичный суперкомпьютер убежища в настольной игре «Бункер 3.3» (в стиле Fallout Overseer и GLaDOS).
Смоделируй итоги выживания группы людей в герметичном бункере на 1 год (365 дней).

ПАРАМЕТРЫ ПАРТИИ:
- Катастрофа: {cat.get('name')} ({cat.get('desc')})
- Исследованные отсеки бункера: {", ".join(revealed_bunkers) if revealed_bunkers else "Стандартный бункер"}
- Открытые Угрозы бункера: {", ".join(revealed_threats) if revealed_threats else "Неизвестные риски"}

ВЫЖИВШИЕ В БУНКЕРЕ ({len(survivors)} чел.):
{json.dumps(survivors, ensure_ascii=False, indent=2)}

ИЗГНАННЫЕ:
{", ".join([p["name"] + " (" + p["profession"] + ")" for p in exiled]) if exiled else "Никого"}

ТРЕБОВАНИЯ:
Оцени шансы группы на основе синергии навыков, репродуктивной способности (фертильности), багажа против угрозы и катастрофы.
Верни СТРОГО валидный JSON следующей структуры:
{{
  "survival_percent": 75,
  "status": "ПОЛНЫЙ УСПЕХ" или "ЧАСТИЧНЫЙ УСПЕХ" или "КОЛОНИЯ ВЫМЕРЛА",
  "title": "Краткое название исхода",
  "verdict": "2-3 предложения вердикта бортового компьютера",
  "timeline": [
    {{"period": "Месяцы 1–3: Обустройство и быт", "event": "Как обустроились..."}},
    {{"period": "Месяцы 4–6: Отражение Угрозы", "event": "Как справились с угрозой..."}},
    {{"period": "Месяцы 7–9: Психология и здоровье", "event": "Обострение болезней и быт..."}},
    {{"period": "Месяцы 10–12: Рождение потомства и финал", "event": "Итог перед открытием дверей..."}}
  ],
  "mvp": {{"name": "Имя", "reason": "Почему стал главным спасителем"}},
  "troublemaker": {{"name": "Имя", "reason": "Почему создал больше всего проблем"}},
  "epilogue": "Художественный рассказ о том, что увидели выжившие при открытии дверей через год."
}}
"""
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.8
                }
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=18) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                text_out = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_out.startswith("```"):
                    text_out = text_out.split("\n", 1)[1]
                    if text_out.endswith("```"):
                        text_out = text_out.rsplit("\n", 1)[0]
                return json.loads(text_out)
        except Exception as e:
            print(f"[Gemini API Call failed: {e}], using procedural fallback")

    return procedural_ai_analysis(cat, survivors, exiled, revealed_bunkers, revealed_threats)

# HTTP Static Handler

def http_process_request(connection, request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None  # Upgrade to WebSocket

    path = request.path.split("?")[0].lstrip("/")
    if not path or path == "":
        path = "index.html"

    file_path = STATIC_DIR / path
    if path == "cards.json":
        file_path = CARDS_FILE

    if not file_path.is_file() or not file_path.exists():
        headers = Headers([("Content-Type", "text/plain; charset=utf-8")])
        return Response(404, "Not Found", headers, b"404: File Not Found")

    content_type, _ = mimetypes.guess_type(str(file_path))
    if not content_type:
        content_type = "application/octet-stream"
    if "text" in content_type or "javascript" in content_type or "json" in content_type:
        content_type += "; charset=utf-8"

    try:
        data = file_path.read_bytes()
        headers = Headers([
            ("Content-Type", content_type),
            ("Content-Length", str(len(data))),
            ("Cache-Control", "no-cache")
        ])
        return Response(200, "OK", headers, data)
    except Exception as e:
        headers = Headers([("Content-Type", "text/plain; charset=utf-8")])
        return Response(500, "Error", headers, f"500: {e}".encode("utf-8"))

# WebSocket Message Handler
async def ws_handler(websocket):
    current_room_code = None
    current_player_id = None

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("action")

            if msg_type == "create_room":
                name = data.get("name", "Игрок 1").strip() or "Командир"
                avatar = data.get("avatar", "👨‍🚀")
                player_id = "p_" + "".join(random.choices(string.digits, k=6))
                room_code = generate_room_code()

                room = Room(room_code, player_id)
                player = Player(player_id, name, avatar, ws=websocket)
                room.players[player_id] = player
                room.turn_order = [player_id]
                room.add_log(f"🟢 Создан новый Бункер [{room_code}]. Командир: {name}")

                ROOMS[room_code] = room
                current_room_code = room_code
                current_player_id = player_id

                await websocket.send(json.dumps({
                    "type": "room_joined",
                    "room_code": room_code,
                    "my_id": player_id,
                    "state": room.sanitize_for(player_id)
                }, ensure_ascii=False))

            elif msg_type == "join_room":
                room_code = data.get("room_code", "").strip().upper()
                name = data.get("name", "").strip() or f"Выживший {random.randint(10,99)}"
                avatar = data.get("avatar", "🤠")
                saved_id = data.get("saved_player_id")

                if room_code not in ROOMS:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": f"Бункер [{room_code}] не найден. Проверьте код!"
                    }, ensure_ascii=False))
                    continue

                room = ROOMS[room_code]

                # Check reconnect
                if saved_id and saved_id in room.players:
                    player = room.players[saved_id]
                    player.ws = websocket
                    player.is_connected = True
                    current_room_code = room_code
                    current_player_id = saved_id
                    room.add_log(f"📶 {player.name} переподключился к убежищу.")
                else:
                    if room.status != "lobby":
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "В этом бункере уже идёт игра! Дождитесь окончания партии."
                        }, ensure_ascii=False))
                        continue

                    player_id = "p_" + "".join(random.choices(string.digits, k=6))
                    player = Player(player_id, name, avatar, ws=websocket)
                    room.players[player_id] = player
                    room.turn_order.append(player_id)
                    current_room_code = room_code
                    current_player_id = player_id
                    room.add_log(f"👋 {name} {avatar} прибыл к шлюзу бункера.")

                await websocket.send(json.dumps({
                    "type": "room_joined",
                    "room_code": room_code,
                    "my_id": current_player_id,
                    "state": room.sanitize_for(current_player_id)
                }, ensure_ascii=False))
                await broadcast_room(room)

            elif msg_type == "start_game":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if current_player_id != room.host_id:
                    await websocket.send(json.dumps({"type": "error", "message": "Только создатель комнаты может запустить игру!"}, ensure_ascii=False))
                    continue

                if len(room.players) < 2:
                    await websocket.send(json.dumps({"type": "error", "message": "Для игры нужно минимум 2 игрока!"}, ensure_ascii=False))
                    continue

                init_game(room)
                await broadcast_room(room)

            elif msg_type == "reveal_card":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if room.status != "in_game" or room.phase != "turns":
                    continue

                active_pid = room.get_active_player_id()
                if current_player_id != active_pid:
                    await websocket.send(json.dumps({"type": "error", "message": "Сейчас не ваш ход!"}, ensure_ascii=False))
                    continue

                category = data.get("category")
                player = room.players[current_player_id]

                # Rule check for Round 1
                if room.round == 1 and category != "profession":
                    await websocket.send(json.dumps({"type": "error", "message": "В 1-м раунде все обязаны открыть Профессию!"}, ensure_ascii=False))
                    continue

                card = player.hand.get(category)
                if not card or card.get("revealed", False):
                    continue

                card["revealed"] = True
                room.timer_seconds = 30  # 30-second speech timer
                room.add_log(f"👁️ {player.name} вскрыл {card.get('badge', category)}: «{card['name']}» {card.get('icon','')}")

                # Automatically or manually progress turn
                next_player_turn(room)
                await broadcast_room(room)

            elif msg_type in ("start_voting", "skip_debate"):
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if current_player_id != room.host_id:
                    continue
                room.stop_timer()
                if room.has_voting_in_round(room.round):
                    room.phase = "voting"
                    for p in room.players.values():
                        p.voted_for = None
                    room.add_log(f"🗳️ Командир завершил дебаты! Тайное голосование Раунда {room.round} открыто.")
                else:
                    room.add_log(f"⏩ Командир завершил Раунд {room.round}. По правилам никто не изгоняется — переход к Раунду {room.round + 1}.")
                    advance_round(room)
                await broadcast_room(room)

            elif msg_type == "extend_timer":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if current_player_id != room.host_id:
                    continue
                add_sec = int(data.get("seconds", 30))
                room.timer_seconds += add_sec
                room.add_log(f"⏱️ Командир продлил таймер на +{add_sec} сек.")
                await broadcast_timer_tick(room)
                await broadcast_room(room)

            elif msg_type == "toggle_pause_timer":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if current_player_id != room.host_id:
                    continue
                room.timer_paused = not room.timer_paused
                status_txt = "поставлен на паузу ⏸️" if room.timer_paused else "возобновлён ⏵"
                room.add_log(f"⏱️ Таймер {status_txt}.")
                await broadcast_timer_tick(room)
                await broadcast_room(room)

            elif msg_type == "force_next_turn":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if current_player_id != room.host_id:
                    continue
                room.add_log("👉 Командир принудительно передал ход следующему выжившему.")
                next_player_turn(room)
                await broadcast_room(room)


            elif msg_type == "cast_vote":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if room.phase != "voting":
                    continue

                voter = room.players.get(current_player_id)
                if not voter or voter.is_exiled:
                    # Exiled players do NOT vote
                    continue

                target_id = data.get("target_id")
                target_player = room.players.get(target_id)
                if not target_player or target_player.is_exiled:
                    # Cannot vote for an exiled player
                    continue

                voter.voted_for = target_id
                room.add_log(f"📝 {voter.name} заполнил тайный бюллетень.")

                # Check if all eligible (non-exiled and connected) players voted
                eligible = [p for p in room.players.values() if not p.is_exiled and p.is_connected]
                all_voted = len(eligible) > 0 and all(p.voted_for is not None for p in eligible)
                if all_voted:
                    resolve_voting(room)

                await broadcast_room(room)

            elif msg_type == "end_voting_force":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if current_player_id != room.host_id:
                    continue
                resolve_voting(room)
                await broadcast_room(room)

            elif msg_type == "next_round_confirm":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if current_player_id != room.host_id:
                    continue
                advance_round(room)
                await broadcast_room(room)

            elif msg_type == "play_special":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                player = room.players.get(current_player_id)
                if not player or not player.special_condition or player.special_condition.get("played", False):
                    continue

                spc = player.special_condition
                spc["played"] = True
                room.add_log(f"⚡ {player.name} разыграл Особое Условие: «{spc['name']}»!")

                # In-game effect handlers
                if spc["id"] == "spc_diplomatic_immunity":
                    player.immunity_this_round = True
                    room.add_log(f"🛡️ {player.name} получил дипломатический иммунитет на этот раунд!")
                elif spc["id"] == "spc_its_not_lupus":
                    player.hand["health"]["name"] = "Идеально здоров (Вылечен)"
                    player.hand["health"]["badge"] = "Здоров"
                    player.hand["health"]["desc"] = "Полностью здоров благодаря своевременному диагнозу."
                    player.hand["health"]["revealed"] = True
                    room.add_log(f"🩺 Карта Здоровья игрока {player.name} заменена на «Идеально здоров»!")

                await broadcast_room(room)

            elif msg_type == "run_ai_analysis":
                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if room.status != "finale":
                    continue
                if current_player_id != room.host_id:
                    continue

                api_key_override = data.get("api_key")
                room.ai_loading = True
                room.add_log("🧠 Бортовой ИИ Бункера начал диагностику и моделирование выживания...")
                await broadcast_room(room)

                analysis = await asyncio.to_thread(generate_bunker_ai_analysis, room, api_key_override)
                room.ai_analysis = analysis
                room.ai_loading = False
                room.add_log(f"📊 ИИ завершил расчёт: Шанс выживания — {analysis.get('survival_percent', 50)}%!")
                await broadcast_room(room)

            elif msg_type == "reset_game":

                if not current_room_code or current_room_code not in ROOMS:
                    continue
                room = ROOMS[current_room_code]
                if current_player_id != room.host_id:
                    continue
                init_game(room)
                await broadcast_room(room)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if current_room_code and current_room_code in ROOMS and current_player_id:
            room = ROOMS[current_room_code]
            if current_player_id in room.players:
                room.players[current_player_id].is_connected = False
                room.add_log(f"🔌 {room.players[current_player_id].name} временно потерял связь.")
                await broadcast_room(room)

async def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", 8000))
    local_ip = get_local_ip()


    print("=" * 64)
    try:
        print("☢️  СЕРВЕР «БУНКЕР 3.3» (Web Edition) ЗАПУЩЕН! ☢️")
        print(f"🖥️  Играть на этом компьютере:    http://localhost:{port}")
        print(f"📱  Играть с телефонов по Wi-Fi:   http://{local_ip}:{port}")
    except Exception:
        print("[!] SERVER BUNKER 3.3 STARTED!")
        print(f"Local: http://localhost:{port}")
        print(f"Wi-Fi: http://{local_ip}:{port}")
    print("=" * 64)


    server = await websockets.serve(
        ws_handler,
        host,
        port,
        process_request=http_process_request
    )
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
