"""The Soul Mixer's window (SE_SOUL_MIXER): the page's side of soul_mixer.py.

Tapping a Soul Mixer in the game (swf_soul_mixer.py) calls window.seOpenSoulMixer(); the window
(templates/js/soul_mixer_overlay.js) reads /soul-mixer/api/state and sends its actions to /soul-mixer/api/action:
choose (two units), clear, powerup, start, speed_up and collect. Starting, finishing early and collecting change the
village while the game is open: the window then offers to reload it (the village's revision changed too, so the
page also pauses the game and asks, as for the season pass).

Nothing here exists unless SE_SOUL_MIXER=on: install_soul_mixer() is only called then.
"""

from pathlib import Path

from flask import abort, g, jsonify, request, session, url_for

from auth import validate_csrf
from portal_i18n import translate as _
from soul_mixer import BUILDING, MixerError, SoulMixer, Tables

ASSETS = '/default01.static.socialpointgames.com/static/socialempires/'


def overlay_texts():
    return {
        'title': _('Misturador de almas'), 'close': _('Fechar'), 'loading': _('Carregando…'),
        'intro': _('Escolha duas unidades da sua vila. As almas delas se misturam e, depois de uma espera, '
                   'nasce uma unidade nova. As duas unidades escolhidas são consumidas.'),
        'pick_first': _('Escolha a primeira alma'), 'pick_second': _('Escolha a segunda alma'),
        'no_units': _('Você não tem unidades que possam ser misturadas nesta vila.'),
        'count': _('x{count}'), 'empty': _('Alma vazia'),
        'mystery': _('Unidade misteriosa'),
        'mystery_help': _('O que vai nascer é um segredo até a mistura terminar.'),
        'powerup': _('Melhorar ({cash} de dinheiro)'),
        'powerup_help': _('Cada melhoria sobe o resultado. Total a pagar ao começar: {cash} de dinheiro.'),
        'upgrades': _('Melhorias: {count}'),
        'start': _('Misturar'), 'change': _('Trocar almas'),
        'start_confirm': _('As duas unidades vão sair da sua vila para sempre. Misturar?'),
        'mixing': _('Misturando: {name}'), 'ready_in': _('Pronta em {time}'), 'ready': _('A unidade está pronta!'),
        'speed_up': _('Terminar agora ({cash} de dinheiro)'),
        'collect': _('Receber unidade'),
        'collected': _('{name} está nos seus presentes.'),
        'started': _('A mistura começou.'),
        'sped_up': _('A mistura terminou.'),
        'reload': _('Recarregar a vila'),
        'reload_help': _('Recarregue a vila para ver as mudanças.'),
        'help': _('Ajuda'), 'back': _('Voltar'), 'cash': _('Seu dinheiro: {cash}'),
        'days': _('{days} d'), 'hours': _('{hours} h'), 'minutes': _('{minutes} min'),
        'error': _('Não foi possível concluir. Tente novamente.'),
        'errors': {
            'no_mixer': _('Construa um Misturador de almas na sua vila (loja, Edifícios, Vários).'),
            'level': _('O Misturador de almas funciona a partir do nível {level}.'),
            'busy': _('Já há uma mistura em andamento.'),
            'not_owned': _('Essas unidades não estão na sua vila.'),
            'parents_gone': _('Uma das unidades escolhidas já não está na vila. Escolha de novo.'),
            'no_preview': _('Escolha duas almas primeiro.'),
            'cash': _('Dinheiro insuficiente.'),
            'no_more': _('Não há unidade mais forte para esta mistura.'),
            'limit': _('Você já tem o máximo dessa unidade.'),
            'no_mix': _('Não há nenhuma mistura em andamento.'),
            'ready': _('A unidade já está pronta.'),
            'not_ready': _('A unidade ainda não está pronta.'),
            'one_mixer': _('Você só pode ter um Misturador de almas por vila.'),
        },
    }


