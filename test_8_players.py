import asyncio
import json
import websockets
import os
import sys

# Import server components
import server

TEST_PORT = 8765

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
        self.ws = await websockets.connect(f"ws://127.0.0.1:{TEST_PORT}")
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
            # print(f"[{self.name} listen error: {e}]")
            pass

    async def send(self, action, **kwargs):
        payload = {"action": action, **kwargs}
        await self.ws.send(json.dumps(payload, ensure_ascii=False))

    async def close(self):
        if self.listen_task:
            self.listen_task.cancel()
        if self.ws:
            await self.ws.close()

async def run_8_player_simulation():
    print("=" * 60)
    print("🚀 НАЧАЛО ТЕСТА С 8 ИГРОКАМИ В «БУНКЕР 3.3»")
    print("=" * 60)

    # 1. Start server on TEST_PORT
    server_task = await websockets.serve(
        server.ws_handler,
        "127.0.0.1",
        TEST_PORT,
        process_request=server.http_process_request
    )
    print(f"✅ Тестовый сервер поднят на ws://127.0.0.1:{TEST_PORT}")

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
        for bot in bots:
            await bot.connect()

        # Step 1: Player 1 creates room
        host = bots[0]
        await host.send("create_room", name=host.name, avatar=host.avatar)
        await asyncio.sleep(0.3)
        room_code = host.room_code
        assert room_code, "Room code was not generated!"
        print(f"✅ Комната создана. Код: [{room_code}], Хост: {host.name} ({host.player_id})")

        # Step 2: Remaining 7 players join
        for i in range(1, 8):
            bot = bots[i]
            await bot.send("join_room", room_code=room_code, name=bot.name, avatar=bot.avatar)
            await asyncio.sleep(0.15)
            assert bot.room_code == room_code, f"{bot.name} failed to join room"
            print(f"  + {bot.name} присоединился ({bot.player_id})")

        await asyncio.sleep(0.2)
        assert len(host.state["players"]) == 8, f"Expected 8 players, got {len(host.state['players'])}"
        print(f"✅ Все 8 игроков в лобби. Вместимость бункера по правилам: {host.state['bunker_capacity']}")

        # Step 3: Start game
        print("\n--- Запуск партии ---")
        await host.send("start_game")
        await asyncio.sleep(0.4)

        assert host.state["status"] == "in_game"
        assert host.state["round"] == 1
        assert host.state["phase"] == "turns"
        cat = host.state["catastrophe"]
        print(f"🚨 Катастрофа: «{cat['name']}» — {cat['desc']}")
        bunker_r1 = host.state["bunker_threat_pairs"][0]
        print(f"📦 Отсек бункера R1: «{bunker_r1['bunker']['name']}» | Угроза R1: «{bunker_r1['threat']['name']}»")

        # Verify Round 1 rule: opening non-profession fails
        active_id = host.state["active_player_id"]
        active_bot = next(b for b in bots if b.player_id == active_id)
        print(f"\nТест правила Раунда 1: попытка вскрыть 'hobby' вместо 'profession' игроком {active_bot.name}...")
        prev_err_count = len(active_bot.unread_messages)
        await active_bot.send("reveal_card", category="hobby")
        await asyncio.sleep(0.2)
        err_msgs = [m for m in active_bot.unread_messages[prev_err_count:] if m.get("type") == "error"]
        assert len(err_msgs) > 0, "Server should have rejected opening non-profession in Round 1!"
        print(f"✅ Сервер корректно отклонил: «{err_msgs[0]['message']}»")

        # Play all 5 rounds
        categories_by_round = {
            1: "profession",
            2: "biology",
            3: "health",
            4: "hobby",
            5: "luggage"
        }

        for r in range(1, 6):
            print(f"\n==================== РАУНД {r} ====================")
            cat_to_open = categories_by_round[r]

            # 1. Turn phase: all surviving players open card
            while host.state["phase"] == "turns":
                active_id = host.state["active_player_id"]
                if not active_id:
                    break
                active_bot = next(b for b in bots if b.player_id == active_id)
                # Check player's hand for cat_to_open
                hand_card = active_bot.state["players"][0]["hand"].get(cat_to_open)
                # Or find their hand in active_bot.state
                my_hand = None
                for p in active_bot.state["players"]:
                    if p["id"] == active_bot.player_id:
                        my_hand = p["hand"]
                        break
                
                card_obj = my_hand.get(cat_to_open)
                if not card_obj or card_obj.get("revealed"):
                    # Find any unrevealed card
                    for cat_k, c in my_hand.items():
                        if not c.get("revealed"):
                            cat_to_open = cat_k
                            card_obj = c
                            break

                await active_bot.send("reveal_card", category=cat_to_open)
                await asyncio.sleep(0.15)
                print(f"  👁️ [{active_bot.name}] открыл {cat_to_open}: «{card_obj.get('name', '???')}»")

            await asyncio.sleep(0.2)
            assert host.state["phase"] == "debate", f"Expected debate phase, got {host.state['phase']}"
            print(f"✅ Все выжившие открыли карты Раунда {r}. Фаза: ДЕБАТЫ.")
            has_voting = host.state["round_has_voting"]
            exiles_count = host.state["round_exiles_count"]
            print(f"  Информация о голосовании: есть голосование={has_voting}, изгнаний={exiles_count}")

            if not has_voting:
                print("  ⚖️ В Раунде 1 изгнания нет (по правилам Бункер 3.3). Хост завершает раунд.")
                await host.send("skip_debate")
                await asyncio.sleep(0.3)
            else:
                # Host starts voting
                await host.send("start_voting")
                await asyncio.sleep(0.2)
                assert host.state["phase"] == "voting"
                print(f"🗳️ Открыто голосование Раунда {r}!")

                # In Round 2, let's intentionally test a TIE scenario to verify tie handling!
                if r == 2:
                    print("  🧪 ТЕСТ НИЧЬИ В ГОЛОСОВАНИИ:")
                    survivors = [b for b in bots if not next(p for p in host.state["players"] if p["id"] == b.player_id)["is_exiled"]]
                    # Split votes equally between survivor 0 and survivor 1: 4 votes for cand 0, 4 votes for cand 1
                    cand0 = survivors[0].player_id
                    cand1 = survivors[1].player_id
                    print(f"    Голосуем 4 голоса за {survivors[0].name} и 4 голоса за {survivors[1].name}")
                    for idx, sbot in enumerate(survivors):
                        target = cand0 if idx % 2 == 0 else cand1
                        await sbot.send("cast_vote", target_id=target)
                        await asyncio.sleep(0.08)

                    await asyncio.sleep(0.3)
                    assert host.state["phase"] == "tie_decision", f"Expected tie_decision phase, got {host.state['phase']}"
                    tie_data = host.state["tie_data"]
                    print(f"    ✅ Ничья успешно зафиксирована! Кандидаты: {tie_data['tied_candidate_names']}")
                    
                    # Test second round (revote)
                    print("    🔄 Хост выбирает ПЕРЕГОЛОСОВАНИЕ (2-й тур)...")
                    await host.send("resolve_tie_decision", choice="revote")
                    await asyncio.sleep(0.2)
                    assert host.state["phase"] == "voting"
                    assert host.state["is_tie_revote"] is True

                    # In 2nd round, vote: 5 for cand0, 3 for cand1
                    print(f"    Голосуем во 2-м туре: 5 за {survivors[0].name}, 3 за {survivors[1].name}")
                    for idx, sbot in enumerate(survivors):
                        target = cand0 if idx < 5 else cand1
                        await sbot.send("cast_vote", target_id=target)
                        await asyncio.sleep(0.08)

                    await asyncio.sleep(0.3)
                    assert host.state["phase"] == "vote_results", f"Expected vote_results, got {host.state['phase']}"
                    print(f"    ✅ Итоги 2-го тура: изгнан(а) {host.state['last_exiled']}!")
                else:
                    # Normal voting in rounds 3, 4, 5
                    survivors = [b for b in bots if not next(p for p in host.state["players"] if p["id"] == b.player_id)["is_exiled"]]
                    # Candidate to exile: pick the last survivor
                    target_to_exile = survivors[-1].player_id
                    target_name = survivors[-1].name
                    print(f"  Выжившие голосуют против {target_name}...")
                    for sbot in survivors:
                        await sbot.send("cast_vote", target_id=target_to_exile)
                        await asyncio.sleep(0.08)

                    await asyncio.sleep(0.3)
                    assert host.state["phase"] == "vote_results", f"Expected vote_results, got {host.state['phase']}"
                    print(f"  ✅ Итоги голосования: {host.state['last_exiled']} покидает Бункер!")

                survivor_count = host.state["survivors_count"]
                print(f"  👥 Осталось выживших: {survivor_count}")

                # Next round confirm
                await host.send("next_round_confirm")
                await asyncio.sleep(0.3)

        # Finale check!
        print("\n==================== ФИНАЛ ИГРЫ ====================")
        assert host.state["status"] == "finale"
        assert host.state["phase"] == "finale"
        survivors_in_finale = [p for p in host.state["players"] if not p["is_exiled"]]
        exiled_in_finale = [p for p in host.state["players"] if p["is_exiled"]]
        print(f"✅ В финал вышли ровно {len(survivors_in_finale)} игрока (вместимость бункера: {host.state['bunker_capacity']})!")
        print(f"   Выжившие: {', '.join(p['name'] for p in survivors_in_finale)}")
        print(f"   Изгнанные: {', '.join(p['name'] for p in exiled_in_finale)}")

        # Verify that for all survivors, all 6 cards are revealed in finale!
        for p in survivors_in_finale:
            all_rev = all(c.get("revealed") for c in p["hand"].values())
            assert all_rev, f"Player {p['name']} has unrevealed cards in finale!"
        print("✅ У всех выживших в финале открыта 6-я скрытая карта («Факт биографии»).")

        # Test Procedural / Gemini AI Analysis
        print("\n--- Запуск анализа выживания (AI Analysis) ---")
        await host.send("run_ai_analysis")
        # Wait up to 10 seconds for analysis
        for _ in range(50):
            await asyncio.sleep(0.2)
            if host.state.get("ai_analysis"):
                break

        ai = host.state["ai_analysis"]
        assert ai is not None, "AI analysis was not generated!"
        print(f"📊 Результат моделирования бортового ИИ:")
        print(f"   Статус: {ai.get('status')}")
        print(f"   Шанс выживания: {ai.get('survival_percent')}%")
        print(f"   Вердикт: {ai.get('verdict')}")
        print(f"   MVP: {ai.get('mvp', {}).get('name')} — {ai.get('mvp', {}).get('reason')}")
        print(f"   Источник проблем: {ai.get('troublemaker', {}).get('name')} — {ai.get('troublemaker', {}).get('reason')}")
        print(f"   Эпилог: {ai.get('epilogue')[:120]}...")

        print("\n🎉 ТЕСТ ИГРЫ С 8 ИГРОКАМИ ПОЛНОСТЬЮ УСПЕШНО ПРОЙДЕН! Все механики работают корректно.")

    finally:
        for b in bots:
            await b.close()
        server_task.close()
        await server_task.wait_closed()

if __name__ == "__main__":
    asyncio.run(run_8_player_simulation())
