import random
import math
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData, GeomNode,
    GeomVertexWriter, GeomLines, Geom, Vec3, ClockObject, TextNode
)

# Globaler Clock
globalClock = ClockObject.getGlobalClock()

from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Basisgeschwindigkeit (1.5 m/s) und initialer Faktor 1.0,
        # also normale Simulationsgeschwindigkeit.
        self.base_speed = 1.5
        self.speed_factor = 1.0
        self.speed = self.base_speed * self.speed_factor

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

        # Fahrzeuge initialisieren (zwei Fahrzeuge)
        self.vehicles = []
        self.cargos = {}  # Fahrzeug -> aktuell transportiertes Paket
        self.current_dropoffs = {}  # Fahrzeug -> aktuell reservierte Abgabestation

        # Fahrzeug 1 startet sofort:
        vehicle1 = self.loader.loadModel("models/box")
        vehicle1.setScale(1, 1, 0.5)
        vehicle1.setColor(LColor(0, 0, 1, 1))
        vehicle1.setPos(0, 0, 0)
        vehicle1.reparentTo(self.render)
        self.vehicles.append(vehicle1)

        # Fahrzeug 2 startet 8 Sekunden später:
        vehicle2 = self.loader.loadModel("models/box")
        vehicle2.setScale(1, 1, 0.5)
        vehicle2.setColor(LColor(0, 0, 0.8, 1))
        vehicle2.setPos(0, 2, 0)
        vehicle2.reparentTo(self.render)
        self.vehicles.append(vehicle2)

        # Globaler Pool für Pickup-Pakete:
        self.pickup_packages = {}
        self.last_removed = {}
        for station in self.annahme_stationen:
            self.last_removed[station] = globalClock.getFrameTime()

        # Reservierungssets:
        self.occupied_dropoffs = set()
        self.occupied_pickups = set()

        # Slider zur Anpassung des Geschwindigkeitsfaktors:
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
            text=f"Sim Speed: {self.speed_factor:.1f} (eff: {self.speed:.1f} m/s)",
            pos=(0, 0, -0.75),
            scale=0.07
        )
        # Task, der den Sliderwert einmal pro Echtsekunde abfragt
        self.taskMgr.doMethodLater(1, self.check_slider_task, "CheckSliderTask")

        # Alle zeitbasierten Tasks nutzen sim_time zur Anpassung
        self.taskMgr.doMethodLater(self.sim_time(1), self.check_and_spawn_packages, "CheckSpawnPackages")
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimers")

        # Start der Lieferzyklen: Fahrzeug 1 sofort, Fahrzeug 2 nach sim_time(8) Sekunden
        self.start_delivery_cycle(self.vehicles[0], self.vehicles[0].getPos())
        self.taskMgr.doMethodLater(self.sim_time(8), lambda t, veh=self.vehicles[1]:
        self.start_delivery_cycle(veh, veh.getPos()),
                                   "StartVehicle2")

    def sim_time(self, t):
        """
        Gibt den skalierten Zeitwert zurück. Dabei wird die Eingabezeit t (in Sekunden)
        durch den aktuellen Geschwindigkeitsfaktor geteilt.
        Dadurch laufen Prozesse z. B. t/speed_factor Sekunden in Echtzeit.
        """
        return t / self.speed_factor if self.speed_factor else t

    def check_slider_task(self, task):
        """
        Diese Funktion wird einmal pro Echtsekunde aufgerufen, um den Sliderwert abzufragen
        und damit alle zeitbasierten Abläufe in Echtzeit anzupassen.
        """
        self.update_simulation_speed()
        return Task.again

    def update_simulation_speed(self, speed_factor=None):
        """
        Aktualisiert den Geschwindigkeitsfaktor, berechnet die effektive Fahrzeuggeschwindigkeit
        und passt das zugehörige Label an.
        """
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed = self.base_speed * self.speed_factor
        self.speed_label['text'] = f"Sim Speed: {self.speed_factor:.1f} (eff: {self.speed:.1f} m/s)"

    def check_and_spawn_packages(self, task):
        """
        Überprüft alle Annahmestationen: falls an einer Station kein Paket vorhanden
        und die simulierte Wartezeit (Basis 1 Sekunde) vergangen ist, wird ein Paket erzeugt.
        """
        spawn_delay = self.sim_time(1)
        current_time = globalClock.getFrameTime()
        for station in self.annahme_stationen:
            if station not in self.pickup_packages:
                if current_time - self.last_removed.get(station, current_time) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.again

    def spawn_package_at_station(self, station):
        """
        Erzeugt ein Paket (Würfel) an der gegebenen Annahmestation, positioniert es um +1 in Z
        und hängt einen TextNode zur Anzeige der Wartezeit an.
        """
        package = self.erzeuge_wuerfel(station.getX(), station.getY(), station.getZ(), LColor(1, 1, 0, 1))
        spawn_time = globalClock.getFrameTime()
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)
        self.pickup_packages[station] = (package, spawn_time, timer_np)

    def update_package_timers(self, task):
        """
        Aktualisiert in jedem Frame den angezeigten Timer aller wartenden Pakete.
        Hierbei wird die verstrichene Zeit (current_time - spawn_time) mit dem speed_factor
        multipliziert (simulierte Zeit).
        """
        current_time = globalClock.getFrameTime()
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed_sim = (current_time - spawn_time) * self.speed_factor
            tn = timer_np.node()
            tn.setText(f"{elapsed_sim:.1f}s")
        return Task.cont

    def move_vehicle_to(self, vehicle, target, on_complete):
        """
        Bewegt das Fahrzeug dynamisch bis zum Ziel (target). Dabei wird in jedem Frame
        der aktuelle Speed (self.speed) verwendet, sodass Änderungen des Reglers sofort
        wirksam werden. Sobald das Fahrzeug das Ziel erreicht hat, wird on_complete() aufgerufen.
        """

        def move_task(task):
            dt = globalClock.getDt()
            current_pos = vehicle.getPos()
            direction = target - current_pos
            dist = direction.length()
            # Wenn die Distanz kleiner als der Schritt ist, Ziel erreichen.
            if dist <= self.speed * dt:
                vehicle.setPos(target)
                on_complete()
                return Task.done
            else:
                move_step = direction.normalized() * self.speed * dt
                vehicle.setPos(current_pos + move_step)
                return Task.cont

        self.taskMgr.add(move_task, f"move_vehicle_{id(vehicle)}")

    def start_delivery_cycle(self, vehicle, start_pos=None):
        """
        Führt für ein Fahrzeug den Liefervorgang aus (alle Wartezeiten werden mittels sim_time skaliert):
          1. Wählt das älteste Paket (basierend auf simulierten Wartezeiten), sofern its Pickup-Station frei ist.
          2. Reserviert die Pickup-Station, fährt dorthin und übergibt das Paket.
          3. Wählt dann zufällig eine freie Abgabestation, reserviert sie und fährt dorthin.
          4. Nach einer simulierten Wartezeit von 1 Sekunde wird das Paket abgesetzt,
             die Reservierungen aufgehoben und der nächste Zyklus gestartet.
        """
        if start_pos is None:
            start_pos = vehicle.getPos()

        if not self.pickup_packages:
            self.taskMgr.doMethodLater(self.sim_time(1),
                                       lambda t: self.start_delivery_cycle(vehicle, vehicle.getPos()),
                                       "RetryCycle_" + str(id(vehicle)))
            return

        current_time = globalClock.getFrameTime()
        available_pickups = [s for s in self.pickup_packages.keys() if s not in self.occupied_pickups]
        if not available_pickups:
            self.taskMgr.doMethodLater(self.sim_time(1),
                                       lambda t: self.start_delivery_cycle(vehicle, vehicle.getPos()),
                                       "RetryCycle_" + str(id(vehicle)))
            return

        pickup_station = max(available_pickups, key=lambda s: current_time - self.pickup_packages[s][1])
        self.occupied_pickups.add(pickup_station)
        pickup_pos = pickup_station.getPos()

        available_dropoffs = [ds for ds in self.abgabe_stationen if ds not in self.occupied_dropoffs]
        if not available_dropoffs:
            self.occupied_pickups.remove(pickup_station)
            self.taskMgr.doMethodLater(self.sim_time(1),
                                       lambda t: self.start_delivery_cycle(vehicle, vehicle.getPos()),
                                       "RetryCycle_" + str(id(vehicle)))
            return

        dropoff_station = random.choice(available_dropoffs)
        self.occupied_dropoffs.add(dropoff_station)
        self.current_dropoffs[vehicle] = dropoff_station
        dropoff_pos = dropoff_station.getPos()

        # Jetzt: bewege das Fahrzeug zuerst zur Pickup-Station, dann zur Abgabestation.
        self.move_vehicle_to(vehicle, pickup_pos, lambda: self.after_pickup(vehicle, pickup_station, dropoff_pos))

    def after_pickup(self, vehicle, pickup_station, dropoff_pos):
        """
        Wird aufgerufen, sobald das Fahrzeug die Pickup-Station erreicht hat.
        Übergibt das Paket und startet die Bewegung zur Abgabestation.
        """
        self.pickup_package(vehicle, pickup_station)
        self.move_vehicle_to(vehicle, dropoff_pos, lambda: self.after_dropoff(vehicle))

    def after_dropoff(self, vehicle):
        """
        Nachdem das Fahrzeug die Abgabestation erreicht hat, wird das Paket abgesetzt.
        Nach einer simulierten Wartezeit von 1 Sekunde wird das Fahrzeug bereit gemacht
        für den nächsten Lieferzyklus.
        """
        self.drop_cargo(vehicle)
        self.taskMgr.doMethodLater(self.sim_time(1),
                                   lambda t: self.finish_cycle(vehicle),
                                   f"FinishCycle_{id(vehicle)}")

    def finish_cycle(self, vehicle):
        """
        Nach dem Absetzen des Pakets wird das Paket entfernt und der nächste Zyklus gestartet.
        """
        self.remove_cargo(vehicle)
        self.start_delivery_cycle(vehicle, vehicle.getPos())

    def pickup_package(self, vehicle, station):
        """
        Das Fahrzeug übernimmt an der Pickup-Station das Paket.
        Entfernt den Timer-Text, löscht den Eintrag aus dem Pickup-Pool, aktualisiert den Zeitpunkt
        und hebt die Pickup-Reservierung auf.
        """
        if station in self.pickup_packages:
            package, spawn_time, timer_np = self.pickup_packages.pop(station)
            timer_np.removeNode()
            package.wrtReparentTo(vehicle)
            package.setPos(0, 0, 1)
            self.cargos[vehicle] = package
            self.last_removed[station] = globalClock.getFrameTime()
            if station in self.occupied_pickups:
                self.occupied_pickups.remove(station)

    def drop_cargo(self, vehicle):
        """
        Das transportierte Paket wird an der reservierten Abgabestation (Z+1) abgesetzt.
        """
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.wrtReparentTo(self.render)
            targetPos = self.current_dropoffs[vehicle].getPos() + Vec3(0, 0, 1)
            cargo.setPos(targetPos)

    def remove_cargo(self, vehicle):
        """
        Entfernt das aktuell transportierte Paket und gibt die reservierte Abgabestation frei.
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
