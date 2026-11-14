import asyncio
import json
import websockets
import sys

RENDER_WS_URL = "wss://bunker-wi5y.onrender.com"

class BotPlayer:
    def __init__(self, name, avatar):
        self.name = name
        self.avatar = avatar
        self.ws = None
        self.player_id = None
        self.room_code = None
        self.state = None
        self.unread_messages = []
        self.listen_task = None

    async def connect(self):
        self.ws = await websockets.connect(RENDER_WS_URL)
        self.listen_task = asyncio.create_task(self._listener())

    async def _listener(self):
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                msg_type = data.get("type")
                if msg_type == "state_update":
                    self.state = data["state"]
                elif msg_type == "room_joined":
                    self.room_code = data["room_code"]
                    self.player_id = data["my_id"]
                    self.state = data["state"]
                self.unread_messages.append(data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            pass

    async def send(self, action, **kwargs):
        payload = {"action": action, **kwargs}
        await self.ws.send(json.dumps(payload, ensure_ascii=False))

    async def close(self):
        if self.listen_task:
            self.listen_task.cancel()
        if self.ws:
            await self.ws.close()

async def run_render_test():
    print("=" * 60)
    print("🌐 ТЕСТИРОВАНИЕ ЖИВОГО СЕРВЕРА НА RENDER С 8 ИГРОКАМИ")
    print(f"URL: {RENDER_WS_URL}")
    print("=" * 60)

    player_names = [
        ("Алексей (Командир)", "👨‍✈️"),
        ("Елена (Биолог)", "👩‍🔬"),
        ("Дмитрий (Инженер)", "👷‍♂️"),
        ("Ольга (Врач)", "👩‍⚕️"),
        ("Михаил (Военный)", "🪖"),
        ("Анна (Агроном)", "👩‍🌾"),
        ("Сергей (Химик)", "🧑‍🔬"),
        ("Мария (Повар)", "👩‍🍳")
    ]

    bots = [BotPlayer(name, avatar) for name, avatar in player_names]

    try:
        print("1. Подключение 8 клиентов через WSS...")
        for bot in bots:
            await bot.connect()

        # Step 1: Host creates room
        host = bots[0]
        await host.send("create_room", name=host.name, avatar=host.avatar)
        await asyncio.sleep(0.5)
        room_code = host.room_code
        assert room_code, "Не удалось создать комнату на Render!"
        print(f"✅ Комната успешно создана на Render. Код: [{room_code}]")

        # Step 2: 7 players join
        for i in range(1, 8):
            bot = bots[i]
            await bot.send("join_room", room_code=room_code, name=bot.name, avatar=bot.avatar)
            await asyncio.sleep(0.2)
            assert bot.room_code == room_code
            print(f"  + {bot.name} подключился")

        await asyncio.sleep(0.5)
        assert len(host.state["players"]) == 8
        print(f"✅ Все 8 игроков в сборе. Вместимость убежища: {host.state['bunker_capacity']}")

        # Step 3: Start game
        print("\n2. Запуск игры...")
        await host.send("start_game")
        await asyncio.sleep(0.5)

        assert host.state["status"] == "in_game"
        cat = host.state["catastrophe"]
        print(f"🚨 Катастрофа: «{cat['name']}»")
        bunker_r1 = host.state["bunker_threat_pairs"][0]
        print(f"📦 Отсек: «{bunker_r1['bunker']['name']}» | Угроза: «{bunker_r1['threat']['name']}»")

        categories_by_round = {
            1: "profession",
            2: "biology",
            3: "health",
            4: "hobby",
            5: "luggage"
        }

        # Play 5 rounds
        for r in range(1, 6):
            print(f"\n--- РАУНД {r} ---")
            cat_to_open = categories_by_round[r]

            while host.state["phase"] == "turns":
                active_id = host.state["active_player_id"]
                if not active_id:
                    break
                active_bot = next(b for b in bots if b.player_id == active_id)
                
                my_hand = None
                for p in active_bot.state["players"]:
                    if p["id"] == active_bot.player_id:
                        my_hand = p["hand"]
                        break

                card_obj = my_hand.get(cat_to_open)
                if not card_obj or card_obj.get("revealed"):
                    for cat_k, c in my_hand.items():
                        if not c.get("revealed"):
                            cat_to_open = cat_k
                            card_obj = c
                            break

                await active_bot.send("reveal_card", category=cat_to_open)
                await asyncio.sleep(0.2)
                print(f"  👁️ [{active_bot.name}] открыл {cat_to_open}: «{card_obj.get('name', '???')}»")

            await asyncio.sleep(0.3)
            assert host.state["phase"] == "debate"
            print(f"  ⚖️ Дебаты Раунда {r}.")

            has_voting = host.state["round_has_voting"]
            if not has_voting:
                print("  ⏩ Раунд 1: голосование отсутствует. Завершение раунда.")
                await host.send("skip_debate")
                await asyncio.sleep(0.4)
            else:
                await host.send("start_voting")
                await asyncio.sleep(0.3)
                assert host.state["phase"] == "voting"
                print(f"  🗳️ Голосование Раунда {r} открыто.")

                # Voting: pick the last non-exiled survivor
                survivors = [b for b in bots if not next(p for p in host.state["players"] if p["id"] == b.player_id)["is_exiled"]]
                target = survivors[-1].player_id
                target_name = survivors[-1].name
                print(f"  Выжившие голосуют против: {target_name}")
                for sbot in survivors:
                    await sbot.send("cast_vote", target_id=target)
                    await asyncio.sleep(0.1)

                await asyncio.sleep(0.5)
                assert host.state["phase"] == "vote_results"
                print(f"  ❌ Изгнан(а): {host.state['last_exiled']}")
                print(f"  👥 Осталось выживших: {host.state['survivors_count']}")

                await host.send("next_round_confirm")
                await asyncio.sleep(0.5)

        # Finale
        print("\n3. ФИНАЛ ИГРЫ НА RENDER...")
        assert host.state["status"] == "finale"
        survivors_in_finale = [p for p in host.state["players"] if not p["is_exiled"]]
        print(f"✅ В финал вышли {len(survivors_in_finale)} игрока: {', '.join(p['name'] for p in survivors_in_finale)}")

        print("\n4. Бортовой ИИ Бункера...")
        await host.send("run_ai_analysis")
        for _ in range(40):
            await asyncio.sleep(0.3)
            if host.state.get("ai_analysis"):
                break

        ai = host.state["ai_analysis"]
        assert ai is not None, "ИИ анализ не получен!"
        print(f"📊 Шанс выживания: {ai.get('survival_percent')}%")
        print(f"   Вердикт: {ai.get('verdict')}")
        print(f"   MVP: {ai.get('mvp', {}).get('name')}")
        print(f"   Troublemaker: {ai.get('troublemaker', {}).get('name')}")
        print(f"   Эпилог: {ai.get('epilogue')[:100]}...")

        print("\n🎉 ВСЕ ТЕСТЫ НА ЖИВОМ RENDER (https://bunker-wi5y.onrender.com) ПРОШЛИ НА 100% УСПЕШНО!")

    finally:
        for b in bots:
            await b.close()

if __name__ == "__main__":
    asyncio.run(run_render_test())
