import pytest
from main import Warrior, Mage, Healer, Boss, Inventory


def test_warrior_has_valid_stats():
    hero = Warrior("Артур")
    assert hero.hp > 0
    assert hero.mp > 0
    assert hero.strength > 0


def test_stat_cannot_be_negative():
    hero = Warrior("Артур")
    hero.hp = -50
    assert hero.hp == 0


def test_is_alive_flag():
    hero = Warrior("Артур")
    hero.hp = 0
    assert not hero.is_alive


def test_basic_attack_reduces_hp():
    hero = Warrior("Артур")
    boss = Boss("Дракон")
    start_hp = boss.hp
    hero.basic_attack(boss)
    assert boss.hp < start_hp


def test_use_skill_spends_mp():
    mage = Mage("Мерлин")
    boss = Boss("Дракон")
    start_mp = mage.mp
    mage.use_skill(boss)
    assert mage.mp < start_mp


def test_healer_can_heal():
    healer = Healer("Эльронд")
    hero = Warrior("Артур")
    hero.hp = 10
    healer.use_skill(hero)
    assert hero.hp >= 10.0


def test_inventory_add_and_use():
    hero = Warrior("Артур")
    potion = hero.inventory
    assert isinstance(potion, Inventory)


def test_boss_phase_change():
    boss = Boss("Дракон")
    boss.hp = boss.max_hp * 0.4
    assert boss.hp / boss.max_hp < 0.5
