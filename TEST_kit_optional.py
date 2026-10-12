"""v0.7.8 回歸測試：基特能力可任意使用/逐次跳過/一鍵全部跳過。"""
from pathlib import Path
import ast
import asyncio
import random
from data import GATLING, BEER, BULL1
from game_engine import Game, add_human, setup_game, _build_resolution_queue, pop_next_action, finish_pending_action


def make_game():
    g = Game(chat_id=878, host_id=1)
    for i in range(4):
        add_human(g, i+1, f'玩家{i+1}')
    setup_game(g, random.Random(8))
    g.current_idx = 0
    g.players[0].character_key = 'kit_carlson'
    g.players[0].arrows = 1
    g.players[1].arrows = 2
    g.arrows_pool = 6
    g.phase = 'resolving'
    g.dice = [GATLING,GATLING,GATLING,BEER,BULL1]
    _build_resolution_queue(g, False)
    return g


class FakeQuery:
    def __init__(self): self.answers=[]
    async def answer(self, text=None, show_alert=False): self.answers.append((text,show_alert))


def extract_real_kit_callback():
    source = Path(__file__).with_name('bot.py').read_text('utf-8')
    tree = ast.parse(source)
    func=next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name=='callback_impl')
    branch=next(n for n in func.body if isinstance(n,ast.If) and isinstance(n.test,ast.Call) and
                isinstance(n.test.func,ast.Attribute) and n.test.func.attr=='startswith' and
                ast.unparse(n.test.args[0])=="'kit:'")
    # Compile the exact same production branch with miniature input bindings.
    wrapper = ast.AsyncFunctionDef(name='handle_kit',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=x) for x in ['q','game','data','context']],kwonlyargs=[],kw_defaults=[],defaults=[]),
                                   body=branch.body, decorator_list=[],returns=None, type_comment=None)
    module=ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[]))
    ns={'finish_pending_action':finish_pending_action}
    updates=[]
    async def resume(context,game): updates.append((game.pending_action,len(game.pending_actions)))
    ns['process_until_input']=resume
    exec(compile(module, 'bot.py:kit_callback', 'exec'),ns)
    return ns['handle_kit'],updates


async def tests():
    source=Path(__file__).with_name('bot.py').read_text('utf8')
    assert 'callback_data="kit:skip"' in source
    assert 'callback_data="kit:done"' in source
    handle,updates=extract_real_kit_callback()
    for choice in ('kit:skip','kit:done','kit:1'):
        game=make_game()
        while (action:=pop_next_action(game)) and action['type']!='kit_discard':
            finish_pending_action(game)
        assert game.pending_action and game.pending_action['type']=='kit_discard'
        old_arrows=[p.arrows for p in game.players]
        old_pool=game.arrows_pool
        q=FakeQuery()
        await handle(q,game,choice,None)
        assert len(q.answers)==1 and game.pending_action is None
        assert len(updates)>0
        if choice=='kit:skip':
            assert [p.arrows for p in game.players]==old_arrows
            assert game.arrows_pool==old_pool
            assert sum(a['type']=='kit_discard' for a in game.pending_actions)==2
        elif choice=='kit:done':
            assert [p.arrows for p in game.players]==old_arrows
            assert game.arrows_pool==old_pool
            assert sum(a['type']=='kit_discard' for a in game.pending_actions)==0
            assert any(a['type']=='end_turn' for a in game.pending_actions)
        else:
            assert game.players[1].arrows==old_arrows[1]-1 and game.arrows_pool==old_pool+1
            assert sum(a['type']=='kit_discard' for a in game.pending_actions)==2
    # 用了一次再按「完成」：前次已移的箭保留，後續不再強制移除。
    game=make_game()
    while (a:=pop_next_action(game)) and a['type']!='kit_discard': finish_pending_action(game)
    await handle(FakeQuery(),game,'kit:1',None)
    pop_next_action(game)
    assert game.pending_action['type']=='kit_discard'
    await handle(FakeQuery(),game,'kit:done',None)
    assert game.players[1].arrows==1 and game.arrows_pool==7
    assert all(a['type']!='kit_discard' for a in game.pending_actions)
    print('PASS: 逐次跳過 / 一鍵全部跳過 / 手動移箭 / 先移再結束 / 既有結算保留')

if __name__=='__main__': asyncio.run(tests())
