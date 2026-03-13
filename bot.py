"""
Protoss Bot - macro oriented Blink / Immortal / Colossus style.
"""

import argparse

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.position import Point2

DIFFICULTY_MAP = {
    "easy": Difficulty.Easy,
    "medium": Difficulty.Medium,
    "hard": Difficulty.Hard,
    "harder": Difficulty.Harder,
    "veryhard": Difficulty.VeryHard,
    "elite": Difficulty.CheatVision,
}

ARMY_UNITS = {
    UnitTypeId.ZEALOT,
    UnitTypeId.STALKER,
    UnitTypeId.SENTRY,
    UnitTypeId.IMMORTAL,
    UnitTypeId.COLOSSUS,
}

WORKER_TYPES = {
    UnitTypeId.SCV,
    UnitTypeId.DRONE,
    UnitTypeId.PROBE,
    UnitTypeId.MULE,
}

WARP_IN_ABILITIES = {
    UnitTypeId.ZEALOT: AbilityId.WARPGATETRAIN_ZEALOT,
    UnitTypeId.STALKER: AbilityId.WARPGATETRAIN_STALKER,
    UnitTypeId.SENTRY: AbilityId.WARPGATETRAIN_SENTRY,
}


class ProtossBot(BotAI):
    """
    A stronger Protoss script bot built around:
    1. 1-Gate expand into 2-base macro
    2. Fast Warpgate + Blink
    3. Robotics support with Observers / Immortals
    4. Colossus transition on 3 bases
    5. Stalker blink retreat and timing-based attacks
    """

    def __init__(self):
        super().__init__()
        self.attack_committed = False
        self.opening_pressure_committed = False
        self.enemy_start_candidates: list[Point2] = []
        self.confirmed_enemy_start: Point2 | None = None
        self.scout_worker_tag: int | None = None
        self.cannon_rush_committed = False
        self.cannon_rush_abandoned = False

    @property
    def army(self):
        return self.units.of_type(ARMY_UNITS)

    def army_strength(self) -> int:
        return (
            self.units(UnitTypeId.ZEALOT).amount
            + self.units(UnitTypeId.STALKER).amount
            + self.units(UnitTypeId.SENTRY).amount
            + (self.units(UnitTypeId.IMMORTAL).amount * 2)
            + (self.units(UnitTypeId.COLOSSUS).amount * 3)
        )

    def gateway_total(self) -> int:
        return (
            self.structures(UnitTypeId.GATEWAY).amount
            + self.structures(UnitTypeId.WARPGATE).amount
        )

    def main_base(self):
        if not self.townhalls.ready.exists:
            return None
        return self.townhalls.ready.furthest_to(self.enemy_reference_point())

    def gather_point(self) -> Point2:
        if not self.townhalls.ready.exists:
            return self.game_info.map_center
        distance = 14 if self.townhalls.ready.amount < 3 else 20
        return self.townhalls.ready.center.towards(
            self.enemy_reference_point(), distance
        )

    def fallback_point(self) -> Point2:
        if not self.townhalls.ready.exists:
            return self.game_info.map_center
        return self.townhalls.ready.center.towards(self.game_info.map_center, 4)

    def initialize_enemy_start_candidates(self):
        if self.enemy_start_candidates:
            return
        start = self.start_location or self.game_info.map_center
        candidates = [
            location
            for location in self.enemy_start_locations
            if self.start_location is None or location.distance_to(self.start_location) > 1
        ]
        self.enemy_start_candidates = sorted(
            candidates,
            key=lambda location: start.distance_to(location),
        )

    def refresh_enemy_start_intel(self):
        self.initialize_enemy_start_candidates()
        start = self.start_location or self.game_info.map_center

        if self.enemy_structures.exists:
            reference = self.enemy_structures.closest_to(start)
            matched = min(
                self.enemy_start_candidates or self.enemy_start_locations,
                key=lambda location: location.distance_to(reference.position),
                default=None,
            )
            if matched and matched.distance_to(reference.position) <= 18:
                self.confirmed_enemy_start = matched

        remaining_candidates: list[Point2] = []
        for location in self.enemy_start_candidates:
            if self.confirmed_enemy_start and location.distance_to(self.confirmed_enemy_start) <= 1:
                remaining_candidates = [self.confirmed_enemy_start]
                break

            if not self.is_visible(location):
                remaining_candidates.append(location)
                continue

            enemy_presence = self.enemy_structures.closer_than(15, location).exists
            if enemy_presence:
                self.confirmed_enemy_start = location
                remaining_candidates = [location]
                break

        if remaining_candidates:
            self.enemy_start_candidates = remaining_candidates
        elif self.confirmed_enemy_start:
            self.enemy_start_candidates = [self.confirmed_enemy_start]
        else:
            self.enemy_start_candidates = sorted(
                self.enemy_start_candidates or self.enemy_start_locations,
                key=lambda location: start.distance_to(location),
            )

    def next_scout_point(self) -> Point2:
        if self.confirmed_enemy_start is not None:
            return self.confirmed_enemy_start

        unseen_candidates = [
            location
            for location in self.enemy_start_candidates
            if not self.is_visible(location)
        ]
        if unseen_candidates:
            return unseen_candidates[0]

        if self.enemy_start_candidates:
            return self.enemy_start_candidates[0]

        return self.game_info.map_center

    def enemy_reference_point(self) -> Point2:
        if self.enemy_structures.exists:
            origin = self.army.center if self.army.exists else self.start_location
            if origin is not None:
                return self.enemy_structures.closest_to(origin).position
            return self.enemy_structures.first.position

        if self.confirmed_enemy_start is not None:
            return self.confirmed_enemy_start

        if self.enemy_start_candidates:
            return self.enemy_start_candidates[0]

        if self.enemy_start_locations:
            return self.enemy_start_locations[0]

        return self.game_info.map_center

    def combat_targets(self):
        return (self.enemy_units | self.enemy_structures).filter(
            lambda unit: unit.can_be_attacked
        )

    def enemy_air_threats(self):
        return self.enemy_units.filter(
            lambda unit: unit.can_be_attacked and unit.is_flying
        )

    def scout_worker(self):
        if self.scout_worker_tag is None:
            return None
        return self.workers.find_by_tag(self.scout_worker_tag)

    def cannon_rush_anchor(self) -> Point2 | None:
        if self.confirmed_enemy_start is None:
            return None
        return self.confirmed_enemy_start.towards(self.game_info.map_center, 7)

    def forward_cannon_pylons(self):
        if self.confirmed_enemy_start is None:
            return self.structures(UnitTypeId.PYLON).filter(lambda _: False)
        return self.structures(UnitTypeId.PYLON).filter(
            lambda pylon: pylon.distance_to(self.confirmed_enemy_start) < 18
        )

    def forward_cannons(self):
        if self.confirmed_enemy_start is None:
            return self.structures(UnitTypeId.PHOTONCANNON).filter(lambda _: False)
        return self.structures(UnitTypeId.PHOTONCANNON).filter(
            lambda cannon: cannon.distance_to(self.confirmed_enemy_start) < 18
        )

    def local_defensive_pressure(self, nexus):
        enemy_units = self.enemy_units.closer_than(24, nexus).filter(
            lambda unit: unit.can_be_attacked
            and unit.type_id not in WORKER_TYPES
            and (unit.can_attack_ground or unit.can_attack_air or unit.is_flying)
        )
        proxy_structures = self.enemy_structures.closer_than(20, nexus).filter(
            lambda structure: structure.can_be_attacked and not structure.is_flying
        )

        pressure = enemy_units.amount + (proxy_structures.amount * 2)
        if enemy_units.filter(lambda unit: unit.can_attack_ground).amount >= 3:
            pressure += 2
        if self.time < 300 and enemy_units.amount >= 2:
            pressure += 1
        return enemy_units, proxy_structures, pressure

    def is_under_early_rush(self) -> bool:
        if not self.townhalls.ready.exists:
            return False

        for nexus in self.townhalls.ready:
            enemy_units, proxy_structures, pressure = self.local_defensive_pressure(nexus)
            if proxy_structures.exists:
                return True
            if self.time < 330 and pressure >= 3:
                return True
            if enemy_units.amount >= 5:
                return True
        return False

    def should_prepare_cannon_rush(self) -> bool:
        if self.cannon_rush_abandoned:
            return False
        if self.time > 180:
            return False
        if self.confirmed_enemy_start is None:
            return False
        if self.townhalls.amount + self.already_pending(UnitTypeId.NEXUS) > 1:
            return False
        if self.workers.amount < 16:
            return False
        if self.is_under_early_rush():
            return False
        scout = self.scout_worker()
        if scout is None:
            return False
        if scout.shield_health_percentage < 0.35:
            return False
        return True

    def is_cannon_rush_active(self) -> bool:
        if self.cannon_rush_abandoned:
            return False
        if not self.cannon_rush_committed:
            return False
        if self.time > 260:
            return False
        if self.forward_cannon_pylons().exists or self.forward_cannons().exists:
            return True
        return (
            self.structures(UnitTypeId.FORGE).exists
            or self.already_pending(UnitTypeId.FORGE) > 0
        )

    def should_opening_pressure(self) -> bool:
        if self.attack_committed:
            return False
        if self.is_under_early_rush():
            return False
        if self.should_prepare_cannon_rush() or self.is_cannon_rush_active():
            return False
        if self.confirmed_enemy_start is None or not self.townhalls.ready.exists:
            return False
        if self.time < 150 or self.time > 360:
            return False
        if self.townhalls.ready.amount > 2:
            return False
        if self.gateway_total() < 2:
            return False
        if self.army_strength() >= 8:
            return True
        return (
            self.units(UnitTypeId.STALKER).amount >= 3
            and self.units(UnitTypeId.ZEALOT).amount >= 2
        )

    def opening_pressure_point(self) -> Point2:
        if self.enemy_structures.exists:
            return self.enemy_structures.closest_to(self.start_location).position
        if self.confirmed_enemy_start is not None:
            return self.confirmed_enemy_start.towards(self.game_info.map_center, 4)
        return self.enemy_reference_point()

    def should_attack(self) -> bool:
        blink_ready = self.already_pending_upgrade(UpgradeId.BLINKTECH) == 1
        if self.supply_used >= 170:
            return True
        if blink_ready and self.units(UnitTypeId.IMMORTAL).amount >= 2:
            return self.army_strength() >= 18
        if self.units(UnitTypeId.COLOSSUS).amount >= 1:
            return self.army_strength() >= 16
        return self.army_strength() >= 26

    def choose_gateway_unit(self) -> UnitTypeId:
        stalkers = self.units(UnitTypeId.STALKER).amount
        zealots = self.units(UnitTypeId.ZEALOT).amount
        sentries = self.units(UnitTypeId.SENTRY).amount
        rush_pressure = self.is_under_early_rush()
        opening_pressure = self.should_opening_pressure()

        if rush_pressure:
            if not self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists:
                return UnitTypeId.ZEALOT
            if self.enemy_air_threats().closer_than(20, self.townhalls.ready.center).exists:
                return UnitTypeId.STALKER
            if stalkers < 4:
                return UnitTypeId.STALKER
            if zealots < 2:
                return UnitTypeId.ZEALOT

        if opening_pressure:
            if not self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists:
                return UnitTypeId.ZEALOT
            if zealots < 2:
                return UnitTypeId.ZEALOT
            if stalkers < 4:
                return UnitTypeId.STALKER

        if (
            self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists
            and sentries == 0
            and stalkers >= 2
            and self.vespene >= 100
        ):
            return UnitTypeId.SENTRY

        if self.enemy_air_threats().amount >= 2:
            return UnitTypeId.STALKER

        if (
            self.already_pending_upgrade(UpgradeId.CHARGE) == 1
            and self.minerals > self.vespene + 250
        ):
            return UnitTypeId.ZEALOT

        if self.minerals > 800 and self.vespene < 150:
            return UnitTypeId.ZEALOT

        if self.already_pending_upgrade(UpgradeId.BLINKTECH) < 1:
            return UnitTypeId.STALKER

        if stalkers <= zealots + 4:
            return UnitTypeId.STALKER

        return UnitTypeId.ZEALOT

    def pick_combat_target(self, unit, candidates):
        valid = candidates.filter(
            lambda enemy: (
                (enemy.is_flying and unit.can_attack_air)
                or (not enemy.is_flying and unit.can_attack_ground)
            )
        )
        if not valid.exists:
            return None

        def sort_key(enemy):
            priority = 0
            if enemy.can_attack:
                priority += 6
            if enemy.is_detector:
                priority += 2
            if enemy.type_id in WORKER_TYPES:
                priority += 1
            if enemy.is_structure:
                priority -= 3
            if enemy.health_percentage < 0.45:
                priority += 2
            return (-priority, enemy.health + enemy.shield, unit.distance_to(enemy))

        return min(valid, key=sort_key)

    def choose_warp_pylon(self):
        pylons = self.structures(UnitTypeId.PYLON).ready
        if not pylons.exists or not self.townhalls.ready.exists:
            return None

        if self.attack_committed:
            forward = pylons.furthest_to(self.townhalls.ready.center)
            if forward.distance_to(self.townhalls.ready.center) > 18:
                return forward

        return pylons.closest_to(self.game_info.map_center)

    async def on_step(self, iteration: int):
        if not self.townhalls.exists:
            for worker in self.workers:
                worker.attack(self.enemy_reference_point())
            return

        self.refresh_enemy_start_intel()
        await self.distribute_workers()
        await self.build_workers()
        await self.build_pylons()
        await self.expand()
        await self.build_assimilators()
        await self.build_tech()
        await self.execute_cannon_rush()
        await self.build_static_defense()
        await self.research_upgrades()
        await self.morph_warpgates()
        await self.chrono_boost()
        await self.train_from_gateways()
        await self.train_from_robos()
        await self.build_forward_pylon()
        await self.warp_in_units()
        await self.scout_with_probe()
        await self.control_observers()
        await self.control_army()

    async def build_workers(self):
        worker_target = min(66, self.townhalls.ready.amount * 22)
        if self.workers.amount + self.already_pending(UnitTypeId.PROBE) >= worker_target:
            return

        for nexus in self.townhalls.ready.idle:
            if self.workers.amount + self.already_pending(UnitTypeId.PROBE) >= worker_target:
                return
            if self.can_afford(UnitTypeId.PROBE):
                nexus.train(UnitTypeId.PROBE)

    async def build_pylons(self):
        if not self.townhalls.ready.exists:
            return

        buffer = 2 if self.supply_used < 36 else 4 if self.supply_used < 90 else 7
        pending_limit = 1 if self.supply_used < 120 else 2
        if self.supply_left >= buffer or self.already_pending(UnitTypeId.PYLON) >= pending_limit:
            return

        if not self.can_afford(UnitTypeId.PYLON):
            return

        anchor = self.townhalls.ready.center.towards(self.game_info.map_center, 6)
        if self.structures(UnitTypeId.PYLON).ready.exists:
            anchor = self.structures(UnitTypeId.PYLON).ready.closest_to(
                self.game_info.map_center
            ).position

        await self.build(
            UnitTypeId.PYLON,
            near=anchor,
            max_distance=10,
            placement_step=2,
        )

    async def expand(self):
        total_bases = self.townhalls.ready.amount + self.already_pending(UnitTypeId.NEXUS)
        cannon_rush_active = self.should_prepare_cannon_rush() or self.is_cannon_rush_active()

        if (
            total_bases < 2
            and self.workers.amount >= 20
            and self.structures(UnitTypeId.GATEWAY).ready.exists
            and not cannon_rush_active
            and not self.is_under_early_rush()
            and self.can_afford(UnitTypeId.NEXUS)
        ):
            await self.expand_now()
            return

        if (
            total_bases < 3
            and self.workers.amount >= 44
            and self.army_strength() >= 10
            and not cannon_rush_active
            and not self.is_under_early_rush()
            and self.can_afford(UnitTypeId.NEXUS)
        ):
            await self.expand_now()

    async def build_assimilators(self):
        if not self.townhalls.ready.exists:
            return

        desired_gas = 0
        if self.structures(UnitTypeId.GATEWAY).exists:
            desired_gas = 1
        if self.structures(UnitTypeId.CYBERNETICSCORE).exists:
            desired_gas = max(desired_gas, min(2, self.townhalls.ready.amount * 2))
        if (
            self.structures(UnitTypeId.TWILIGHTCOUNCIL).exists
            or self.structures(UnitTypeId.ROBOTICSFACILITY).exists
        ):
            desired_gas = max(desired_gas, min(4, self.townhalls.ready.amount * 2))
        if self.townhalls.ready.amount >= 3:
            desired_gas = 6

        current_gas = self.gas_buildings.amount
        if current_gas >= desired_gas:
            return

        for nexus in self.townhalls.ready:
            for geyser in self.vespene_geyser.closer_than(10, nexus):
                if current_gas >= desired_gas:
                    return
                if not self.can_afford(UnitTypeId.ASSIMILATOR):
                    return
                if self.gas_buildings.closer_than(1, geyser):
                    continue
                worker = self.select_build_worker(geyser.position)
                if worker is None:
                    continue
                worker.build_gas(geyser)
                worker.stop(queue=True)
                current_gas += 1

    async def build_tech(self):
        if not self.structures(UnitTypeId.PYLON).ready.exists:
            return

        pylon = self.structures(UnitTypeId.PYLON).ready.closest_to(self.game_info.map_center)
        total_gateways = self.gateway_total()
        rush_pressure = self.is_under_early_rush()

        if total_gateways < 1 and self.can_afford(UnitTypeId.GATEWAY):
            await self.build(UnitTypeId.GATEWAY, near=pylon, max_distance=8)
            return

        if (
            (rush_pressure or self.should_prepare_cannon_rush())
            and self.structures(UnitTypeId.GATEWAY).ready.exists
            and not self.structures(UnitTypeId.FORGE).exists
            and not self.already_pending(UnitTypeId.FORGE)
            and self.can_afford(UnitTypeId.FORGE)
        ):
            if await self.build(UnitTypeId.FORGE, near=pylon, max_distance=8):
                if self.should_prepare_cannon_rush():
                    self.cannon_rush_committed = True
            return

        if (
            self.structures(UnitTypeId.GATEWAY).ready.exists
            and not self.structures(UnitTypeId.CYBERNETICSCORE).exists
            and not self.already_pending(UnitTypeId.CYBERNETICSCORE)
            and self.can_afford(UnitTypeId.CYBERNETICSCORE)
        ):
            await self.build(UnitTypeId.CYBERNETICSCORE, near=pylon, max_distance=8)
            return

        if self.townhalls.ready.amount >= 2:
            if (
                self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists
                and not self.structures(UnitTypeId.TWILIGHTCOUNCIL).exists
                and not self.already_pending(UnitTypeId.TWILIGHTCOUNCIL)
                and self.can_afford(UnitTypeId.TWILIGHTCOUNCIL)
            ):
                await self.build(UnitTypeId.TWILIGHTCOUNCIL, near=pylon, max_distance=8)
                return

            if (
                self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists
                and not self.structures(UnitTypeId.ROBOTICSFACILITY).exists
                and not self.already_pending(UnitTypeId.ROBOTICSFACILITY)
                and self.can_afford(UnitTypeId.ROBOTICSFACILITY)
            ):
                await self.build(UnitTypeId.ROBOTICSFACILITY, near=pylon, max_distance=8)
                return

            if (
                self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists
                and not self.structures(UnitTypeId.FORGE).exists
                and not self.already_pending(UnitTypeId.FORGE)
                and self.can_afford(UnitTypeId.FORGE)
            ):
                await self.build(UnitTypeId.FORGE, near=pylon, max_distance=8)
                return

            if total_gateways < 3 and self.can_afford(UnitTypeId.GATEWAY):
                await self.build(UnitTypeId.GATEWAY, near=pylon, max_distance=8)
                return

        extra_gate_target = 6 if self.townhalls.ready.amount < 3 else 8
        if (
            (
                self.already_pending_upgrade(UpgradeId.BLINKTECH) > 0
                or self.townhalls.ready.amount >= 3
            )
            and total_gateways < extra_gate_target
            and self.can_afford(UnitTypeId.GATEWAY)
        ):
            await self.build(UnitTypeId.GATEWAY, near=pylon, max_distance=10)
            return

        if (
            self.townhalls.ready.amount >= 3
            and self.structures(UnitTypeId.ROBOTICSFACILITY).ready.exists
            and not self.structures(UnitTypeId.ROBOTICSBAY).exists
            and not self.already_pending(UnitTypeId.ROBOTICSBAY)
            and self.can_afford(UnitTypeId.ROBOTICSBAY)
        ):
            await self.build(UnitTypeId.ROBOTICSBAY, near=pylon, max_distance=10)

    async def build_static_defense(self):
        if not self.townhalls.ready.exists:
            return

        rush_pressure = self.is_under_early_rush()
        cyber_ready = self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists
        forge_ready = self.structures(UnitTypeId.FORGE).ready.exists
        main = self.main_base()

        for nexus in self.townhalls.ready:
            enemy_units, proxy_structures, pressure = self.local_defensive_pressure(nexus)
            air_threats = self.enemy_air_threats().closer_than(20, nexus)

            needs_static = (
                rush_pressure
                or air_threats.exists
                or proxy_structures.exists
                or (main is not None and nexus.tag != main.tag)
            )
            if not needs_static:
                continue

            local_pylons = self.structures(UnitTypeId.PYLON).ready.closer_than(12, nexus)
            if not local_pylons.exists:
                if (
                    self.already_pending(UnitTypeId.PYLON) == 0
                    and self.can_afford(UnitTypeId.PYLON)
                ):
                    await self.build(
                        UnitTypeId.PYLON,
                        near=nexus.position.towards(self.game_info.map_center, 5),
                        max_distance=6,
                    )
                return

            desired_batteries = 1 if (main is not None and nexus.tag != main.tag) else 0
            desired_cannons = 1 if (main is not None and nexus.tag != main.tag and forge_ready) else 0

            if rush_pressure or proxy_structures.exists or air_threats.exists:
                if main is not None and nexus.tag == main.tag:
                    desired_batteries = max(desired_batteries, 1)
                if forge_ready:
                    desired_cannons = max(desired_cannons, 1)

            if pressure >= 6 or air_threats.amount >= 2:
                desired_batteries = max(desired_batteries, 2)
                if forge_ready:
                    desired_cannons = max(desired_cannons, 2)

            if (
                cyber_ready
                and desired_batteries > 0
                and
                self.structures(UnitTypeId.SHIELDBATTERY).closer_than(10, nexus).amount < desired_batteries
                and self.already_pending(UnitTypeId.SHIELDBATTERY) == 0
                and self.can_afford(UnitTypeId.SHIELDBATTERY)
            ):
                await self.build(
                    UnitTypeId.SHIELDBATTERY,
                    near=local_pylons.closest_to(nexus),
                    max_distance=6,
                )
                return

            if (
                forge_ready
                and desired_cannons > 0
                and self.structures(UnitTypeId.PHOTONCANNON).closer_than(10, nexus).amount < desired_cannons
                and self.already_pending(UnitTypeId.PHOTONCANNON) == 0
                and self.can_afford(UnitTypeId.PHOTONCANNON)
            ):
                await self.build(
                    UnitTypeId.PHOTONCANNON,
                    near=local_pylons.closest_to(nexus),
                    max_distance=6,
                )
                return

    async def research_upgrades(self):
        if (
            self.structures(UnitTypeId.CYBERNETICSCORE).ready.idle.exists
            and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0
            and self.can_afford(UpgradeId.WARPGATERESEARCH)
        ):
            self.structures(UnitTypeId.CYBERNETICSCORE).ready.idle.first.research(
                UpgradeId.WARPGATERESEARCH
            )
            return

        if self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.idle.exists:
            twilight = self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.idle.first
            if (
                self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 1
                and self.already_pending_upgrade(UpgradeId.BLINKTECH) == 0
                and self.can_afford(UpgradeId.BLINKTECH)
            ):
                twilight.research(UpgradeId.BLINKTECH)
                return
            if (
                self.townhalls.ready.amount >= 3
                and self.already_pending_upgrade(UpgradeId.BLINKTECH) == 1
                and self.already_pending_upgrade(UpgradeId.CHARGE) == 0
                and self.can_afford(UpgradeId.CHARGE)
            ):
                twilight.research(UpgradeId.CHARGE)
                return

        if self.structures(UnitTypeId.FORGE).ready.idle.exists:
            forge = self.structures(UnitTypeId.FORGE).ready.idle.first
            if (
                self.already_pending_upgrade(UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1) == 0
                and self.can_afford(UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1)
            ):
                forge.research(UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1)
                return
            if (
                self.townhalls.ready.amount >= 3
                and self.already_pending_upgrade(UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1) == 1
                and self.already_pending_upgrade(UpgradeId.PROTOSSGROUNDWEAPONSLEVEL2) == 0
                and self.can_afford(UpgradeId.PROTOSSGROUNDWEAPONSLEVEL2)
            ):
                forge.research(UpgradeId.PROTOSSGROUNDWEAPONSLEVEL2)
                return

        if (
            self.structures(UnitTypeId.ROBOTICSBAY).ready.idle.exists
            and self.units(UnitTypeId.COLOSSUS).amount > 0
            and self.already_pending_upgrade(UpgradeId.EXTENDEDTHERMALLANCE) == 0
            and self.can_afford(UpgradeId.EXTENDEDTHERMALLANCE)
        ):
            self.structures(UnitTypeId.ROBOTICSBAY).ready.idle.first.research(
                UpgradeId.EXTENDEDTHERMALLANCE
            )

    async def morph_warpgates(self):
        if self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) < 1:
            return

        for gateway in self.structures(UnitTypeId.GATEWAY).ready.idle:
            gateway(AbilityId.MORPH_WARPGATE)

    async def chrono_boost(self):
        nexuses = self.townhalls.ready.filter(lambda nexus: nexus.energy >= 50)
        if not nexuses.exists:
            return

        target = None
        for structure_type in (
            UnitTypeId.CYBERNETICSCORE,
            UnitTypeId.TWILIGHTCOUNCIL,
            UnitTypeId.FORGE,
            UnitTypeId.ROBOTICSFACILITY,
        ):
            for structure in self.structures(structure_type).ready:
                if not structure.is_idle and not structure.has_buff(
                    BuffId.CHRONOBOOSTENERGYCOST
                ):
                    target = structure
                    break
            if target:
                break

        if target is None and self.workers.amount < 44:
            for nexus in self.townhalls.ready:
                if not nexus.is_idle and not nexus.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
                    target = nexus
                    break

        if target is None:
            return

        nexuses.first(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, target)

    async def train_from_gateways(self):
        desired = self.choose_gateway_unit()
        cyber_ready = self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists

        for gateway in self.structures(UnitTypeId.GATEWAY).ready.idle:
            if desired == UnitTypeId.SENTRY:
                if (
                    cyber_ready
                    and self.can_afford(UnitTypeId.SENTRY)
                    and self.supply_left >= 2
                ):
                    gateway.train(UnitTypeId.SENTRY)
                    continue
                desired = UnitTypeId.STALKER

            if desired == UnitTypeId.STALKER:
                if (
                    cyber_ready
                    and self.can_afford(UnitTypeId.STALKER)
                    and self.supply_left >= 2
                ):
                    gateway.train(UnitTypeId.STALKER)
                    continue
                desired = UnitTypeId.ZEALOT

            if self.can_afford(UnitTypeId.ZEALOT) and self.supply_left >= 2:
                gateway.train(UnitTypeId.ZEALOT)

    async def train_from_robos(self):
        if not self.structures(UnitTypeId.ROBOTICSFACILITY).ready.exists:
            return

        for robo in self.structures(UnitTypeId.ROBOTICSFACILITY).ready.idle:
            if (
                self.units(UnitTypeId.OBSERVER).amount
                + self.already_pending(UnitTypeId.OBSERVER)
                < 1
                and self.can_afford(UnitTypeId.OBSERVER)
                and self.supply_left >= 1
            ):
                robo.train(UnitTypeId.OBSERVER)
                continue

            if (
                self.townhalls.ready.amount >= 3
                and self.structures(UnitTypeId.ROBOTICSBAY).ready.exists
                and self.units(UnitTypeId.COLOSSUS).amount
                + self.already_pending(UnitTypeId.COLOSSUS)
                < 2
                and self.can_afford(UnitTypeId.COLOSSUS)
                and self.supply_left >= 6
            ):
                robo.train(UnitTypeId.COLOSSUS)
                continue

            immortal_target = 2 if self.townhalls.ready.amount < 3 else 4
            if (
                self.units(UnitTypeId.IMMORTAL).amount
                + self.already_pending(UnitTypeId.IMMORTAL)
                < immortal_target
                and self.can_afford(UnitTypeId.IMMORTAL)
                and self.supply_left >= 4
            ):
                robo.train(UnitTypeId.IMMORTAL)
                continue

            if (
                self.attack_committed
                and self.units(UnitTypeId.OBSERVER).amount
                + self.already_pending(UnitTypeId.OBSERVER)
                < 2
                and self.can_afford(UnitTypeId.OBSERVER)
                and self.supply_left >= 1
            ):
                robo.train(UnitTypeId.OBSERVER)

    async def build_forward_pylon(self):
        if not self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists:
            return
        if self.already_pending(UnitTypeId.PYLON) > 0 or not self.can_afford(UnitTypeId.PYLON):
            return
        if self.already_pending_upgrade(UpgradeId.BLINKTECH) < 1 and self.army_strength() < 14:
            return
        if not self.townhalls.ready.exists:
            return

        forward_pylons = self.structures(UnitTypeId.PYLON).ready.filter(
            lambda pylon: pylon.distance_to(self.townhalls.ready.center) > 20
        )
        if forward_pylons.exists:
            return

        base_center = self.townhalls.ready.center
        enemy_focus = self.enemy_reference_point()
        distance = min(32, base_center.distance_to(enemy_focus) * 0.55)
        position = base_center.towards(enemy_focus, distance)
        await self.build(UnitTypeId.PYLON, near=position, max_distance=6, placement_step=2)

    async def execute_cannon_rush(self):
        if not (self.should_prepare_cannon_rush() or self.is_cannon_rush_active()):
            return

        scout = self.scout_worker()
        anchor = self.cannon_rush_anchor()
        if scout is None or anchor is None:
            self.cannon_rush_abandoned = True
            return

        local_threats = self.enemy_units.closer_than(8, scout).filter(
            lambda unit: unit.can_attack_ground and unit.type_id not in WORKER_TYPES
        )
        if local_threats.amount >= 2 and scout.shield_health_percentage < 0.5:
            self.cannon_rush_abandoned = True
            scout.move(self.start_location)
            return

        forward_pylons = self.forward_cannon_pylons()
        forward_cannons = self.forward_cannons()

        if not forward_pylons.exists:
            if scout.distance_to(anchor) > 5:
                scout.move(anchor)
                return

            if self.already_pending(UnitTypeId.PYLON) == 0 and self.can_afford(UnitTypeId.PYLON):
                if await self.build(
                    UnitTypeId.PYLON,
                    near=anchor,
                    max_distance=6,
                    build_worker=scout,
                    placement_step=1,
                ):
                    self.cannon_rush_committed = True
            return

        if not self.structures(UnitTypeId.FORGE).ready.exists:
            scout.move(forward_pylons.closest_to(anchor))
            return

        desired_cannons = 1
        if self.time < 180 and scout.shield_health_percentage > 0.6:
            desired_cannons = 2

        if (
            forward_cannons.amount < desired_cannons
            and self.already_pending(UnitTypeId.PHOTONCANNON) == 0
            and self.can_afford(UnitTypeId.PHOTONCANNON)
        ):
            cannon_anchor = forward_pylons.closest_to(anchor).position.towards(
                self.confirmed_enemy_start, 2
            )
            if await self.build(
                UnitTypeId.PHOTONCANNON,
                near=cannon_anchor,
                max_distance=6,
                build_worker=scout,
                placement_step=1,
            ):
                self.cannon_rush_committed = True
            return

        if scout.is_idle:
            scout.move(forward_pylons.closest_to(anchor))
        if self.time > 220 and not forward_cannons.exists:
            self.cannon_rush_abandoned = True

    async def warp_in_units(self):
        warpgates = self.structures(UnitTypeId.WARPGATE).ready
        if not warpgates.exists:
            return

        pylon = self.choose_warp_pylon()
        if pylon is None:
            return

        abilities_list = await self.get_available_abilities(warpgates)
        desired = self.choose_gateway_unit()

        for warpgate, abilities in zip(warpgates, abilities_list):
            if self.supply_left < 2:
                return

            for unit_type in (desired, UnitTypeId.STALKER, UnitTypeId.ZEALOT):
                if unit_type == UnitTypeId.STALKER and not self.structures(
                    UnitTypeId.CYBERNETICSCORE
                ).ready.exists:
                    continue
                if unit_type == UnitTypeId.SENTRY and not self.structures(
                    UnitTypeId.CYBERNETICSCORE
                ).ready.exists:
                    continue

                ability = WARP_IN_ABILITIES.get(unit_type)
                if ability not in abilities or not self.can_afford(unit_type):
                    continue

                position = pylon.position.random_on_distance(4)
                placement = await self.find_placement(
                    ability, position, placement_step=1
                )
                if placement is None:
                    continue

                warpgate.warp_in(unit_type, placement)
                break

    async def scout_with_probe(self):
        if self.time < 45 or self.workers.amount < 16:
            return
        if self.units(UnitTypeId.OBSERVER).ready.exists and not self.is_cannon_rush_active():
            return

        scout = self.scout_worker()
        if self.scout_worker_tag is not None and scout is None:
            self.scout_worker_tag = None

        if scout is None:
            worker_pool = self.workers.gathering if self.workers.gathering.exists else self.workers
            if not worker_pool.exists:
                return
            scout = worker_pool.furthest_to(self.start_location)
            self.scout_worker_tag = scout.tag

        hostile_threats = self.enemy_units.closer_than(9, scout).filter(
            lambda unit: unit.can_attack_ground and unit.type_id not in WORKER_TYPES
        )
        if hostile_threats.exists and scout.shield_health_percentage < 0.45:
            scout.move(self.start_location)
            self.scout_worker_tag = None
            self.cannon_rush_abandoned = True
            return

        if self.confirmed_enemy_start is not None:
            if self.should_prepare_cannon_rush() or self.is_cannon_rush_active():
                anchor = self.cannon_rush_anchor()
                if anchor is not None and (scout.is_idle or scout.distance_to(anchor) > 6):
                    scout.move(anchor)
            return

        scout_target = self.next_scout_point()
        if scout.is_idle or scout.distance_to(scout_target) > 6:
            scout.move(scout_target)

    async def control_observers(self):
        observers = self.units(UnitTypeId.OBSERVER).ready.idle
        if not observers.exists:
            return

        targets = self.combat_targets()
        for observer in observers:
            if self.confirmed_enemy_start is None:
                observer.move(self.next_scout_point())
                continue
            if self.army.exists and targets.exists:
                observer.move(self.army.center.towards(targets.closest_to(self.army.center), 6))
            elif self.attack_committed or self.opening_pressure_committed:
                observer.move(self.enemy_reference_point().towards(self.game_info.map_center, 8))
            else:
                observer.move(self.game_info.map_center)

    async def micro_stalkers(self, destination: Point2, enemies):
        stalkers = self.units(UnitTypeId.STALKER).ready
        if not stalkers.exists:
            return

        blink_ready = self.already_pending_upgrade(UpgradeId.BLINKTECH) == 1
        abilities_list = (
            await self.get_available_abilities(stalkers)
            if blink_ready
            else [[] for _ in stalkers]
        )
        fallback = self.fallback_point()

        for stalker, abilities in zip(stalkers, abilities_list):
            nearby = enemies.closer_than(10 + max(stalker.ground_range, stalker.air_range), stalker)
            if nearby.exists:
                target = self.pick_combat_target(stalker, nearby)
                if target is None:
                    stalker.attack(destination)
                    continue

                low_shield = stalker.shield_health_percentage < 0.35
                if low_shield and AbilityId.EFFECT_BLINK_STALKER in abilities:
                    blink_position = stalker.position.towards(fallback, 8)
                    stalker(AbilityId.EFFECT_BLINK_STALKER, blink_position)
                    continue

                if low_shield and not stalker.weapon_ready and stalker.target_in_range(target):
                    stalker.move(stalker.position.towards(fallback, 2))
                    continue

                stalker.attack(target)
                continue

            if stalker.is_idle or stalker.distance_to(destination) > 6:
                stalker.attack(destination)

    async def control_army(self):
        army = self.army.ready
        if not army.exists or not self.townhalls.ready.exists:
            return

        targets = self.combat_targets()
        defense_targets = targets.filter(
            lambda enemy: any(nexus.distance_to(enemy) < 25 for nexus in self.townhalls.ready)
        )

        if defense_targets.exists:
            self.attack_committed = False
            self.opening_pressure_committed = False
            destination = defense_targets.closest_to(self.townhalls.ready.center)
        else:
            if (
                not self.attack_committed
                and not self.opening_pressure_committed
                and self.should_opening_pressure()
            ):
                self.opening_pressure_committed = True

            if (
                self.opening_pressure_committed
                and (
                    self.is_under_early_rush()
                    or self.time > 420
                    or self.army_strength() < 6
                )
            ):
                self.opening_pressure_committed = False

            if not self.attack_committed and self.should_attack():
                self.attack_committed = True
            if self.attack_committed and self.army_strength() < 10:
                self.attack_committed = False

            if self.attack_committed:
                self.opening_pressure_committed = False
                destination = (
                    targets.closest_to(army.center) if targets.exists else self.enemy_reference_point()
                )
            elif self.opening_pressure_committed:
                destination = (
                    targets.closest_to(army.center) if targets.exists else self.opening_pressure_point()
                )
            else:
                destination = self.gather_point()

        enemies = defense_targets if defense_targets.exists else targets
        await self.micro_stalkers(destination, enemies)

        for unit in self.units.of_type(
            {
                UnitTypeId.ZEALOT,
                UnitTypeId.SENTRY,
                UnitTypeId.IMMORTAL,
                UnitTypeId.COLOSSUS,
            }
        ).ready:
            if enemies.exists:
                search_range = 12 if max(unit.ground_range, unit.air_range) > 1 else 4
                nearby = enemies.closer_than(search_range, unit)
                if nearby.exists:
                    target = self.pick_combat_target(unit, nearby)
                    if target is not None:
                        unit.attack(target)
                        continue

            if unit.is_idle or unit.distance_to(destination) > 6:
                unit.attack(destination)


