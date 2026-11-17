"""Логика клиента (NORMAL/DEPUTY): подключение, приём состояния, failover."""
from __future__ import annotations

from typing import List, Optional

from . import codec
from . import constants as C
from .messages import envelope, make_discover
from .model import Config, Endpoint, World
from .proto import snakes_pb2 as pb


class ClientMixin:
    def _init_client_fields(self) -> None:
        self.master_ep: Optional[Endpoint] = None
        self.master_id: Optional[int] = None
        self.join_seq: Optional[int] = None
        self.join_status = pb.PLAYING
        self.join_started = 0.0
        self.join_acked = False
        self.buffered = None            # (State, receiver_id) с наибольшим state_order до активации
        self.last_cfg_discover = float("-inf")
        self.alt_deadline: Optional[float] = None
        self.failover_done = False      # уже переключались на DEPUTY и ждём его State
        self.status_pending = False     # запрос смены статуса отправлен, ждём State

    # ----------------------------------------------------------- подключение
    def start_as_client(self, ep: Endpoint, status: int, config: Optional[Config]) -> None:
        self.master_ep = ep
        self.config = config
        self.join_status = status
        self._send_join()
        self.version += 1

    def _send_join(self) -> None:
        now = self.clock()
        m = envelope(self.game_name)
        j = m.join
        j.player_type = pb.HUMAN
        j.player_name = self.player_name
        j.game_name = self.game_name
        j.requested_status = self.join_status
        self.join_seq = self.out.send(self.master_ep, m)  # повторы Join каждые 100 мс
        self.join_started = now
        self.join_acked = False
        self.alt_deadline = None
        self.out.link(self.master_ep).last_recv = now

    def _c_on_announcement(self, msg, ep: Endpoint, now: float) -> None:
        """Конфиг принимается из Announcement выбранного endpoint с выбранным game_name."""
        from .session import Phase

        if self.is_master or self.phase != Phase.CONNECTING or ep != self.master_ep:
            return
        if self.config is not None:
            return
        for g in msg.announcement.games:
            if g.game_name == self.game_name:
                try:
                    self.config = Config.from_proto(g.config)
                except ValueError:
                    return
                self.out.touch(ep)
                self._try_activate()
                return

    def _try_activate(self) -> None:
        from .session import Phase

        if self.phase != Phase.CONNECTING or not self.join_acked or self.config is None:
            return
        if self.buffered is None:
            return
        state, receiver_id = self.buffered
        if receiver_id is not None and receiver_id != self.my_id:
            self.buffered = None  # State адресован не нам
            return
        try:
            world = codec.world_from_proto(state, self.config, self.game_name, self.master_ep)
        except ValueError:
            self.buffered = None
            return
        if world.player(self.my_id) is None:
            self.buffered = None
            return
        self.buffered = None
        self.phase = Phase.ACTIVE
        self._apply_world(world)

    def _apply_world(self, world: World) -> None:
        self.world = world
        master = world.master()
        if master is not None:
            self.master_id = master.id
        self.status_pending = False
        self.failover_done = False
        self.version += 1

    # --------------------------------------------------------------- цикл
    def _c_tick(self, now: float) -> None:
        from .session import Phase

        if self.phase == Phase.LEAVING:
            self.out.retransmit()
            if now >= self.leave_deadline:
                self.phase = Phase.CLOSED
                self.version += 1
            return
        if self.phase == Phase.CONNECTING:
            self._c_tick_connecting(now)
        elif self.out.silence(self.master_ep) > C.LINK_TIMEOUT:
            self._c_master_lost(now)
        if self.phase == Phase.CLOSED or self.is_master:
            return
        if self.my_id is not None and self.out.idle(self.master_ep) >= C.PING_INTERVAL:
            ping = envelope(self.game_name, self.my_id, self.master_id)
            ping.ping.SetInParent()
            self.out.send(self.master_ep, ping, key="ping")
        self.out.retransmit()

    def _c_tick_connecting(self, now: float) -> None:
        if self.join_acked and self.config is None and now - self.last_cfg_discover >= C.CONFIG_DISCOVER_INTERVAL:
            self.last_cfg_discover = now
            self.out.emit_raw(self.master_ep, self._discover_bytes())
        ready = self.join_acked and self.config is not None
        if not ready and now - self.join_started > C.JOIN_TIMEOUT:
            self.fail("Не удалось подключиться: нет ответа за 5 секунд")
            return
        if not self.join_acked:
            # MASTER молчит: ищем новый анонс с тем же game_name (возможно, прошёл failover).
            if self.out.silence(self.master_ep) > C.LINK_TIMEOUT:
                if self.alt_deadline is None:
                    self.alt_deadline = now + C.REJOIN_SEARCH_TIMEOUT
                alt = self.ctx.find_alternative(self.game_name, self.master_ep)
                if alt is not None:
                    self.out.drop_endpoint(self.master_ep)
                    self.master_ep = alt  # смена endpoint начинает новую попытку подключения
                    self._send_join()
                    return
                if now > self.alt_deadline:
                    self.fail("Игра недоступна: MASTER не отвечает, нового анонса нет")
        elif self.out.silence(self.master_ep) > C.LINK_TIMEOUT:
            self.fail("MASTER перестал отвечать при подключении")

    def _discover_bytes(self) -> bytes:
        m = make_discover()
        m.msg_seq = self.out.next_seq()
        return m.SerializeToString()

    # ---------------------------------------------------------- команды UI
    def _c_steer(self, direction: int) -> None:
        me = self.my_player()
        snake = self.world.snake_of(self.my_id) if self.world else None
        if me is None or me.status != pb.PLAYING or snake is None:
            return
        from .rules import is_reverse

        c = self.world.config
        if is_reverse(snake, direction, c.width, c.height):
            return
        m = envelope(self.game_name, self.my_id, self.master_id)
        m.steer.direction = direction
        self.out.send(self.master_ep, m, key="steer")

    def _c_request_status(self, playing: bool) -> None:
        me = self.my_player()
        if me is None:
            return
        want = pb.PLAYING if playing else pb.VIEWING
        m = envelope(self.game_name, self.my_id, self.master_id)
        m.player_status_change.status = want
        self.out.send(self.master_ep, m)  # управляющая операция: не вытесняется
        self.status_pending = True
        self.version += 1

    def _c_begin_leave(self, now: float) -> None:
        from .session import Phase

        if self.phase == Phase.CONNECTING and not self.join_acked:
            self.phase = Phase.CLOSED
            self.version += 1
            return
        m = envelope(self.game_name, self.my_id, self.master_id)
        m.leave.SetInParent()
        self.leave_seq = self.out.send(self.master_ep, m)
        self.phase = Phase.LEAVING
        self.leave_deadline = now + C.LEAVE_TIMEOUT
        self.version += 1

    # ------------------------------------------------------- приём (клиент)
    def _c_ack_sender_ok(self, msg, ep: Endpoint) -> bool:
        if ep != self.master_ep:
            return False
        if self.master_id is not None and msg.HasField("sender_id") and msg.sender_id != self.master_id:
            return False
        return True

    def _c_after_ack(self, pending, ack, now: float) -> None:
        from .session import Phase

        if (self.phase == Phase.CONNECTING and pending.msg.msg_seq == self.join_seq
                and pending.msg.WhichOneof("Type") == "join" and not self.join_acked):
            if not ack.HasField("receiver_id") or ack.receiver_id <= 0:
                self.fail("Некорректный ACK на Join (нет выданного ID)")
                return
            self.my_id = ack.receiver_id
            if ack.HasField("sender_id"):
                self.master_id = ack.sender_id
            self.join_acked = True
            self.out.link(self.master_ep).last_recv = now
            self._try_activate()

    def _deputy_endpoint(self) -> Optional[Endpoint]:
        if self.world is None:
            return None
        dep = self.world.deputy()
        return dep.endpoint if dep and dep.id != self.my_id else None

    def _client_receive(self, msg, ep: Endpoint, t: str, now: float) -> None:
        seq = msg.msg_seq
        rc = msg.node_role_change if t == "node_role_change" else None
        deputy_notice = (rc is not None and rc.HasField("sender_role") and rc.sender_role == pb.MASTER
                         and ep != self.master_ep and ep == self._deputy_endpoint())
        if ep != self.master_ep and not deputy_notice:
            return
        if self.my_id is not None and msg.HasField("receiver_id") and msg.receiver_id != self.my_id:
            return
        expected = self.master_id
        if ep != self.master_ep:
            expected = self.world.player_at(ep).id
        if expected is not None and msg.HasField("sender_id") and msg.sender_id != expected:
            return
        self.out.touch(ep)
        verdict, cached = self.dedup.check(ep, seq)
        if verdict == "dup":
            for data in cached:
                self.out.emit_raw(ep, data)
            return
        if verdict == "old":
            return
        handler = {
            "state": self._c_state,
            "ping": self._c_ping,
            "node_role_change": self._c_role_change,
            "error": self._c_error,
        }.get(t)
        if handler is None:
            return
        responses = handler(msg, ep, now)
        if responses is not None:
            self.dedup.record(ep, seq, responses)

    def _c_ping(self, msg, ep, now) -> List[bytes]:
        return [self._reply_ack(ep, msg)]

    def _c_state(self, msg, ep: Endpoint, now: float) -> Optional[List[bytes]]:
        from .session import Phase

        st = msg.state.state
        rid = msg.receiver_id if msg.HasField("receiver_id") else None
        if self.phase == Phase.CONNECTING:
            # До ACK/конфига храним только снимок с наибольшим state_order.
            if st.state_order < 0:
                return None
            if self.buffered is None or st.state_order > self.buffered[0].state_order:
                self.buffered = (st, rid)
            ack = self._reply_ack(ep, msg)
            self._try_activate()
            return [ack]
        try:
            world = codec.world_from_proto(st, self.config, self.game_name, ep)
        except ValueError:
            return None  # некорректный снимок игнорируется
        ack = self._reply_ack(ep, msg)
        if world.state_order <= self.world.state_order:
            return [ack]  # устаревший: подтверждаем, но не применяем
        if world.player(self.my_id) is None:
            self.fail("Вы удалены из игры (MASTER потерял связь с вами)")
            return [ack]
        self._apply_world(world)
        return [ack]

    def _c_error(self, msg, ep: Endpoint, now: float) -> List[bytes]:
        from .session import Phase

        ack = self._reply_ack(ep, msg)
        text = msg.error.error_message
        req = msg.error.request_seq
        self.out.cancel(req)
        if self.phase == Phase.CONNECTING and req == self.join_seq:
            self.fail(text or "Присоединение отклонено")
        else:
            self.status_pending = False
            self.notice(text or "Ошибка операции")
        return [ack]

    def _c_role_change(self, msg, ep: Endpoint, now: float) -> List[bytes]:
        n = msg.node_role_change
        ack = self._reply_ack(ep, msg)
        w = self.world
        if w is None:
            return [ack]
        stale = n.state_order < w.state_order  # устаревшее уведомление подтверждается без применения
        if ep != self.master_ep:  # объявление нового MASTER от известного DEPUTY
            if not stale:
                self._switch_master(ep, now)
            return [ack]
        if stale:
            return [ack]
        me = w.player(self.my_id)
        if n.HasField("receiver_role") and n.receiver_role == pb.DEPUTY and not n.HasField("sender_role"):
            if me is not None and me.role == pb.NORMAL:
                me.role = pb.DEPUTY
                self.version += 1
        elif (n.HasField("sender_role") and n.sender_role == pb.NORMAL
              and n.HasField("receiver_role") and n.receiver_role == pb.MASTER):
            if me is not None and me.role == pb.DEPUTY:  # осознанный выход MASTER
                self.dedup.record(ep, msg.msg_seq, [ack])
                self._become_master(now, order_hint=n.state_order)
        return [ack]

    # --------------------------------------------------------------- failover
    def _switch_master(self, ep: Endpoint, now: float) -> None:
        dep = self.world.player_at(ep)
        if dep is None or ep == self.master_ep:
            return
        self.out.retarget(self.master_ep, ep, dep.id)
        self.master_ep, self.master_id = ep, dep.id
        self.out.link(ep).last_recv = now
        self.failover_done = True
        self.version += 1

    def _c_master_lost(self, now: float) -> None:
        w = self.world
        me = w.player(self.my_id)
        if me is not None and me.role == pb.DEPUTY:
            self._become_master(now)
            return
        if self.failover_done:
            self.fail("Потеряна связь с MASTER и его заместителем")
            return
        dep_ep = self._deputy_endpoint()
        if dep_ep is None:
            self.fail("Потеряна связь с MASTER, заместителя нет")
            return
        self._switch_master(dep_ep, now)

    def _become_master(self, now: float, order_hint: Optional[int] = None) -> None:
        """DEPUTY становится MASTER: продолжает последнюю принятую копию, удаляет прежнего MASTER."""
        from .session import Phase

        w = self.world
        for old in [p for p in w.players if p.role == pb.MASTER and p.id != self.my_id]:
            w.players = [p for p in w.players if p.id != old.id]
            w.snakes = [s for s in w.snakes if s.player_id != old.id]
        me = w.player(self.my_id)
        me.role = pb.MASTER
        if order_hint is not None:
            w.state_order = max(w.state_order, order_hint - 1)
        self.out.clear()
        self.dedup = type(self.dedup)()
        self.is_master = True
        self.master_ep = self.master_id = None
        self.phase = Phase.ACTIVE
        self.status_pending = False
        self.pending_dirs.clear()
        self.next_tick = now + w.config.state_delay_ms / 1000.0
        for p in w.players:
            if p.id != self.my_id and p.endpoint:
                self.out.link(p.endpoint).last_recv = now
        self._commit(notify_master=True)
        self._announce(now)
