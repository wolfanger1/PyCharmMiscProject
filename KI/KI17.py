import random
import math
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData, GeomNode,
    GeomVertexWriter, GeomLines, Geom, Vec3, ClockObject, TextNode
)

# Wir nutzen globalClock für dt
globalClock = ClockObject.getGlobalClock()

from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Basisgeschwindigkeit bleibt konstant: 1.5 m/s.
        self.base_speed = 1.5
        # Der Multiplikator (speed_factor) steuert den Zeitskalierungsfaktor.
        # Startwert 1.0 => normale Simulation.
        self.speed_factor = 1.0

        # Eigener Simulationszeitticker (in simulierten Sekunden)
        self.sim_clock = 0.0
        # Zähler der abgegebenen Pakete
        self.delivered_packages = 0

        # Zeitpunkt des Simulationsstart (reale Zeit)
        self.sim_start_real = globalClock.getFrameTime()

        self.cam.setPos(0, -60, 30)
        self.cam.lookAt(0, 0, 0)

        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=40, cell_size=1)

        # Erzeuge 5 Annahme- (rot) und 5 Abgabe-Stationen (grün) in einer Linie.
        station_count = 5
        spacing = 5
        y_start = -((station_count - 1) * spacing) / 2
        self.annahme_stationen = []
        self.abgabe_stationen = []
        for i in range(station_count):
            y = y_start + i * spacing
            pickup_station = self.erzeuge_gitterbox(-9, y, 0, LColor(1, 0, 0, 1))
            self.annahme_stationen.append(pickup_station)
            dropoff_station = self.erzeuge_gitterbox(9, y, 0, LColor(0, 1, 0, 1))
            self.abgabe_stationen.append(dropoff_station)

        # Fahrzeuge initialisieren – zwei Fahrzeuge.
        self.vehicles = []
        self.cargos = {}  # Fahrzeug -> aktuell transportiertes Paket
        self.current_dropoffs = {}  # Fahrzeug -> aktuell reservierte Abgabestation

        # Fahrzeug 1: startet sofort
        vehicle1 = self.loader.loadModel("models/box")
        vehicle1.setScale(1, 1, 0.5)
        vehicle1.setColor(LColor(0, 0, 1, 1))
        vehicle1.setPos(0, 0, 0)
        vehicle1.reparentTo(self.render)
        self.vehicles.append(vehicle1)

        # Fahrzeug 2: startet 8 simulierte Sekunden später
        vehicle2 = self.loader.loadModel("models/box")
        vehicle2.setScale(1, 1, 0.5)
        vehicle2.setColor(LColor(0, 0, 0.8, 1))
        vehicle2.setPos(0, 2, 0)  # y-Offset von 2 Einheiten
        vehicle2.reparentTo(self.render)
        self.vehicles.append(vehicle2)

        # Globaler Pool für Pickup-Pakete und Zeitstempel (in simulierten Sekunden)
        self.pickup_packages = {}
        self.last_removed = {}
        for station in self.annahme_stationen:
            self.last_removed[station] = self.sim_clock

        self.occupied_dropoffs = set()
        self.occupied_pickups = set()

        # Slider zur Anpassung des Multiplikators (Zeitskalierung)
        # Wertebereich: 0.1 bis 10, Startwert: 1.0
        self.speed_slider = DirectSlider(
            range=(0.1, 10.0),
            value=self.speed_factor,
            pageSize=0.1,
            command=self.update_simulation_speed,
            pos=(0, 0, -0.85),
            scale=0.3
        )
        self.speed_label = DirectLabel(
            text=f"Sim Time Factor: {self.speed_factor:.1f}",
            pos=(0, 0, -0.75),
            scale=0.07
        )

        # Info-Anzeige rechts: Laufzeit der Simulation, Summe abgegebener Pakete,
        # Pakete pro Minute und Kennzahl des am längsten wartenden Pakets
        self.info_label = DirectLabel(
            text="Laufzeit: 0.0 s\nAbgegebene Pakete: 0",
            pos=(1.2, 0, 0.8),
            scale=0.07,
            frameColor=(0, 0, 0, 0)
        )

        # Tasks:
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.doMethodLater(1, self.check_slider_task, "CheckSliderTask")
        self.taskMgr.add(self.check_and_spawn_packages, "CheckSpawnPackages")
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimers")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
        self.taskMgr.add(self.check_vehicle2_start, "CheckVehicle2StartTask")

        # Fahrzeug 1 startet den Liefervorgang sofort
        self.start_delivery_cycle(self.vehicles[0], self.vehicles[0].getPos())
        # Fahrzeug 2 startet, sobald 8 simulierte Sekunden erreicht sind (über Task)

    def update_sim_clock(self, task):
        dt = globalClock.getDt()
        # Erhöhe die interne Simulationszeit um dt * speed_factor.
        # Höherer Faktor => Simulation läuft schneller (mehr simulierte Sekunden pro realer Sekunde)
        self.sim_clock += dt * self.speed_factor
        return Task.cont

    def update_info_display(self, task):
        max_wait_time = 0
        max_wait_package = None

        # Berechne die maximale Wartezeit aller Pakete an den Annahmestationen
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_clock - spawn_time
            if elapsed > max_wait_time:
                max_wait_time = elapsed
                max_wait_package = package

        if max_wait_package:
            max_wait_text = f"Paket mit höchster Wartezeit: {max_wait_time:.1f}s"
        else:
            max_wait_text = "Kein Paket an Annahmestation"

        # Berechne die abgegebenen Pakete pro Minute (basierend auf der simulierten Zeit)
        if self.sim_clock > 0:
            delivered_per_minute = self.delivered_packages / (self.sim_clock / 60.0)
        else:
            delivered_per_minute = 0

        self.info_label['text'] = (f"Laufzeit: {self.sim_clock:.1f} s\n"
                                   f"Abgegebene Pakete: {self.delivered_packages}\n"
                                   f"Pakete pro Minute: {delivered_per_minute:.1f}\n"
                                   f"{max_wait_text}")
        return Task.cont

    def sim_time(self, t):
        """
        Skalierung eines Basiszeitwerts t (in Sekunden) anhand des Multiplikators.
        Wir verwenden hier die Formel: t / speed_factor.
        Dadurch wird bei einem kleineren Faktor (z. B. 0.1) t größer (Simulation wird verlangsamt),
        und bei einem höheren Faktor (z. B. 10) t kleiner (Simulation beschleunigt).
        """
        return t / self.speed_factor if self.speed_factor else t

    def check_slider_task(self, task):
        self.update_simulation_speed()
        return Task.again

    def check_vehicle2_start(self, task):
        """
        Überprüft kontinuierlich, ob 8 simulierte Sekunden vergangen sind.
        Sobald self.sim_clock >= 8, wird Fahrzeug 2 gestartet.
        """
        if self.sim_clock >= 8.0 and not hasattr(self, 'vehicle2_started'):
            self.vehicle2_started = True
            self.start_delivery_cycle(self.vehicles[1], self.vehicles[1].getPos())
            return Task.done
        return Task.cont

    def update_simulation_speed(self, speed_factor=None):
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

    def check_and_spawn_packages(self, task):
        # Basiswartezeit von 1 simulierten Sekunde:
        spawn_delay = self.sim_time(1)
        for station in self.annahme_stationen:
            if station not in self.pickup_packages:
                if (self.sim_clock - self.last_removed.get(station, self.sim_clock)) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.cont

    def spawn_package_at_station(self, station):
        package = self.erzeuge_wuerfel(station.getX(), station.getY(), station.getZ(), LColor(1, 1, 0, 1))
        spawn_time = self.sim_clock
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)
        self.pickup_packages[station] = (package, spawn_time, timer_np)

    def update_package_timers(self, task):
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_clock - spawn_time
            tn = timer_np.node()
            tn.setText(f"{elapsed:.1f}s")
        return Task.cont

    def move_vehicle_to(self, vehicle, target, on_complete):
        def move_task(task):
            dt = globalClock.getDt()
            current_pos = vehicle.getPos()
            direction = target - current_pos
            distance = direction.length()
            # Effektiver Schritt = (base_speed * speed_factor) * dt.
            # Höherer Multiplikator => Fahrzeuge bewegen sich in realer Zeit schneller.
            step = (self.base_speed * self.speed_factor) * dt
            if distance <= step:
                vehicle.setPos(target)
                on_complete()
                return Task.done
            else:
                vehicle.setPos(current_pos + direction.normalized() * step)
                return Task.cont

        self.taskMgr.add(move_task, f"move_vehicle_{id(vehicle)}_{target}")

    def start_delivery_cycle(self, vehicle, start_pos=None):
        if start_pos is None:
            start_pos = vehicle.getPos()
        if not self.pickup_packages:
            def wait_task(task):
                if self.pickup_packages:
                    self.start_delivery_cycle(vehicle, vehicle.getPos())
                    return Task.done
                return Task.cont

            self.taskMgr.add(wait_task, f"WaitPackage_{id(vehicle)}")
            return
        current_time = self.sim_clock
        available_pickups = [s for s in self.pickup_packages.keys() if s not in self.occupied_pickups]
        if not available_pickups:
            def wait_for_pickup(task):
                if any(s not in self.occupied_pickups for s in self.pickup_packages.keys()):
                    self.start_delivery_cycle(vehicle, vehicle.getPos())
                    return Task.done
                return Task.cont

            self.taskMgr.add(wait_for_pickup, f"WaitPickup_{id(vehicle)}")
            return
        pickup_station = max(available_pickups, key=lambda s: current_time - self.pickup_packages[s][1])
        self.occupied_pickups.add(pickup_station)
        pickup_pos = pickup_station.getPos()

        available_dropoffs = [ds for ds in self.abgabe_stationen if ds not in self.occupied_dropoffs]
        if not available_dropoffs:
            self.occupied_pickups.remove(pickup_station)

            def wait_for_dropoff(task):
                if any(ds not in self.occupied_dropoffs for ds in self.abgabe_stationen):
                    self.start_delivery_cycle(vehicle, vehicle.getPos())
                    return Task.done
                return Task.cont

            self.taskMgr.add(wait_for_dropoff, f"WaitDropoff_{id(vehicle)}")
            return

        dropoff_station = random.choice(available_dropoffs)
        self.occupied_dropoffs.add(dropoff_station)
        self.current_dropoffs[vehicle] = dropoff_station
        dropoff_pos = dropoff_station.getPos()

        self.move_vehicle_to(vehicle, pickup_pos, lambda: self.after_pickup(vehicle, pickup_station, dropoff_pos))

    def after_pickup(self, vehicle, pickup_station, dropoff_pos):
        self.pickup_package(vehicle, pickup_station)
        self.move_vehicle_to(vehicle, dropoff_pos, lambda: self.after_dropoff(vehicle))

    def after_dropoff(self, vehicle):
        self.drop_cargo(vehicle)
        start_wait = self.sim_clock

        def wait_task(task):
            if self.sim_clock - start_wait >= self.sim_time(1):
                self.finish_cycle(vehicle)
                return Task.done
            return Task.cont

        self.taskMgr.add(wait_task, f"WaitAfterDrop_{id(vehicle)}")

    def finish_cycle(self, vehicle):
        self.remove_cargo(vehicle)
        self.start_delivery_cycle(vehicle, vehicle.getPos())

    def pickup_package(self, vehicle, station):
        if station in self.pickup_packages:
            package, spawn_time, timer_np = self.pickup_packages.pop(station)
            timer_np.removeNode()
            package.wrtReparentTo(vehicle)
            package.setPos(0, 0, 1)
            self.cargos[vehicle] = package
            self.last_removed[station] = self.sim_clock
            if station in self.occupied_pickups:
                self.occupied_pickups.remove(station)

    def drop_cargo(self, vehicle):
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.wrtReparentTo(self.render)
            targetPos = self.current_dropoffs[vehicle].getPos() + Vec3(0, 0, 1)
            cargo.setPos(targetPos)
            self.delivered_packages += 1

    def remove_cargo(self, vehicle):
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.removeNode()
            self.cargos[vehicle] = None
        dropoff_station = self.current_dropoffs.get(vehicle)
        if dropoff_station in self.occupied_dropoffs:
            self.occupied_dropoffs.remove(dropoff_station)
            del self.current_dropoffs[vehicle]

    def erzeuge_bodenraster(self, center_extent=40, cell_size=1):
        vertex_format = GeomVertexFormat.getV3()
        vdata = GeomVertexData("grid", vertex_format, Geom.UHStatic)
        writer = GeomVertexWriter(vdata, "vertex")
        lines = GeomLines(Geom.UHStatic)
        n_vertices = 0
        min_line, max_line = -center_extent - 0.5, center_extent + 0.5
        y = min_line
        while y <= max_line:
            writer.addData3(min_line, y, 0)
            writer.addData3(max_line, y, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            y += cell_size
        x = min_line
        while x <= max_line:
            writer.addData3(x, min_line, 0)
            writer.addData3(x, max_line, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            x += cell_size
        lines.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(lines)
        node = GeomNode("grid")
        node.addGeom(geom)
        np_grid = self.render.attachNewNode(node)
        np_grid.setColor(0.7, 0.7, 0.7, 1)
        return np_grid

    def erzeuge_gitterbox(self, x, y, z, farbe):
        gitterbox = self.loader.loadModel("models/box")
        gitterbox.setScale(1, 1, 1)
        gitterbox.setPos(x, y, z)
        gitterbox.setColor(farbe)
        gitterbox.setRenderMode(RenderModeAttrib.MWireframe, 1)
        gitterbox.reparentTo(self.render)
        return gitterbox

    def erzeuge_wuerfel(self, x, y, z, farbe):
        wuerfel = self.loader.loadModel("models/box")
        wuerfel.setScale(1, 1, 1)
        wuerfel.setPos(x, y, z + 1)
        wuerfel.setColor(farbe)
        wuerfel.reparentTo(self.render)
        return wuerfel

    def erzeuge_licht(self):
        alight = AmbientLight("ambient_light")
        alight.setColor((0.5, 0.5, 0.5, 1))
        self.render.setLight(self.render.attachNewNode(alight))
        dlight = DirectionalLight("directional_light")
        dlight.setColor((1, 1, 1, 1))
        dlightNP = self.render.attachNewNode(dlight)
        dlightNP.setPos(10, -10, 10)
        self.render.setLight(dlightNP)


app = LagerSimulation()
app.run()
