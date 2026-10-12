"""不連 Telegram 的圓桌座位/距離回歸測試。"""
import math
import random
from renderer import LAYOUTS, CLOCKWISE_SEATS, render_board
from game_engine import Game, add_ai, setup_game, distance, valid_targets_for_face
from data import BULL1, BULL2

for n in range(3, 9):
    game = Game(chat_id=n, host_id=1)
    for _ in range(n):
        add_ai(game)
    setup_game(game, random.Random(n+10))
    game.players[0].character_key = 'bart_cassidy'
    game.current_idx = 0
    game.phase = 'resolving'
    game.pending_action = {'type':'shot', 'face': BULL1, 'amount':1}
    coords = [LAYOUTS[n]['seats'][CLOCKWISE_SEATS[n][i]]['panel'] for i in range(n)]
    angles = [math.atan2(x-724, 480-y) % (2*math.pi) for x,y in coords]
    assert all(0 < ((angles[(i+1)%n] - angles[i]) % (2*math.pi)) < 3.2 for i in range(n)), n
    assert set(valid_targets_for_face(game, 0, BULL1)) == {1, n-1}, n
    assert distance(game, 0, 1) == 1, n
    assert render_board(game).getbuffer().nbytes > 10000, n

# 2/3 位玩家還活著時，蘿絲・杜蘭的 2 號靶心不能變成無目標。
game = Game(chat_id=8, host_id=1)
for _ in range(5):
    add_ai(game)
setup_game(game, random.Random(50))
game.players[0].character_key = 'rose_doolan'
game.players[3].alive = False
game.players[4].alive = False
assert set(valid_targets_for_face(game, 0, BULL2)) == {1,2}
game.players[2].alive = False
assert valid_targets_for_face(game, 0, BULL2) == [1]
print('ROUND TABLE TESTS OK')