def main():
    parser = argparse.ArgumentParser(description="SC2 Protoss AI Bot")
    parser.add_argument(
        "--difficulty",
        type=str,
        default="medium",
        choices=list(DIFFICULTY_MAP.keys()),
        help="Computer difficulty",
    )
    parser.add_argument(
        "--race",
        type=str,
        default="protoss",
        choices=["protoss", "terran", "zerg", "random"],
        help="Enemy race",
    )
    parser.add_argument(
        "--map",
        type=str,
        default="AcropolisLE",
        help="Map name",
    )
    parser.add_argument(
        "--save-replay",
        action="store_true",
        help="Save replay after game",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Run in real-time (slower)",
    )

    args = parser.parse_args()

    enemy_race = {
        "protoss": Race.Protoss,
        "terran": Race.Terran,
        "zerg": Race.Zerg,
        "random": Race.Random,
    }

    result = run_game(
        maps.get(args.map),
        [
            Bot(Race.Protoss, ProtossBot()),
            Computer(
                enemy_race.get(args.race, Race.Random),
                DIFFICULTY_MAP[args.difficulty],
            ),
        ],
        realtime=args.realtime,
        save_replay_as="replay.SC2Replay" if args.save_replay else None,
    )
    print(f"Game result: {result}")


if __name__ == "__main__":
    main()
