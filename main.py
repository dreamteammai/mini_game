from __future__ import annotations
import json
import random
from abc import ABC, abstractmethod
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Tuple


#дескриптор для проверки числовых характеристик
class BoundedStat:
    def __init__(self, name: str, min_value: float = 0.0, max_value: Optional[float] = None):
        self.name = name
        self.min = min_value
        self.max = max_value
        self.private_name = f"_{name}"

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return getattr(instance, self.private_name, 0.0)

    def __set__(self, instance, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise TypeError(f"{self.name} должно быть число")
        if self.max is not None:
            v = max(self.min, min(self.max, v))
        else:
            v = max(self.min, v)
        setattr(instance, self.private_name, v)

    def __delete__(self, instance):
        raise AttributeError("Нельзя удалить параметр")


#создание миксинов
class LoggerMixin:
    def log(self, message: str):
        print(message)


class CritMixin:
    crit_chance: float = 0.0
    crit_multiplier: float = 1.5

    def roll_crit(self) -> bool:
        return random.random() < getattr(self, 'crit_chance', 0.0)


class SilenceMixin:
    def is_silenced(self) -> bool:
        return any(isinstance(e, SilenceEffect) for e in getattr(self, 'effects', []))


#базовые классы
class Human:
    hp = BoundedStat('hp', min_value=0)
    mp = BoundedStat('mp', min_value=0)
    strength = BoundedStat('strength', min_value=0)
    agility = BoundedStat('agility', min_value=0)
    intelligence = BoundedStat('intelligence', min_value=0)

    def __init__(
        self,
        name: str,
        level: int = 1,
        max_hp: float = 100.0,
        max_mp: float = 50.0,
        strength: float = 10.0,
        agility: float = 10.0,
        intelligence: float = 10.0,
    ):
        self.name = name
        self.level = level
        self._max_hp = float(max_hp)
        self._max_mp = float(max_mp)
        #инициализация через дескрипторы
        self.hp = self._max_hp
        self.mp = self._max_mp
        self.strength = strength
        self.agility = agility
        self.intelligence = intelligence

    @property
    def max_hp(self) -> float:
        return self._max_hp

    @property
    def max_mp(self) -> float:
        return self._max_mp

    def __str__(self):
        return f"{self.name} (Уровень {self.level})"

    def __repr__(self):
        return f"{self.__class__.__name__}('{self.name}', lvl={self.level})"


#система эффектов
class Effect(ABC):
    def __init__(self, source: Any, duration: int):
        self.source = source
        self.duration = duration

    def apply(self, target: 'Character'):
        pass

    def on_turn(self, target: 'Character'):
        self.duration -= 1

    def expire(self, target: 'Character'):
        pass


class ShieldEffect(Effect):
    def __init__(self, source: Any, amount: float, duration: int):
        super().__init__(source, duration)
        self.amount = amount

    def apply(self, target: 'Character'):
        target.shield += self.amount

    def expire(self, target: 'Character'):
        target.shield = max(0.0, target.shield - self.amount)


class DotEffect(Effect):
    def __init__(self, source: Any, damage: float, duration: int):
        super().__init__(source, duration)
        self.damage = damage

    def on_turn(self, target: 'Character'):
        if target.is_alive:
            target.take_damage(self.damage, source=self.source, is_dot=True)
        super().on_turn(target)

#маркерный эффект
class SilenceEffect(Effect):
    pass


class RegenEffect(Effect):
    def __init__(self, source: Any, amount: float, duration: int):
        super().__init__(source, duration)
        self.amount = amount

    def on_turn(self, target: 'Character'):
        if target.is_alive:
            target.heal(self.amount)
        super().on_turn(target)


#предметы
@dataclass
class Item:
    name: str
    description: str = ""
    hp_restore: float = 0.0
    mp_restore: float = 0.0

    def use(self, target: 'Character'):
        if self.hp_restore:
            target.heal(self.hp_restore)
        if self.mp_restore:
            target.restore_mp(self.mp_restore)

#инвентарь
class Inventory:
    def __init__(self):
        self.items: Dict[str, Tuple[Item, int]] = {}

    def add(self, item: Item, count: int = 1):
        if item.name in self.items:
            _, cur = self.items[item.name]
            self.items[item.name] = (item, cur + count)
        else:
            self.items[item.name] = (item, count)

    def remove_by_name(self, name: str, count: int = 1) -> bool:
        if name not in self.items:
            return False
        item, cur = self.items[name]
        if cur < count:
            return False
        if cur == count:
            del self.items[name]
        else:
            self.items[name] = (item, cur - count)
        return True

    def has(self, name: str) -> bool:
        return name in self.items and self.items[name][1] > 0

    def use(self, name: str, target: 'Character') -> bool:
        if not self.has(name):
            return False
        item, _ = self.items[name]
        item.use(target)
        self.remove_by_name(name, 1)
        return True

    def list_items(self) -> List[Tuple[str, Item, int]]:
        return [(name, it[0], it[1]) for name, it in self.items.items()]


#персонажи
class Character(Human, ABC, LoggerMixin, CritMixin, SilenceMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.effects: List[Effect] = []
        self.shield: float = 0.0
        self.cooldowns: Dict[str, int] = {}
        self.inventory = Inventory()

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    def apply_effect(self, effect: Effect):
        effect.apply(self)
        self.effects.append(effect)
        self.log(f"{self.name} получает эффект: {effect.__class__.__name__} ({effect.duration} ходов)")

    def remove_expired_effects(self):
        still: List[Effect] = []
        for e in self.effects:
            if e.duration <= 0:
                e.expire(self)
                self.log(f"{self.name}: эффект {e.__class__.__name__} закончился")
            else:
                still.append(e)
        self.effects = still

    def start_turn_effects(self):
        for e in list(self.effects):
            e.on_turn(self)
        self.remove_expired_effects()

    def take_damage(self, amount: float, source=None, is_dot: bool = False):
        if self.shield > 0:
            absorbed = min(self.shield, amount)
            self.shield -= absorbed
            amount -= absorbed
            self.log(f"{self.name} — щит отразил {absorbed:.1f} урона")
        if amount <= 0:
            return
        old = self.hp
        self.hp = max(0.0, self.hp - amount)
        self.log(f"{self.name} получает {amount:.1f} урона от {getattr(source, 'name', source)} 🡺 {self.hp:.1f}/{self.max_hp:.1f} HP")

    def heal(self, amount: float):
        old = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        self.log(f"{self.name} восстановил {self.hp - old:.1f} HP 🡺 {self.hp:.1f}/{self.max_hp:.1f}")

    def restore_mp(self, amount: float):
        old = self.mp
        self.mp = min(self.max_mp, self.mp + amount)
        self.log(f"{self.name} восстановил {self.mp - old:.1f} MP 🡺 {self.mp:.1f}/{self.max_mp:.1f}")

    def spend_mp(self, amount: float) -> bool:
        if self.mp >= amount:
            self.mp -= amount
            return True
        return False

    def basic_attack(self, target: 'Character'):
        base = self.strength * 1.0
        crit = self.roll_crit()
        if crit:
            base *= self.crit_multiplier
            self.log(f"{self.name} наносит критический удар")
        damage = random.uniform(0.9, 1.1) * base
        target.take_damage(damage, source=self)

    @abstractmethod
    def use_skill(self, target: Optional['Character'] = None, allies: Optional[List['Character']] = None):
        pass


#классы персонажей
class Warrior(Character):
    def __init__(self, name: str):
        super().__init__(name, level=1, max_hp=150.0, max_mp=30.0,
                         strength=20.0, agility=12.0, intelligence=6.0)
        self.crit_chance = 0.12
        self.cooldowns = {'power_strike': 0}

    def power_strike(self, target: Character) -> bool:
        cost = 8
        cd = 2
        if self.is_silenced():
            self.log(f"{self.name} немой и не может использовать сокрушительный удар")
            return False
        if self.cooldowns.get('power_strike', 0) > 0:
            self.log(f"{self.name}: сокрушительный удар сейчас недоступен")
            return False
        if not self.spend_mp(cost):
            self.log(f"{self.name} не хватает MP для сокрушительного удара")
            return False
        self.cooldowns['power_strike'] = cd
        damage = self.strength * 2.0
        if self.roll_crit():
            damage *= self.crit_multiplier
            self.log(f"{self.name} наносит критически сокрушительный удар!")
        target.take_damage(damage, source=self)
        return True

    def use_skill(self, target: Optional[Character] = None, allies: Optional[List[Character]] = None):
        if target is None:
            return
        used = self.power_strike(target)
        if not used:
            self.basic_attack(target)


class Mage(Character):
    def __init__(self, name: str):
        super().__init__(name, level=1, max_hp=90.0, max_mp=140.0,
                         strength=6.0, agility=10.0, intelligence=22.0)
        self.crit_chance = 0.06
        self.cooldowns = {'fireball': 0}

    def fireball(self, target: Character) -> bool:
        cost = 20
        cd = 3
        if self.is_silenced():
            self.log(f"{self.name} немой и не может использовать огненный шар")
            return False
        if self.cooldowns.get('fireball', 0) > 0:
            self.log(f"{self.name}: огненный шар на перезарядке")
            return False
        if not self.spend_mp(cost):
            self.log(f"{self.name} не хватает MP для использования огненного шара")
            return False
        self.cooldowns['fireball'] = cd
        damage = self.intelligence * 3.0
        target.take_damage(damage, source=self)
        dot = DotEffect(self, damage * 0.25, duration=2)
        target.apply_effect(dot)
        return True

    def use_skill(self, target: Optional[Character] = None, allies: Optional[List[Character]] = None):
        if target is None:
            return
        used = self.fireball(target)
        if not used:
            self.basic_attack(target)


class Healer(Character):
    def __init__(self, name: str):
        super().__init__(name, level=1, max_hp=110.0, max_mp=130.0,
                         strength=6.0, agility=10.0, intelligence=20.0)
        self.crit_chance = 0.03
        self.cooldowns = {'mass_heal': 0}

    def mass_heal(self, allies: List[Character]) -> bool:
        cost = 25
        cd = 3
        if self.is_silenced():
            self.log(f"{self.name} нем и не может исцелить команду")
            return False
        if self.cooldowns.get('mass_heal', 0) > 0:
            self.log(f"{self.name}: командное исцеление на перезарядке")
            return False
        if not self.spend_mp(cost):
            self.log(f"{self.name} не хватает MP для командного исцеления")
            return False
        self.cooldowns['mass_heal'] = cd
        amount = self.intelligence * 2.0
        for a in allies:
            if a.is_alive:
                a.heal(amount)
        return True

    def use_skill(self, target: Optional[Character] = None, allies: Optional[List[Character]] = None):
        if allies is None:
            allies = []
        used = self.mass_heal(allies)
        if not used:
            if target and target.is_alive:
                self.basic_attack(target)


#босс и паттерн Strategy
class BossStrategy(ABC):
    @abstractmethod
    def choose_action(self, boss: 'Boss', allies: List[Character], enemies: List[Character]) -> Tuple[Optional[Character], str]:
        pass


class AggressiveStrategy(BossStrategy):
    def choose_action(self, boss: 'Boss', allies: List[Character], enemies: List[Character]) -> Tuple[Optional[Character], str]:
        living = [e for e in enemies if e.is_alive]
        if not living:
            return None, 'wait'
        target = min(living, key=lambda x: x.hp)
        return target, 'smash'


class DefensiveStrategy(BossStrategy):
    def choose_action(self, boss: 'Boss', allies: List[Character], enemies: List[Character]) -> Tuple[Optional[Character], str]:
        if boss.shield < boss.max_hp * 0.15:
            return boss, 'shield'
        living = [e for e in enemies if e.is_alive]
        if not living:
            return None, 'wait'
        target = max(living, key=lambda x: x.strength)
        return target, 'smash'


class Boss(Character):
    def __init__(self, name: str):
        super().__init__(name, level=5, max_hp=600.0, max_mp=80.0,
                         strength=26.0, agility=8.0, intelligence=14.0)
        self.phase_thresholds = [0.66, 0.33]
        self.strategies = {
            'phase1': AggressiveStrategy(),
            'phase2': DefensiveStrategy(),
            'phase3': AggressiveStrategy(),
        }

    @property
    def phase(self) -> int:
        ratio = (self.hp / self.max_hp) if self.max_hp > 0 else 0
        if ratio > self.phase_thresholds[0]:
            return 1
        elif ratio > self.phase_thresholds[1]:
            return 2
        else:
            return 3

    def choose_strategy(self) -> BossStrategy:
        return self.strategies[f'phase{self.phase}']

    def smash(self, target: Character):
        damage = self.strength * 2.2
        self.log(f"{self.name} использует удар по {target.name}")
        target.take_damage(damage, source=self)

    def shield_self(self):
        amount = self.intelligence * 3.5
        self.log(f"{self.name} использует щит величиной {amount:.1f}")
        self.apply_effect(ShieldEffect(self, amount, duration=2))

    def cast_silence(self, target: Character):
        self.log(f"{self.name} накладывает немоту на {target.name}")
        target.apply_effect(SilenceEffect(self, duration=1))

    def use_skill(self, target: Optional[List[Character]] = None, allies: Optional[List[Character]] = None):
        enemies = target or []
        strategy = self.choose_strategy()
        chosen_target, action = strategy.choose_action(self, allies or [], enemies)
        if action == 'smash' and chosen_target is not None:
            self.smash(chosen_target)
        elif action == 'shield':
            self.shield_self()
        else:
            self.log(f"{self.name} пропускает ход")

        if self.phase == 3 and enemies:
            if random.random() < 0.5:
                candidates = [e for e in enemies if e.is_alive]
                if candidates:
                    t = random.choice(candidates)
                    self.cast_silence(t)


#порядок ходов
class TurnOrder:
    def __init__(self, combatants: List[Character]):
        self.combatants = combatants
        self._order = deque()
        self.prepare_round()

    def prepare_round(self):
        living = [c for c in self.combatants if c.is_alive]
        random.shuffle(living)
        living.sort(key=lambda x: x.agility, reverse=True)
        self._order = deque(living)

    def __iter__(self):
        return self

    def __next__(self) -> Character:
        while self._order:
            c = self._order.popleft()
            if c.is_alive:
                return c
        raise StopIteration


#логирование раундов
class RoundLogger:
    def __init__(self):
        self.entries: List[Dict[str, Any]] = []

    def record(self, message: str):
        self.entries.append({'msg': message})

    def dump(self, path: str = 'battle_log.json'):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)


@contextmanager
def log_round(logger: RoundLogger, round_number: int):
    logger.record(f"--- Раунд {round_number} начало ---")
    try:
        yield
    finally:
        logger.record(f"--- Раунд {round_number} конец ---")


#класс битвы
class Battle(LoggerMixin):
    def __init__(self, party: List[Character], boss: Boss, verbose: bool = True):
        self.party = party
        self.boss = boss
        self.combatants: List[Character] = party + [boss]
        self.round = 1
        self.logger = RoundLogger()
        self.verbose = verbose

    def broadcast(self, message: str):
        if self.verbose:
            print(message)
        self.logger.record(message)

    def tick_cooldowns(self):
        for c in self.combatants:
            for k in list(c.cooldowns.keys()):
                if c.cooldowns[k] > 0:
                    c.cooldowns[k] -= 1

    def _choose_item_from_hero(self, hero: Character) -> Optional[str]:
        items = hero.inventory.list_items()
        if not items:
            print("Инвентарь пуст")
            return None
        print("Инвентарь:")
        for i, (name, item, cnt) in enumerate(items, start=1):
            print(f"{i}. {name} x{cnt} — {item.description}")
        choice = input("Введите номер предмета (или Enter для отмены): ").strip()
        if choice == "":
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                return items[idx][0]
        except ValueError:
            pass
        print("Неверный выбор предмета.")
        return None

    def _hero_menu_action(self, hero: Character) -> bool:
        print(f"\nХод героя: {hero.name} — HP {hero.hp:.1f}/{hero.max_hp:.1f}, MP {hero.mp:.1f}/{hero.max_mp:.1f}")
        print("0 - Выйти из боя")
        print("1 - Обычная атака")
        print("2 - Использовать навык")
        print("3 - Использовать предмет")
        choice = input("Выберите действие: ").strip()
        if choice == "0":
            confirm = input("Вы уверены, что хотите выйти из боя? (yes/no): ").strip().lower()
            if confirm == 'yes':
                return True
            return False
        if choice == "1":
            hero.basic_attack(self.boss)
        elif choice == "2":
            # use_skill сам внутри решает, можно передать босс и союзников
            hero.use_skill(target=self.boss, allies=self.party)
        elif choice == "3":
            item_name = self._choose_item_from_hero(hero)
            if item_name:
                used = hero.inventory.use(item_name, hero)
                if used:
                    print(f"{hero.name} использовал(а) {item_name}.")
                else:
                    print("Не удалось использовать предмет.")
            else:
                print("Предмет не выбран — действие пропущено.")
        else:
            print("Неверный ввод — выполняется обычная атака.")
            hero.basic_attack(self.boss)
        return False

    def run(self, max_rounds: int = 50):
        self.broadcast("Бой начинается!")
        while self.round <= max_rounds and self.boss.is_alive and any(h.is_alive for h in self.party):
            with log_round(self.logger, self.round):
                self.broadcast(f"\n※※※ Раунд {self.round} — фаза босса: {self.boss.phase} ※※※")
                order = TurnOrder(self.combatants)
                for actor in order:
                    if not actor.is_alive:
                        continue
                    actor.start_turn_effects()
                    if not actor.is_alive:
                        continue

                    if isinstance(actor, Boss):
                        actor.use_skill(target=self.party, allies=[self.boss])
                        if not any(h.is_alive for h in self.party):
                            break
                        continue

                    hero = actor  # type: Character
                    boss_hp_before = self.boss.hp

                    exit_battle = self._hero_menu_action(hero)
                    if exit_battle:
                        self.broadcast("Игрок вышел из боя. Бой завершён досрочно.")
                        self.logger.dump()
                        return False

                    boss_took_damage = boss_hp_before > self.boss.hp
                    if boss_took_damage and self.boss.is_alive and any(h.is_alive for h in self.party):
                        target = random.choice([h for h in self.party if h.is_alive])
                        self.broadcast(f"\n>>> {self.boss.name} наносит ответный удар по {target.name}!")
                        self.boss.smash(target)
                        if not any(h.is_alive for h in self.party):
                            break

                    if not any(h.is_alive for h in self.party) or not self.boss.is_alive:
                        break

                self.tick_cooldowns()
            self.round += 1

        if self.boss.is_alive:
            self.broadcast("※※※ Босс побеждает... ※※※")
            self.logger.dump()
            return False
        else:
            self.broadcast("※※※ Пати побеждает! Поздравляю! ※※※")
            self.logger.dump()
            return True


#вспомогательные функции
def make_sample_party() -> List[Character]:
    w = Warrior('Леголас')
    m = Mage('Гэндальф')
    h = Healer('Арагорн')
    potion = Item('Элексир жизни', 'Восстанавливает 50 HP', hp_restore=50)
    mana_potion = Item('Исидас мортум', 'Восстанавливает 40 MP', mp_restore=40)
    m.inventory.add(potion, 1)
    w.inventory.add(potion, 1)
    h.inventory.add(mana_potion, 1)
    return [w, m, h]


#точка входа в игру
def main():
    random.seed()
    party = make_sample_party()
    boss = Boss('Огнедышащий дракон')
    battle = Battle(party, boss, verbose=True)
    battle.run(max_rounds=50)


if __name__ == '__main__':
    main()
