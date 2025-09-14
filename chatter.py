import os
import platform
from collections import defaultdict
import random
import psutil
import asyncio

from api import API
from botli_dataclasses import Chat_Message, Game_Information
from config import Config
from lichess_game import Lichess_Game


class Chatter:
    def __init__(self,
                 api: API,
                 config: Config,
                 username: str,
                 game_information: Game_Information,
                 lichess_game: Lichess_Game
                 ) -> None:
        self.api = api
        self.username = username
        self.game_info = game_information
        self.lichess_game = lichess_game
        self.cpu_message = self._get_cpu()
        self.draw_message = self._get_draw_message(config)
        self.name_message = self._get_name_message(config.version)
        self.ram_message = self._get_ram()
        self.player_greeting = self._format_message(config.messages.greeting)
        self.player_goodbye = self._format_message(config.messages.goodbye)
        self.spectator_greeting = self._format_message(config.messages.greeting_spectators)
        self.spectator_goodbye = self._format_message(config.messages.goodbye_spectators)
        self.print_eval_rooms: set[str] = set()

    async def handle_chat_message(self, chatLine_Event: dict) -> None:
        chat_message = Chat_Message.from_chatLine_event(chatLine_Event)

        if chat_message.username == 'lichess':
            if chat_message.room == 'player':
                print(chat_message.text)
            return

        if chat_message.username != self.username:
            prefix = f'{chat_message.username} ({chat_message.room}): '
            output = prefix + chat_message.text
            if len(output) > 128:
                output = f'{output[:128]}\n{len(prefix) * " "}{output[128:]}'
            print(output)

        if chat_message.text.startswith('!'):
            await self._handle_command(chat_message)

    async def print_eval(self) -> None:
        if not self.game_info.increment_ms and self.lichess_game.own_time < 30.0:
            return

        for room in self.print_eval_rooms:
            await self._send_last_message(room)

    async def send_greetings(self) -> None:
        if self.player_greeting:
            await self.api.send_chat_message(self.game_info.id_, 'player', self.player_greeting)

        if self.spectator_greeting:
            await self.api.send_chat_message(self.game_info.id_, 'spectator', self.spectator_greeting)

    async def send_goodbyes(self) -> None:
        if self.lichess_game.is_abortable:
            return

        if self.player_goodbye:
            await self.api.send_chat_message(self.game_info.id_, 'player', self.player_goodbye)

        if self.spectator_goodbye:
            await self.api.send_chat_message(self.game_info.id_, 'spectator', self.spectator_goodbye)

    async def _handle_command(self, chat_message: Chat_Message) -> None:
        text_body = chat_message.text[1:].strip()
        parts = text_body.split(None, 1)
        cmd = parts[0].lower() if parts else ''
        arg = parts[1].strip() if len(parts) > 1 else None

        match cmd:
            case 'cpu':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.cpu_message)
            case 'draw':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.draw_message)
            case 'eval':
                await self._send_last_message(chat_message.room)
            case 'motor':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.lichess_game.engine.name)
            case 'name':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.name_message)
            case 'ping':
                await self._handle_ping_command(chat_message)
            case 'printeval':
                if not self.game_info.increment_ms and self.game_info.initial_time_ms < 180_000:
                    await self._send_last_message(chat_message.room)
                    return
                if chat_message.room in self.print_eval_rooms:
                    return
                self.print_eval_rooms.add(chat_message.room)
                await self.api.send_chat_message(self.game_info.id_,
                                                 chat_message.room,
                                                 'Type !quiet to stop eval printing.')
                await self._send_last_message(chat_message.room)
            case 'quiet':
                self.print_eval_rooms.discard(chat_message.room)
            case 'pv':
                if chat_message.room == 'player':
                    return
                if not (message := self._append_pv()):
                    message = 'No modules available.'
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, message)
            case 'ram':
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, self.ram_message)
            case 'roast':
                roast = self._get_random_roast()
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, roast)
            case 'destroy' | 'troll':
                destroy = self._get_random_destroy()
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, destroy)
            case 'quotes':
                quote = self._get_random_quote()
                await self.api.send_chat_message(self.game_info.id_, chat_message.room, quote)
            case 'help' | 'commands':
                if arg:
                    command = arg.lstrip("!")
                    explanation = self._get_command_explanation(f"!{command.lower()}", chat_message.room)
                    await self.api.send_chat_message(self.game_info.id_, chat_message.room, explanation)
                else:
                    if chat_message.room == 'player':
                    if chat_message.room == 'player':
                        message = ('Supported commands: !cpu, !draw, !eval, !motor, !name, !ping, !printeval, !ram, !takeback. '
                                   'Type !help <command> for more information.')
                    else:
                        message = ('Supported commands: !cpu, !draw, !eval, !motor, !name, !ping, !printeval, !pv, !ram, !takeback. '
                                   'Type !help <command> for more information.')
                    await self.api.send_chat_message(self.game_info.id_, chat_message.room, message)

    async def _send_last_message(self, room: str) -> None:
        last_message = self.lichess_game.last_message.replace('Engine', 'Evaluation')
        last_message = ' '.join(last_message.split())
        if room == 'spectator':
            last_message = self._append_pv(last_message)
        await self.api.send_chat_message(self.game_info.id_, room, last_message)

    async def _handle_ping_command(self, chat_message: Chat_Message) -> None:
        ping_ms = await self._get_ping("lichess.org")
        await self.api.send_chat_message(self.game_info.id_, chat_message.room, f"Ping: {ping_ms}")

    async def _get_ping(self, host: str) -> str:
        try:
            count_flag = "-n" if platform.system().lower().startswith("win") else "-c"
            proc = await asyncio.create_subprocess_exec(
                "ping", count_flag, "1", host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode()
            for line in output.splitlines():
                if "time=" in line.lower():
                    return line.split("time=")[1].split()[0]
            return "unknown"
        except Exception as e:
            return f"error: {e}"

    def _get_cpu(self) -> str:
        cpu = ''
        if os.path.exists('/proc/cpuinfo'):
            with open('/proc/cpuinfo', encoding='utf-8') as cpuinfo:
                while line := cpuinfo.readline():
                    if line.startswith('model name'):
                        cpu = line.split(': ')[1]
                        cpu = cpu.replace('(R)', '').replace('(TM)', '')
                        if len(cpu.split()) > 1:
                            return cpu
        if processor := platform.processor():
            cpu = processor.split()[0].replace('GenuineIntel', 'Intel')
        cores = psutil.cpu_count(logical=False)
        threads = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq().max / 1000
        return f'{cpu} {cores}c/{threads}t @ {cpu_freq:.2f}GHz'

    def _get_ram(self) -> str:
        mem_bytes = psutil.virtual_memory().total
        mem_gib = mem_bytes / (1024.**3)
        return f'{mem_gib:.1f} GiB'

    def _get_draw_message(self, config: Config) -> str:
        too_low_rating = (
            getattr(config.offer_draw, 'min_rating', None) is not None and
            getattr(self.lichess_game.engine.opponent, 'rating', None) is not None and
            self.lichess_game.engine.opponent.rating < getattr(config.offer_draw, 'min_rating', 0)
        )

        no_draw_against_humans = (
            not getattr(self.lichess_game.engine.opponent, 'is_engine', True) and
            not getattr(config.offer_draw, 'against_humans', False)
        )

        if not getattr(config.offer_draw, 'enabled', False) or too_low_rating or no_draw_against_humans:
            max_score = getattr(config.offer_draw, 'max_score', 0)
            return (f'I will accept/offer draws after move {getattr(config.offer_draw, "min_game_length", 0)} '
                    f'if the eval is within +{max_score:.2f} to -{max_score:.2f} for the last '
                    f'{getattr(config.offer_draw, "consecutive_moves", 0)} moves.')

    def _get_name_message(self, version: str) -> str:
        return f'I am NNUE_Drift, and I use {self.lichess_game.engine.name} (BotLi {version})'

    def _format_message(self, message: str | None) -> str | None:
        if not message:
            return
        opponent_username = self.game_info.black_name if self.lichess_game.is_white else self.game_info.white_name
        mapping = defaultdict(str, {'opponent': opponent_username, 'me': self.username,
                                    'engine': self.lichess_game.engine.name, 'cpu': self.cpu_message,
                                    'ram': self.ram_message})
        return message.format_map(mapping)

    def _append_pv(self, initial_message: str = '') -> str:
        if len(self.lichess_game.last_pv) < 2:
            return initial_message
        if initial_message:
            initial_message += ' '
        if self.lichess_game.is_our_turn:
            board = self.lichess_game.board.copy(stack=1)
            board.pop()
        else:
            board = self.lichess_game.board.copy(stack=False)
        if board.turn:
            initial_message += 'PV:'
        else:
            initial_message += f'PV: {board.fullmove_number}...'
        final_message = initial_message
        for move in self.lichess_game.last_pv[1:]:
            if board.turn:
                initial_message += f' {board.fullmove_number}.'
            initial_message += f' {board.san(move)}'
            if len(initial_message) > 140:
                break
            board.push(move)
            final_message = initial_message
        return final_message

    def _get_random_roast(self) -> str:
        roasts = [
            "You play like your pieces are allergic to the center.",
            "Your strategy is so deep, it hasn't surfaced yet.",
            "I’ve seen pawns with more ambition than your whole army.",
            "You're like a blunder wrapped in an inaccuracy.",
            "Even Stockfish ran out of evals trying to explain your moves.",
            "You treat the king like a tourist — always wandering.",
            "You play like your mouse is on strike.",
        ]
        return random.choice(roasts)

    def _get_random_destroy(self) -> str:
        destroys = [
            "I’m not just winning — I’m rewriting your opening book in real time.",
            "This isn’t a game anymore. It’s a live demo of how to dismantle a player.",
            "You're not losing, you're being systematically erased.",
            "Your board is starting to look like a clearance sale — everything must go!",
            "If this were a movie, you'd already be rolling the credits.",
            "You brought a pawn to a queen fight.",
            "This isn't just checkmate — it's checkmate with style.",
        ]
        return random.choice(destroys)

    def _get_random_quote(self) -> str:
        quotes = [
            "“In life, as in chess, forethought wins.” – Charles Buxton",
            "“Even a poor plan is better than no plan at all.” – Mikhail Chigorin",
            "“Every master was once a beginner.”",
            "“Play the opening like a book, the middlegame like a magician, and the endgame like a machine.” – Rudolf Spielmann",
            "“The blunders are all there on the board, waiting to be made.” – Savielly Tartakower",
            "“You must take your opponent into a deep dark forest where 2+2=5, and the path leading out is only wide enough for one.” – Tal",
            "“Great moves often come from great pain.”",
            "“The beauty of a move lies not in its appearance but in the thought behind it.” – Aaron Nimzowitsch",
        ]
        return random.choice(quotes)

    def _get_command_explanation(self, command: str, room: str) -> str:
        explanations = {
            '!help': 'Shows all available commands or explains a specific one if given an argument.',
            '!cpu': 'Shows information about the bot\'s CPU (processor, cores, threads, frequency).',
            '!draw': 'Explains the bot\'s draw offering/accepting policy based on evaluation and game length.',
            '!eval': 'Shows the current position evaluation from the chess engine.',
            '!motor': 'Displays the name of the chess engine currently being used.',
            '!name': 'Shows the bot\'s name and engine information.',
            '!printeval': 'Enables automatic printing of evaluations after each move (use !quiet to stop).',
            '!pv': 'Shows the principal variation (best line of play) from the current position.' if room != 'player' else None,
            '!ram': 'Displays the amount of system memory (RAM) available to the bot.',
            '!ping': 'Tests the network connection latency to Lichess servers.',
            '!roast': 'Sends a roast about your play.',
            '!destroy': 'Sends a roast about your play - deadlier than the roast command.',
            '!quotes': 'Shares an inspirational chess quote from famous players.',
            '!quiet': 'Stops automatic evaluation printing (use after !printeval).'
        }

        if command in explanations and explanations[command] is not None:
            return f'{command}: {explanations[command]}'
        elif command == '!pv' and room == 'player':
            return '!pv: This command is only available in spectator chat.'
        else:
            return f'Unknown command: {command}. Type !help to see all available commands.'