def install_soul_mixer(app, village_lock, village_session, save_village, items, unit_name, assets_dir):
    """`items`: {id: config item}; `unit_name(id)`: the unit's name in the player's language."""
    tables = Tables.load(items)
    thumbs = Path(assets_dir) / 'buildingthumbs'

    def current_player():
        account = g.get('account')
        if not account or account['status'] != 'approved' or not account['village_id']:
            return None
        if session.get('USERID') != account['village_id']:
            return None
        return account

    @app.context_processor
    def soul_mixer_context():
        if not current_player():
            return {}
        return {'soul_mixer_overlay': {
            'state': url_for('soul_mixer_api_state'), 'action': url_for('soul_mixer_api_action'),
            'play': url_for('play'), 'texts': overlay_texts(),
            'art': {'background': ASSETS + 'externalized/SoulMixer/SoulMixer-background.jpg',
                    'empty': ASSETS + 'externalized/SoulMixer/SoulMixer-no-soul-126x126.jpg',
                    'help': [ASSETS + f'externalized/popup_elements/popup_help_soul_mixer/{n}.png' for n in range(1, 5)]},
        }}

    def unit_view(unit):
        item = items.get(int(unit), {})
        name = item.get('img_name')
        return {'id': int(unit), 'name': unit_name(unit),
                'thumb': ASSETS + f'buildingthumbs/{name}.jpg' if name and (thumbs / f'{name}.jpg').is_file() else None}

    def view(mixer):
        town = mixer.town()
        out = {'has_mixer': town is not None, 'min_level': tables.min_level, 'cash': mixer.cash(),
               'level': mixer.level(town) if town else 0, 'eligible': [], 'preview': None, 'mix': None}
        if town is not None:
            counts = mixer.eligible(town)
            out['eligible'] = sorted(({**unit_view(unit), 'count': count, 'rank': tables.order[unit]}
                                      for unit, count in counts.items()), key=lambda row: (-row['rank'], row['id']))
        preview = mixer.preview()
        if preview:
            upgrades = int(preview.get('upgrades') or 0)
            # The result stays secret until the mix is over (the page shows a "?"; nothing to read in its code).
            out['preview'] = {'parents': [unit_view(parent) for parent in preview['parents']], 'upgrades': upgrades,
                              'next_price': tables.powerup_price(upgrades),
                              'total': tables.powerups_cost(upgrades)}
        mix = mixer.mix()
        if mix:
            ready = not mixer.remaining()
            out['mix'] = {'result': unit_view(mix['unit']) if ready else None,
                          'parents': [unit_view(p) for p in mix.get('parents', [])],
                          'remaining': mixer.remaining(), 'seconds': int(mix.get('seconds') or 0),
                          'speed_price': mixer.speed_up_price()}
        return out

    def open_mixer():
        userid = session['USERID']
        return userid, SoulMixer(village_session(userid), tables, items)

    @app.get('/soul-mixer/api/state', endpoint='soul_mixer_api_state')
    def soul_mixer_state():
        if not current_player():
            abort(403)
        with village_lock:
            _userid, mixer = open_mixer()
            return jsonify(view(mixer))

    @app.post('/soul-mixer/api/action', endpoint='soul_mixer_api_action')
    def soul_mixer_action():
        validate_csrf()
        if not current_player():
            abort(403)
        action = request.form.get('action', '')
        with village_lock:
            userid, mixer = open_mixer()
            before = mixer.changes()
            done = {}
            try:
                if action == 'choose':
                    mixer.choose(request.form.get('first'), request.form.get('second'))
                elif action == 'clear':
                    mixer.clear()
                elif action == 'powerup':
                    mixer.power_up()
                elif action == 'start':
                    mixer.start()
                elif action == 'speed_up':
                    done['paid'] = mixer.speed_up()
                elif action == 'collect':
                    done['unit'] = unit_view(mixer.collect())
                else:
                    abort(400)
            except MixerError as error:
                texts = overlay_texts()['errors']
                return jsonify({'error': texts.get(error.code, overlay_texts()['error']).format(**error.values),
                                'code': error.code, 'state': view(mixer)}), 409
            save_village(userid)
            if mixer.changes() != before:
                print(f' [soul mixer] {userid}: {action}')
            return jsonify({'state': view(mixer), 'changed': mixer.changes() != before, **done})

    app.extensions['soul_mixer'] = {'tables': tables, 'building': BUILDING}
