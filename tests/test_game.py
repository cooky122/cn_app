import unittest

from server.game import Bullet, Game
from shared.protocol import BASE_DAMAGE, BOOST_DAMAGE, BOOST_DURATION, ITEM_RESPAWN


class GameTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.game.add_player("a", "Alice")
        self.game.add_player("b", "Bob")
        self.game.mark_ready("a")
        self.game.mark_ready("b")
        self.game.drain_events()

    def hit(self, target_id, owner_id, damage=BASE_DAMAGE):
        target = self.game.players[target_id]
        self.game.bullets.append(Bullet(owner_id, target.x - 30, target.y, 650, 0, damage))

    def test_ten_normal_hits_end_once_and_preserve_records_on_rematch(self):
        for index in range(10):
            self.hit("b", "a")
            self.game.update(1 / 60)
            self.assertEqual(self.game.players["b"].health, 100 - (index + 1) * 10)
        self.assertEqual(self.game.result["winner_id"], "a")
        self.game.update(1.0)
        self.game.finish_match("a", "knockout")
        self.assertEqual(self.game.records["Alice"]["wins"], 1)
        self.assertEqual(self.game.records["Bob"]["losses"], 1)
        self.game.request_rematch("a")
        self.game.request_rematch("a")
        self.assertEqual(self.game.phase, "finished")
        self.game.request_rematch("b")
        self.assertEqual(self.game.phase, "playing")
        self.assertEqual(self.game.match_id, 2)
        self.assertTrue(all(p.health == 100 for p in self.game.players.values()))
        self.assertEqual(self.game.records["Alice"]["wins"], 1)

    def test_item_damage_expiry_and_respawn(self):
        player = self.game.players["a"]
        player.x, player.y = self.game.item
        self.game.update(1 / 60)
        self.assertIsNone(self.game.item)
        self.assertAlmostEqual(player.boost_until - self.game.now, BOOST_DURATION)
        self.game.fire(player)
        self.assertEqual(self.game.bullets[-1].damage, BOOST_DAMAGE)
        self.hit("b", "a", BOOST_DAMAGE)
        self.game.update(1 / 60)
        self.assertEqual(self.game.players["b"].health, 85)
        for _ in range(int(BOOST_DURATION * 60) + 2):
            self.game.update(1 / 60)
        self.game.fire(player)
        self.assertEqual(self.game.bullets[-1].damage, BASE_DAMAGE)
        for _ in range(int((ITEM_RESPAWN - BOOST_DURATION) * 60) + 2):
            self.game.update(1 / 60)
        self.assertIsNotNone(self.game.item)

    def test_simultaneous_death_and_timeout_are_draws(self):
        for player in self.game.players.values():
            player.health = 10
        self.hit("a", "b")
        self.hit("b", "a")
        self.game.update(1 / 60)
        self.assertEqual(self.game.result["reason"], "simultaneous")
        self.assertTrue(all(r["draws"] == 1 for r in self.game.records.values()))
        self.game.start_match()
        self.game.round_end = self.game.now + 0.01
        self.game.update(0.02)
        self.assertEqual(self.game.result["reason"], "timeout")
        self.assertTrue(all(r["draws"] == 2 for r in self.game.records.values()))

    def test_disconnect_records_one_forfeit_and_reconnect_reuses_name(self):
        self.game.remove_player("b")
        self.game.remove_player("b")
        self.assertEqual(self.game.records["Alice"]["wins"], 1)
        self.assertEqual(self.game.records["Bob"]["losses"], 1)
        self.game.add_player("new-b", "Bob")
        self.game.mark_ready("new-b")
        self.assertEqual(self.game.phase, "playing")
        self.assertEqual(self.game.records["Bob"]["losses"], 1)
        self.assertTrue(all(p.health == 100 for p in self.game.players.values()))

    def test_invalid_and_stale_input_cannot_move_players(self):
        player = self.game.players["a"]
        start = (player.x, player.y)
        message = {"match_id": self.game.match_id - 1, "move": [1, 0],
                   "aim": [1, 0], "shooting": False}
        self.game.set_input("a", message)
        self.game.update(0.1)
        self.assertEqual((player.x, player.y), start)
        message["match_id"] = self.game.match_id
        message["move"] = [float("nan"), 0]
        self.game.set_input("a", message)
        message["move"] = [10 ** 1000, 0]
        self.game.set_input("a", message)
        self.game.update(0.1)
        self.assertEqual((player.x, player.y), start)
        message["move"] = [1, 1]
        self.game.set_input("a", message)
        self.game.update(0.1)
        self.assertAlmostEqual(((player.x - start[0]) ** 2 + (player.y - start[1]) ** 2) ** 0.5, 25)
        stopped = (player.x, player.y)
        self.game.update(0.5)
        self.assertEqual((player.x, player.y), stopped)


if __name__ == "__main__":
    unittest.main()
