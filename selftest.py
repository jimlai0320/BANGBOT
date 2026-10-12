import random
from game_engine import Game, add_ai, setup_game
from ai import run_ai_turn

def one(n, seed):
    g = Game(chat_id=seed, host_id=1)
    for _ in range(n):
        add_ai(g)
    setup_game(g, random.Random(seed))
    turns = 0
    while g.phase != "ended" and turns < 300:
        run_ai_turn(g)
        turns += 1
    assert g.phase == "ended", (n, turns)
    return turns, g.winner_text

if __name__ == "__main__":
    for n in range(3, 9):
        turns, winner = one(n, 100 + n)
        print(f"{n} 人 AI 測試：{turns} 回合 -> {winner}")
    print("SELFTEST OK")
