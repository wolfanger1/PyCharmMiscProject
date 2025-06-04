import random
import math
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData, GeomNode,
    GeomVertexWriter, GeomLines, Geom, Vec3, ClockObject, TextNode
)

# Wir nutzen weiterhin globalClock für dt, aber nicht für die Zeitmessung in der Simulation.
globalClock = ClockObject.getGlobalClock()

from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Die Basisgeschwindigkeit ändert sich nicht: 1.5 m/s.
        self.base_speed = 1.5
        # Der Multiplikator (speed_factor) regelt ausschließlich den Zeitablauf.
        # Startwert 1.0 entspricht normaler Simulation.
        self.speed_factor = 1.0
        # Wir definieren keinen "effektiven" Speed direkt – die physikalische Bewegung
        # wird in move_vehicle_to frame-by-frame dynamisch berechnet.

        # Eigene Simulationstime (in sim-Sekunden) – startet bei 0
        self.sim_time = 0.0

        # Speichere außerdem den Zeitpunkt, zu dem die Simulation (real) gestartet wurde,
        # um z. B. den Start von Fahrzeug 2 relativ zur Simulation zu steuern.
        self.sim_start_real = globalClock.getFrameTime()

        self.cam.setPos(0, -60, 30)
        self.cam.lookAt(0, 0, 0)

        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=40, cell_size=1)

        # Erzeuge 5 Annahme-(rot) und 5 Abgabe-Stationen (grün) in einer Linie.
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

        # Fahrzeug 2: startet später (genauer: 8 simulierte Sekunden später)
        vehicle2 = self.loader.loadModel("models/box")
        vehicle2.setScale(1, 1, 0.5)
        vehicle2.setColor(LColor(0, 0, 0.8, 1))
        vehicle2.setPos(0, 2, 0)
        vehicle2.reparentTo(self.render)
        self.vehicles.append(vehicle2)

        # Globaler Pool für Pickup-Pakete: Wir speichern den Zeitpunkt (sim_time) des Spawns.
        self.pickup_packages = {}
        self.last_removed = {}
        for station in self.annahme_stationen:
            self.last_removed[station] = self.sim_time

        # Reservierungssets für Stationen:
        self.occupied_dropoffs = set()
        self.occupied_pickups = set()

        # Slider zur Anpassung des Multiplikators (nur für Zeiten!):
        # Wertebereich: 0.1 bis 10.0, Startwert: 1.0.
        self.speed_slider = DirectSlider(
            range=(0.1, 10.0),
            value=self.speed_factor,
            pageSize=0.1,
            command=self.update_simulation_speed,
            pos=(0, 0, -0.85),
            scale=0.3
        )
        # Das Label gibt den aktuellen Multiplikator und die „effektiven“ Parameter aus.
        # In unserem Fall bleibt die Basisgeschwindigkeit konstant – nur die Zeitparameter (Wartezeiten)
        # werden skaliert.
        self.speed_label = DirectLabel(
            text=f"Sim Time Factor: {self.speed_factor:.1f}",
            pos=(0, 0, -0.75),
            scale=0.07
        )

        # Starte einen Task, der den eigenen Simulationstime (self.sim_time) frame-by-frame aktualisiert.
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")

        # Tasks, die kontinuierlich agieren, nutzen nun self.sim_time.
        self.taskMgr.add(self.check_and_spawn_packages, "CheckSpawnPackages")
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimers")
        self.taskMgr.doMethodLater(1, self.check_slider_task, "CheckSliderTask")
        self.taskMgr.add(self.check_vehicle2_start, "CheckVehicle2StartTask")

        # Fahrzeug 1 startet den Liefervorgang sofort.
        self.start_delivery_cycle(self.vehicles[0], self.vehicles[0].getPos())
        # Fahrzeug 2 wird über den Task gestartet, sobald 8 simulierte Sekunden vergangen sind.

    def update_sim_clock(self, task):
        """
        Aktualisiert in jedem Frame die Simulationstime (self.sim_time).
        Diese wird um (dt * speed_factor) erhöht – so läuft die Simulation
        beim Erhöhen des Faktors schneller (alle Zeiten verkürzen sich in Realzeit).
        """
        dt = globalClock.getDt()
        self.sim_time += dt * self.speed_factor
        return Task.cont

    def check_slider_task(self, task):
        """
        Liest einmal pro Echtsekunde den Slider aus und aktualisiert so den Multiplikator.
        Bereits laufende Tasks nutzen den aktuellen self.sim_time, sodass die Simulation
        insgesamt beschleunigt oder verlangsamt wird.
        """
        self.update_simulation_speed()
        return Task.again

    def check_vehicle2_start(self, task):
        """
        Überprüft laufend, ob 8 simulierte Sekunden seit Start der Simulation vergangen sind.
        Sobald das der Fall ist, wird Fahrzeug 2 gestartet (falls es noch nicht gestartet wurde).
        """
        if (self.sim_time - 0) >= 8.0 and not hasattr(self, 'vehicle2_started'):
            self.vehicle2_started = True
            self.start_delivery_cycle(self.vehicles[1], self.vehicles[1].getPos())
            return Task.done
        return Task.cont

    def update_simulation_speed(self, speed_factor=None):
        """
        Wird aufgerufen, wenn der Slider bewegt wird.
        Der Multiplikator (speed_factor) wird aktualisiert – dabei werden
        keine anderen berechneten Werte direkt modifiziert, sondern nur die Zeitabläufe (über self.sim_time).
        """
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

    def check_and_spawn_packages(self, task):
        """
        Überprüft kontinuierlich die Annahmestationen.
        Wenn an einer Station kein Paket vorhanden ist und
        (self.sim_time - last_removed) >= 1 (Basiswartezeit),
        wird ein neues Paket erzeugt.
        """
        spawn_delay = 1  # 1 simulierte Sekunde
        for station in self.annahme_stationen:
            if station not in self.pickup_packages:
                if (self.sim_time - self.last_removed.get(station, self.sim_time)) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.cont

    def spawn_package_at_station(self, station):
        """
        Erzeugt an der angegebenen Annahmestation ein Paket (als Würfel),
        setzt seinen Spawnzeitpunkt (self.sim_time) und hängt einen Timer-Text an.
        """
        package = self.erzeuge_wuerfel(station.getX(), station.getY(), station.getZ(), LColor(1, 1, 0, 1))
        spawn_time = self.sim_time
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)
        self.pickup_packages[station] = (package, spawn_time, timer_np)

    def update_package_timers(self, task):
        """
        Aktualisiert in jedem Frame den angezeigten Timer der Pakete.
        Es wird die simulierte verstrichene Zeit berechnet:
            elapsed = self.sim_time - spawn_time.
        """
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_time - spawn_time
            tn = timer_np.node()
            tn.setText(f"{elapsed:.1f}s")
        return Task.cont

    def move_vehicle_to(self, vehicle, target, on_complete):
        """
        Bewegt das Fahrzeug frame-by-frame dynamisch zum Ziel.
        Dabei wird in jedem Frame der Schritt berechnet als:
          step = (base_speed * speed_factor) * dt.
        Dadurch werden Änderungen am Regler (speed_factor) sofort wirksam.
        """

        def move_task(task):
            dt = globalClock.getDt()
            current_pos = vehicle.getPos()
            direction = target - current_pos
            distance = direction.length()
            # Effektive Geschwindigkeit = base_speed * speed_factor
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
        """
        Führt für ein Fahrzeug den Liefervorgang aus:
          1. Wählt (aus dem globalen Pool) das Paket mit der höchsten simulierten Wartezeit,
             sofern dessen Pickup-Station verfügbar ist.
          2. Reserviert die Pickup-Station und bewegt das Fahrzeug (mit move_vehicle_to) dorthin.
          3. Anschließend wählt es zufällig eine freie Dropoff-Station, reserviert sie und fährt dorthin.
          4. Sobald das Fahrzeug dort ist, wird nach einer Wartezeit von 1 simulierten Sekunde das Paket abgesetzt.
          5. Danach startet der nächste Zyklus.
        """
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

        current_time = self.sim_time
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

        # Starte die Bewegung zur Pickup-Station.
        self.move_vehicle_to(vehicle, pickup_pos, lambda: self.after_pickup(vehicle, pickup_station, dropoff_pos))

    def after_pickup(self, vehicle, pickup_station, dropoff_pos):
        """
        Wird aufgerufen, sobald das Fahrzeug die Pickup-Station erreicht hat.
        Das Paket wird übernommen, anschließend bewegt sich das Fahrzeug zur Dropoff-Station.
        """
        self.pickup_package(vehicle, pickup_station)
        self.move_vehicle_to(vehicle, dropoff_pos, lambda: self.after_dropoff(vehicle))

    def after_dropoff(self, vehicle):
        """
        Nachdem das Fahrzeug die Dropoff-Station erreicht hat, wird das Paket abgesetzt.
        Nach einer Wartezeit von 1 simulierten Sekunde wird der aktuelle Vorgang abgeschlossen.
        """
        self.drop_cargo(vehicle)
        start_wait = self.sim_time

        def wait_task(task):
            if self.sim_time - start_wait >= 1:
                self.finish_cycle(vehicle)
                return Task.done
            return Task.cont

        self.taskMgr.add(wait_task, f"WaitAfterDrop_{id(vehicle)}")

    def finish_cycle(self, vehicle):
        """
        Entfernt das transportierte Paket und startet den nächsten Liefervorgang für das Fahrzeug.
        """
        self.remove_cargo(vehicle)
        self.start_delivery_cycle(vehicle, vehicle.getPos())

    def pickup_package(self, vehicle, station):
        """
        Das Fahrzeug übernimmt an der angegebenen Pickup-Station das Paket.
        Dabei wird der zugehörige Timer entfernt, der Eintrag gelöscht, und die Reservierung aufgehoben.
        """
        if station in self.pickup_packages:
            package, spawn_time, timer_np = self.pickup_packages.pop(station)
            timer_np.removeNode()
            package.wrtReparentTo(vehicle)
            package.setPos(0, 0, 1)
            self.cargos[vehicle] = package
            self.last_removed[station] = self.sim_time
            if station in self.occupied_pickups:
                self.occupied_pickups.remove(station)

    def drop_cargo(self, vehicle):
        """
        Das vom Fahrzeug transportierte Paket wird an der Dropoff-Station (Z+1) abgesetzt.
        """
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.wrtReparentTo(self.render)
            targetPos = self.current_dropoffs[vehicle].getPos() + Vec3(0, 0, 1)
            cargo.setPos(targetPos)

    def remove_cargo(self, vehicle):
        """
        Entfernt das aktuell transportierte Paket und gibt die Dropoff-Reservierung frei.
        """
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.removeNode()
            self.cargos[vehicle] = None
        dropoff_station = self.current_dropoffs.get(vehicle)
        if dropoff_station in self.occupied_dropoffs:
            self.occupied_dropoffs.remove(dropoff_station)
            del self.current_dropoffs[vehicle]

    def erzeuge_bodenraster(self, center_extent=40, cell_size=1):
        """
        Erzeugt ein Bodenraster als Referenz.
        """
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
        """
        Erzeugt ein Wireframe-Box-Modell als Station.
        """
        gitterbox = self.loader.loadModel("models/box")
        gitterbox.setScale(1, 1, 1)
        gitterbox.setPos(x, y, z)
        gitterbox.setColor(farbe)
        gitterbox.setRenderMode(RenderModeAttrib.MWireframe, 1)
        gitterbox.reparentTo(self.render)
        return gitterbox

    def erzeuge_wuerfel(self, x, y, z, farbe):
        """
        Erzeugt einen Würfel (als Paket), der etwas über dem Boden platziert wird.
        """
        wuerfel = self.loader.loadModel("models/box")
        wuerfel.setScale(1, 1, 1)
        wuerfel.setPos(x, y, z + 1)
        wuerfel.setColor(farbe)
        wuerfel.reparentTo(self.render)
        return wuerfel

    def erzeuge_licht(self):
        """
        Einfache Beleuchtung mittels Ambient- und Richtungslicht.
        """
        alight = AmbientLight("ambient_light")
        alight.setColor((0.5, 0.5, 0.5, 1))
        self.render.setLight(self.render.attachNewNode(alight))
        dlight = DirectionalLight("directional_light")
        dlight.setColor((1, 1, 1, 1))
        dlightNP = self.render.attachNewNode(dlight)
        dlightNP.setPos(10, -10, 10)
        self.render.setLight(dlightNP)


# Starte die Simulation
app = LagerSimulation()
app.run()
