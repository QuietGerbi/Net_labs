"""Логика ведущего узла (MASTER): состояние игры, приём запросов, рассылка, анонсы."""
from __future__ import annotations

from typing import Dict, List, Optional

from . import codec, rules
from . import constants as C
from .messages import clip_error_text, envelope
from .model import Config, Endpoint, Player, World, validate_player_name
from .proto import snakes_pb2 as pb


class MasterMixin:
    # ------------------------------------------------------------ инициализация
    def _init_master_fields(self) -> None:
        self.next_tick = 0.0
        self.pending_dirs: Dict[int, int] = {}
        self.steer_seq: Dict[int, int] = {}
        self.status_seq: Dict[int, int] = {}
        self.last_announce = float("-inf")
        self.invite_server = False
        self.leave_stage: Optional[str] = None
        self.leave_seq: Optional[int] = None
        self.leave_deadline = 0.0

    def start_as_master(self, config: Config, invite_server: bool = False) -> None:
        """Создатель получает ID 1, роль MASTER и статус PLAYING."""
        from .session import Phase

        now = self.clock()
        world = World(self.game_name, config, state_order=0, next_player_id=2)
        world.players.append(Player(1, self.player_name, pb.MASTER, pb.PLAYING))
        snake = rules.find_spawn(world, self.rng)
        if snake is None:  # на пустом поле такого быть не может
            raise ValueError("Не удалось разместить змейку")
        snake.player_id = 1
        world.snakes.append(snake)
        rules.replenish_food(world, self.rng)
        self.world, self.config, self.my_id = world, config, 1
        self.is_master = True
        self.phase = Phase.ACTIVE
        self.invite_server = invite_server
        self.next_tick = now + config.state_delay_ms / 1000.0
        self.version += 1
        self._announce(now)

    # ------------------------------------------------------------------- цикл
    def _m_tick(self, now: float) -> None:
        from .session import Phase

        if self.phase == Phase.LEAVING:
            self.out.retransmit()
            if now >= self.leave_deadline:
                self.phase = Phase.CLOSED
                self.version += 1
            return

        w = self.world
        # Потеря связи с участником: удаляем его и его змейку.
        lost = [p for p in w.players
                if p.id != self.my_id and p.endpoint and self.out.silence(p.endpoint) > C.LINK_TIMEOUT]
        if lost:
            for p in lost:
                self._drop_player(p)
            self._commit()

        if now >= self.next_tick:
            delay = w.config.state_delay_ms / 1000.0
            self.next_tick += delay
            if self.next_tick <= now:
                self.next_tick = now + delay
            self._m_step()

        for p in w.players:
            if p.id != self.my_id and p.endpoint and self.out.idle(p.endpoint) >= C.PING_INTERVAL:
                ping = envelope(self.game_name, self.my_id, p.id)
                ping.ping.SetInParent()
                self.out.send(p.endpoint, ping, key="ping")

        self._announce(now)
        self.out.retransmit()

    def _m_step(self) -> None:
        dirs = dict(self.pending_dirs)
        self.pending_dirs.clear()
        rules.step(self.world, dirs)
        self._commit()

    # --------------------------------------------------- публикация состояния
    def _commit(self, notify_master: bool = False) -> None:
        """Любое изменение состояния: пополнить еду, увеличить state_order, разослать всем.

        notify_master=True — новый MASTER после failover сначала уведомляет всех
        через NodeRoleChange(sender_role=MASTER), затем рассылает State.
        """
        w = self.world
        rules.replenish_food(w, self.rng)
        if w.state_order >= C.INT32_MAX:
            from .messages import ProtocolError
            raise ProtocolError("Исчерпан диапазон state_order")
        w.state_order += 1
        self._ensure_deputy()
        if notify_master:
            for p in w.players:
                if p.id != self.my_id and p.endpoint:
                    m = envelope(self.game_name, self.my_id, p.id)
                    m.node_role_change.sender_role = pb.MASTER
                    m.node_role_change.state_order = w.state_order
                    self.out.send(p.endpoint, m)
        self._broadcast_state()
        self.version += 1

    def _ensure_deputy(self) -> None:
        """Если участников >= 2, должен быть ровно один DEPUTY (любой NORMAL, включая наблюдателей)."""
        w = self.world
        if len(w.players) < 2 or w.deputy() is not None:
            return
        for p in w.players:
            if p.role == pb.NORMAL and p.endpoint:
                p.role = pb.DEPUTY
                m = envelope(self.game_name, self.my_id, p.id)
                m.node_role_change.receiver_role = pb.DEPUTY
                m.node_role_change.state_order = w.state_order
                self.out.send(p.endpoint, m)
                return

    def _broadcast_state(self, only: Optional[Player] = None) -> None:
        w = self.world
        state = codec.world_to_state(w, sender_id=self.my_id)
        for p in w.players:
            if p.id == self.my_id or not p.endpoint or (only is not None and p is not only):
                continue
            m = envelope(self.game_name, self.my_id, p.id)
            m.state.state.CopyFrom(state)
            self.out.send(p.endpoint, m, key="state")

    def _drop_player(self, p: Player) -> None:
        w = self.world
        w.players = [x for x in w.players if x.id != p.id]
        w.snakes = [s for s in w.snakes if s.player_id != p.id]
        self.pending_dirs.pop(p.id, None)
        if p.endpoint:
            self.out.drop_endpoint(p.endpoint)

    # ----------------------------------------------------------------- анонсы
    def _can_join(self) -> bool:
        w = self.world
        return (len(w.players) < C.MAX_PLAYERS and w.next_player_id < C.INT32_MAX
                and rules.find_spawn(w, self.rng) is not None)

    def _announcement_message(self) -> "pb.GameMessage":
        w = self.world
        m = envelope(None)
        g = m.announcement.games.add()
        g.players.CopyFrom(codec.players_to_proto(w, sender_id=self.my_id))
        g.config.CopyFrom(w.config.to_proto())
        g.can_join = self._can_join()
        g.game_name = self.game_name
        m.msg_seq = self.out.next_seq()
        return m

    def _announce(self, now: float) -> None:
        if now - self.last_announce < C.ANNOUNCE_INTERVAL:
            return
        self.last_announce = now
        from .messages import serialize_checked

        data = serialize_checked(self._announcement_message())
        self.sock.send_multicast(data, self.ctx.interfaces())
        server = self.ctx.server_ep()
        if self.invite_server and server is not None:
            self.sock.sendto(data, server)

    def _on_discover(self, ep: Endpoint) -> None:
        if not self.is_master or self.world is None:
            return
        from .messages import serialize_checked

        self.sock.sendto(serialize_checked(self._announcement_message()), ep)

    def _on_announcement(self, msg, ep: Endpoint, now: float) -> None:
        self._c_on_announcement(msg, ep, now)

    # ------------------------------------------------- приём сообщений (MASTER)
    def _ack_sender_ok(self, msg, ep: Endpoint) -> bool:
        if not self.is_master:
            return self._c_ack_sender_ok(msg, ep)
        p = self.world.player_at(ep)
        return not (p and msg.HasField("sender_id") and msg.sender_id != p.id)

    def _is_known_neighbor(self, ep: Endpoint) -> bool:
        if self.is_master:
            return self.world.player_at(ep) is not None
        return ep == self.master_ep

    def _master_receive(self, msg, ep: Endpoint, t: str, now: float) -> None:
        seq = msg.msg_seq
        verdict, cached = self.dedup.check(ep, seq)
        known = self.world.player_at(ep)
        if verdict == "dup":  # повтор получает прежний ответ, операция не выполняется заново
            if known:
                self.out.touch(ep)
            for data in cached:
                self.out.emit_raw(ep, data)
            return
        if verdict == "old":
            return
        if t == "join":
            if not self.dedup.can_admit(ep):
                return  # бюджет кеша исчерпан: новых endpoint не допускаем
            responses = self._m_join(msg, ep, now, known)
        else:
            if known is None or not self._ids_ok(msg, known):
                return
            self.out.touch(ep)
            handler = {
                "ping": self._m_ping,
                "steer": self._m_steer,
                "player_status_change": self._m_status_change,
                "leave": self._m_leave,
            }.get(t)
            if handler is None:
                return  # State/NodeRoleChange/Error от участников MASTER не принимает
            responses = handler(msg, ep, known, now)
        if responses is not None:  # только корректные сообщения продвигают окно
            self.dedup.record(ep, seq, responses)

    def _ids_ok(self, msg, player: Player) -> bool:
        if not msg.HasField("sender_id") or msg.sender_id != player.id:
            return False
        return not (msg.HasField("receiver_id") and msg.receiver_id != self.my_id)

    def _reply_error(self, ep: Endpoint, req, text: str, receiver_id: Optional[int] = None) -> bytes:
        m = envelope(self.game_name, self.my_id, receiver_id)
        m.error.error_message = clip_error_text(text)
        m.error.request_seq = req.msg_seq
        self.out.send(ep, m)  # собственный msg_seq, подтверждается ACK
        return m.SerializeToString()

    # --- обработчики ---
    def _m_ping(self, msg, ep, player, now) -> List[bytes]:
        return [self._reply_ack(ep, msg)]

    def _m_join(self, msg, ep: Endpoint, now: float, existing: Optional[Player]) -> Optional[List[bytes]]:
        w = self.world
        if existing is not None:  # тот же endpoint: возвращаем имеющийся ID, змейку не создаём
            return [self._reply_ack(ep, msg, receiver_id=existing.id)]
        j = msg.join
        if j.game_name != self.game_name:
            return None
        try:
            validate_player_name(j.player_name)
        except ValueError:
            return [self._reply_error(ep, msg, "Недопустимое имя игрока")]
        status = j.requested_status
        if status not in (pb.PLAYING, pb.VIEWING):
            return [self._reply_error(ep, msg, "Недопустимый статус")]
        if len(w.players) >= C.MAX_PLAYERS:
            return [self._reply_error(ep, msg, "Игра заполнена: нет мест для участников")]
        if w.next_player_id >= C.INT32_MAX:
            return [self._reply_error(ep, msg, "Исчерпан диапазон идентификаторов игроков")]
        snake = None
        if status == pb.PLAYING:
            snake = rules.find_spawn(w, self.rng)
            if snake is None:
                return [self._reply_error(ep, msg, "Нет места для новой змейки")]
        pid = w.next_player_id
        w.next_player_id += 1
        player = Player(pid, j.player_name, pb.NORMAL, status, 0, j.player_type, ep[0], ep[1])
        w.players.append(player)
        if snake is not None:
            snake.player_id = pid
            w.snakes.append(snake)
        self.out.link(ep).last_recv = now
        ack = self._reply_ack(ep, msg, receiver_id=pid)  # сначала ACK с выданным ID, затем State
        self._commit()
        return [ack]

    def _m_steer(self, msg, ep, player: Player, now) -> List[bytes]:
        ack = self._reply_ack(ep, msg)
        if msg.msg_seq > self.steer_seq.get(player.id, -1):  # запоздавшая команда не отменяет новую
            self.steer_seq[player.id] = msg.msg_seq
            snake = self.world.snake_of(player.id)
            d = msg.steer.direction
            c = self.world.config
            if player.status == pb.PLAYING and snake and not rules.is_reverse(snake, d, c.width, c.height):
                self.pending_dirs[player.id] = d
        return [ack]

    def _m_status_change(self, msg, ep, player: Player, now) -> List[bytes]:
        w = self.world
        if msg.msg_seq <= self.status_seq.get(player.id, -1):
            return [self._reply_ack(ep, msg)]  # устаревший запрос: подтверждаем без применения
        self.status_seq[player.id] = msg.msg_seq
        target = msg.player_status_change.status
        if target == player.status:  # текущий статус: ACK и актуальный State без нового state_order
            ack = self._reply_ack(ep, msg)
            self._broadcast_state(only=player)
            return [ack]
        if target == pb.VIEWING:
            w.snakes = [s for s in w.snakes if s.player_id != player.id]
            player.status = pb.VIEWING
            self.pending_dirs.pop(player.id, None)
            ack = self._reply_ack(ep, msg)
            self._commit()
            return [ack]
        snake = rules.find_spawn(w, self.rng)
        if snake is None:
            return [self._reply_error(ep, msg, "Нет места для новой змейки", player.id)]
        snake.player_id = player.id
        w.snakes.append(snake)
        player.status = pb.PLAYING
        ack = self._reply_ack(ep, msg)
        self._commit()
        return [ack]

    def _m_leave(self, msg, ep, player: Player, now) -> List[bytes]:
        ack = self._reply_ack(ep, msg)
        self._drop_player(player)
        self._commit()
        return [ack]

    # ------------------------------------------------ действия самого MASTER
    def _m_local_steer(self, direction: int) -> None:
        snake = self.world.snake_of(self.my_id)
        c = self.world.config
        if snake and not rules.is_reverse(snake, direction, c.width, c.height):
            self.pending_dirs[self.my_id] = direction

    def _m_local_status(self, playing: bool) -> None:
        w = self.world
        me = w.player(self.my_id)
        if playing and me.status == pb.VIEWING:
            snake = rules.find_spawn(w, self.rng)
            if snake is None:
                self.notice("Нет места для новой змейки")
                return
            snake.player_id = me.id
            w.snakes.append(snake)
            me.status = pb.PLAYING
            self._commit()
        elif not playing and me.status == pb.PLAYING:
            w.snakes = [s for s in w.snakes if s.player_id != me.id]
            me.status = pb.VIEWING
            self.pending_dirs.pop(me.id, None)
            self._commit()

    # --------------------------------------------- выход ведущего узла из игры
    def _m_begin_leave(self, now: float) -> None:
        """State -> DEPUTY (ждём ACK), затем NodeRoleChange(NORMAL->MASTER) (ждём ACK)."""
        from .session import Phase

        w = self.world
        dep = w.deputy()
        if dep is None or dep.endpoint is None or len(w.players) < 2:
            self.phase = Phase.CLOSED  # некому передавать (или игра закончена)
            self.version += 1
            return
        for p in w.players:  # прочие повторы больше не нужны
            if p.id not in (self.my_id, dep.id) and p.endpoint:
                self.out.drop_endpoint(p.endpoint)
        self.phase = Phase.LEAVING
        self.leave_deadline = now + C.LEAVE_TIMEOUT
        self.leave_stage = "state"
        m = envelope(self.game_name, self.my_id, dep.id)
        m.state.state.CopyFrom(codec.world_to_state(w, sender_id=self.my_id))
        self.leave_seq = self.out.send(dep.endpoint, m, key="state")
        self.version += 1

    def _on_leave_ack(self, now: float) -> None:
        from .session import Phase

        if self.is_master and self.leave_stage == "state":
            w = self.world
            dep = w.deputy()
            m = envelope(self.game_name, self.my_id, dep.id)
            m.node_role_change.sender_role = pb.NORMAL
            m.node_role_change.receiver_role = pb.MASTER
            m.node_role_change.state_order = w.state_order + 1  # следующее состояние нового MASTER
            self.leave_stage = "role"
            self.leave_seq = self.out.send(dep.endpoint, m)
            return
        self.phase = Phase.CLOSED
        self.version += 1
