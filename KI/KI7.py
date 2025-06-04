import random
import math
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData, GeomNode,
    GeomVertexWriter, GeomLines, Geom, Vec3, ClockObject, TextNode
)
# Globaler Clock über ClockObject
globalClock = ClockObject.getGlobalClock()

from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
from direct.interval.IntervalGlobal import Sequence, Wait, LerpPosInterval, Func
from direct.task import Task


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Fahrzeuggeschwindigkeit: 1.5 m/s * 5 = 7.5 m/s
        self.speed = 1.5 * 5
        self.cam.setPos(0, -60, 30)
        self.cam.lookAt(0, 0, 0)

        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=40, cell_size=1)

        # Erzeuge 5 Annahme- (rot) und 5 Abgabe-Stationen (grün) in einer Linie (gleicher Abstand)
        station_count = 5
        spacing = 5
        y_start = -((station_count - 1) * spacing) / 2

        self.annahme_stationen = []
        self.abgabe_stationen = []
        for i in range(station_count):
            y = y_start + i * spacing
            # Annahmestation links (rot) bei x = -9
            pickup_station = self.erzeuge_gitterbox(-9, y, 0, LColor(1, 0, 0, 1))
            self.annahme_stationen.append(pickup_station)
            # Abgabestation rechts (grün) bei x = 9
            dropoff_station = self.erzeuge_gitterbox(9, y, 0, LColor(0, 1, 0, 1))
            self.abgabe_stationen.append(dropoff_station)

        # Fahrzeuge initialisieren – wir erzeugen zwei Fahrzeuge.
        self.vehicles = []
        self.cargos = {}             # Dictionary: Fahrzeug -> aktuell transportiertes Paket
        self.current_dropoffs = {}   # Dictionary: Fahrzeug -> aktuelle Abgabestation

        # Fahrzeug 1
        vehicle1 = self.loader.loadModel("models/box")
        vehicle1.setScale(1, 1, 0.5)
        vehicle1.setColor(LColor(0, 0, 1, 1))
        vehicle1.setPos(0, 0, 0)
        vehicle1.reparentTo(self.render)
        self.vehicles.append(vehicle1)

        # Fahrzeug 2 – leicht versetzt, damit die Modelle nicht exakt übereinander liegen.
        vehicle2 = self.loader.loadModel("models/box")
        vehicle2.setScale(1, 1, 0.5)
        vehicle2.setColor(LColor(0, 0, 0.8, 1))
        vehicle2.setPos(0, 2, 0)  # y-Offset von 2 Einheiten
        vehicle2.reparentTo(self.render)
        self.vehicles.append(vehicle2)

        # Globaler Pool für alle Pickup-Pakete:
        # Schlüssel = Annahmestation, Wert = (Paket, Spawnzeit, Timer-TextNode)
        self.pickup_packages = {}
        # Für jede Station wird der Zeitpunkt des letzten Entfernens initialisiert.
        self.last_removed = {}
        for station in self.annahme_stationen:
            self.last_removed[station] = globalClock.getFrameTime()

        # Starte einen Task, der regelmäßig prüft, ob an einer Annahmestation ein Paket fehlen soll.
        self.taskMgr.doMethodLater(1, self.check_and_spawn_packages, "CheckSpawnPackages")
        # Task zum Aktualisieren der Timer-Anzeige über den Paketen.
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimers")

        # Starte für jedes Fahrzeug einen eigenen, unabhängigen Lieferzyklus.
        for v in self.vehicles:
            self.start_delivery_cycle(v, v.getPos())

    def check_and_spawn_packages(self, task):
        """
        Überprüft alle Annahmestationen:
        Falls an einer Station noch kein Paket vorhanden ist und seit dem letzten Entfernen
        mindestens 5 Sekunden vergangen sind, wird ein Paket erzeugt.
        """
        spawn_delay = 5  # 5 Sekunden Wartezeit pro Station
        current_time = globalClock.getFrameTime()
        for station in self.annahme_stationen:
            if station not in self.pickup_packages:
                if current_time - self.last_removed.get(station, current_time) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.again

    def spawn_package_at_station(self, station):
        """
        Erzeugt ein Paket (als Würfel) an der gegebenen Annahmestation.
        Das Paket wird um +1 in Z positioniert. Zudem wird ein TextNode über dem Paket
        zur Timer-Anzeige angehängt. Die Tuple (Paket, Spawnzeit, Timer-TextNode) wird im
        globalen Pickup-Pool gespeichert.
        """
        package = self.erzeuge_wuerfel(station.getX(), station.getY(), station.getZ(),
                                        LColor(1, 1, 0, 1))
        spawn_time = globalClock.getFrameTime()
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)
        self.pickup_packages[station] = (package, spawn_time, timer_np)

    def update_package_timers(self, task):
        """
        Aktualisiert in jedem Frame den Text (Wartezeit) aller wartenden Pakete.
        """
        current_time = globalClock.getFrameTime()
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = current_time - spawn_time
            tn = timer_np.node()
            tn.setText(f"{elapsed:.1f}s")
        return Task.cont

    def start_delivery_cycle(self, vehicle, start_pos=None):
        """
        Liefert für ein einzelnes Fahrzeug folgenden Ablauf:
          1. Ist der globale Pool der Pickup-Pakete nicht leer, wählt das Fahrzeug das Paket
             mit der höchsten Wartezeit (also das älteste, gemessen an der Spawnzeit).
          2. Das Fahrzeug fährt zur entsprechenden Annahmestation, nimmt das Paket auf,
             wählt zufällig eine Abgabestation und liefert das Paket dort ab.
          3. Nach 1 Sekunde wird das Paket entfernt und der nächste Auftrag
             startet – unabhängig von anderen Fahrzeugen.
        """
        if start_pos is None:
            start_pos = vehicle.getPos()

        if not self.pickup_packages:
            self.taskMgr.doMethodLater(1,
                lambda t: self.start_delivery_cycle(vehicle, vehicle.getPos()),
                "RetryCycle_" + str(id(vehicle)))
            return

        current_time = globalClock.getFrameTime()
        # Jedes Fahrzeug wählt das Paket mit der höchsten Wartezeit aus dem globalen Pool.
        pickup_station = max(self.pickup_packages, key=lambda s: current_time - self.pickup_packages[s][1])
        pickup_pos = pickup_station.getPos()
        seg1_duration = (pickup_pos - start_pos).length() / self.speed

        # Zufällige Auswahl einer Abgabestation.
        dropoff_station = random.choice(self.abgabe_stationen)
        self.current_dropoffs[vehicle] = dropoff_station
        dropoff_pos = dropoff_station.getPos()
        seg2_duration = (dropoff_pos - pickup_pos).length() / self.speed

        cycle = Sequence(
            LerpPosInterval(vehicle, duration=seg1_duration, pos=pickup_pos),
            Func(self.pickup_package, vehicle, pickup_station),
            LerpPosInterval(vehicle, duration=seg2_duration, pos=dropoff_pos),
            Func(self.drop_cargo, vehicle),
            Wait(1),
            Func(self.remove_cargo, vehicle),
            Func(self.start_delivery_cycle, vehicle, vehicle.getPos())
        )
        cycle.start()

    def pickup_package(self, vehicle, station):
        """
        Das Fahrzeug übernimmt das Paket der angegebenen Annahmestation.
        Dabei wird der Timer-Text entfernt, das Paket aus dem globalen Pool gelöscht
        und der Zeitpunkt der Entfernung in last_removed aktualisiert.
        """
        if station in self.pickup_packages:
            package, spawn_time, timer_np = self.pickup_packages.pop(station)
            timer_np.removeNode()
            package.wrtReparentTo(vehicle)
            package.setPos(0, 0, 1)
            self.cargos[vehicle] = package
            self.last_removed[station] = globalClock.getFrameTime()

    def drop_cargo(self, vehicle):
        """
        Das vom Fahrzeug transportierte Paket wird exakt auf den Würfel der
        (zufällig ausgewählten) Abgabestation (mit Z-Offset +1) abgesetzt.
        """
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.wrtReparentTo(self.render)
            targetPos = self.current_dropoffs[vehicle].getPos() + Vec3(0, 0, 1)
            cargo.setPos(targetPos)

    def remove_cargo(self, vehicle):
        """
        Entfernt das aktuell transportierte Paket des Fahrzeugs aus der Szene.
        """
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.removeNode()
            self.cargos[vehicle] = None

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
        Einfaches Beleuchtungssetup: Ambient- und Richtungslicht.
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
