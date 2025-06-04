import random
import math
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData,
    GeomNode, GeomVertexWriter, GeomLines, Geom, Vec3, ClockObject, TextNode
)

# Hol den globalen Clock über ClockObject (so funktioniert es in Panda3D)
globalClock = ClockObject.getGlobalClock()

from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
from direct.interval.IntervalGlobal import Sequence, Wait, LerpPosInterval, Func
from direct.task import Task


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Fahrzeuggeschwindigkeit: Ursprünglich 1.5 m/s, um den Faktor 5 erhöht → 7.5 m/s
        self.speed = 1.5 * 5
        self.cam.setPos(0, -60, 30)
        self.cam.lookAt(0, 0, 0)

        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=40, cell_size=1)

        # Erzeuge 5 Annahme- (rot) und 5 Abgabe-Stationen (grün) in einer Linie mit gleichem Abstand.
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

        # Fahrzeug initialisieren
        self.vehicle = self.loader.loadModel("models/box")
        self.vehicle.setScale(1, 1, 0.5)
        self.vehicle.setColor(LColor(0, 0, 1, 1))
        self.vehicle.setPos(0, 0, 0)
        self.vehicle.reparentTo(self.render)

        self.cargo = None  # Das aktuell transportierte Paket
        # Dictionary für alle Pickup-Pakete:
        # Schlüssel = Pickup-Station, Wert = (Paket, Spawnzeit, TextNode)
        self.pickup_packages = {}

        # Starte einen Task, der regelmäßig prüft, ob an einer Annahmestation ein Paket fehlt.
        self.taskMgr.doMethodLater(5, self.check_and_spawn_packages, "CheckSpawnPackages")
        # Task zum Aktualisieren der angezeigten Wartezeit für alle wartenden Pakete.
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimers")

        # Start des ersten Lieferzyklus
        self.start_delivery_cycle()

    def check_and_spawn_packages(self, task):
        """
        Für jede Annahmestation wird geprüft, ob bereits ein Paket vorhanden ist.
        Falls nicht, wird an dieser Station (mit Spawnzeit = globalClock.getFrameTime())
        ein Paket erzeugt.
        """
        for station in self.annahme_stationen:
            if station not in self.pickup_packages:
                self.spawn_package_at_station(station)
        return Task.again

    def spawn_package_at_station(self, station):
        """
        Erzeugt ein Paket (als Würfel) an der gegebenen Station.
        Das Paket wird an die Position der Station (mit einem Z-Offset von +1)
        gesetzt. Zusätzlich wird ein TextNode oberhalb des Pakets erstellt,
        der später die verstrichene Zeit anzeigt. Anschließend wird im Dictionary
        der Station das Tuple (Paket, Spawnzeit, TextNode) abgelegt.
        """
        package = self.erzeuge_wuerfel(station.getX(), station.getY(), station.getZ(), LColor(1, 1, 0, 1))
        spawn_time = globalClock.getFrameTime()

        # Erzeuge einen TextNode zur Anzeige der Wartezeit
        timer_text_node = TextNode("package_timer")
        timer_text_node.setText("0.0s")
        timer_np = package.attachNewNode(timer_text_node)
        timer_np.setScale(0.5)
        # Positioniere den Text etwas oberhalb des Pakets (das Paket wird mit Z+1 gesetzt)
        timer_np.setPos(0, 0, 1.2)

        self.pickup_packages[station] = (package, spawn_time, timer_np)

    def update_package_timers(self, task):
        """
        Aktualisiert den Text aller wartenden Pakete, sodass über jedem Paket
        die aktuelle Wartezeit angezeigt wird.
        """
        current_time = globalClock.getFrameTime()
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = current_time - spawn_time
            tn = timer_np.node()
            tn.setText(f"{elapsed:.1f}s")
        return Task.cont

    def start_delivery_cycle(self, start_pos=None):
        """
        Ablauf:
          1. Das Fahrzeug startet vom aktuellen Punkt (start_pos)
             und sucht unter allen Annahmestationen das Paket, welches am längsten wartet.
          2. Das Fahrzeug fährt zu dieser Annahmestation und nimmt das Paket auf.
          3. Anschließend wird zufällig eine Abgabestation gewählt, zu der das Fahrzeug fährt.
          4. Dort wird das Paket auf den Würfel der Abgabestation gesetzt; nach 1 Sekunde
             wird es entfernt.
          5. Der nächste Zyklus startet ab der aktuellen Position (der Abgabestation).
        """
        if start_pos is None:
            start_pos = self.vehicle.getPos()

        # Falls gerade keine Pakete existieren, kurz warten.
        if not self.pickup_packages:
            self.taskMgr.doMethodLater(1, lambda t: self.start_delivery_cycle(start_pos), "RetryCycle")
            return

        # Auswahl der Annahmestation mit dem ältesten Paket (kleinster Spawnzeitwert)
        pickup_station = min(self.pickup_packages, key=lambda s: self.pickup_packages[s][1])
        pickup_pos = pickup_station.getPos()
        seg1_duration = (pickup_pos - start_pos).length() / self.speed

        # Zufällige Auswahl einer Abgabestation
        dropoff_station = random.choice(self.abgabe_stationen)
        self.current_dropoff_station = dropoff_station  # Für drop_cargo()
        dropoff_pos = dropoff_station.getPos()
        seg2_duration = (dropoff_pos - pickup_pos).length() / self.speed

        cycle = Sequence(
            # Fahrt zur Annahmestation (Pickup-Station, bei der das älteste Paket liegt)
            LerpPosInterval(self.vehicle, duration=seg1_duration, pos=pickup_pos),
            # Nach der Ankunft: Paket vom Pickup-Punkt aufnehmen
            Func(self.pickup_package, pickup_station),
            # Fahrt zur zufällig ausgewählten Abgabestation
            LerpPosInterval(self.vehicle, duration=seg2_duration, pos=dropoff_pos),
            Func(self.drop_cargo),
            Wait(1),
            Func(self.remove_cargo),
            # Starte nächsten Zyklus von der aktuellen Position aus (Abgabestation)
            Func(self.start_delivery_cycle, self.vehicle.getPos())
        )
        cycle.start()

    def pickup_package(self, station):
        """
        Nimmt das an der gegebenen Pickup-Station wartende Paket vom Boden und hängt es
        als Kind des Fahrzeugs an. Gleichzeitig wird der Eintrag aus dem Dictionary entfernt
        und der zugehörige Timer-Text gelöscht.
        """
        if station in self.pickup_packages:
            package, spawn_time, timer_np = self.pickup_packages.pop(station)
            # Entferne den Timer-Text, da das Paket abgeholt wurde
            timer_np.removeNode()
            package.wrtReparentTo(self.vehicle)
            package.setPos(0, 0, 1)
            self.cargo = package

    def drop_cargo(self):
        """
        Setzt das Paket exakt auf den Würfel der (zufällig ausgewählten) Abgabestation
        (Z-Offset +1).
        """
        self.cargo.wrtReparentTo(self.render)
        targetPos = self.current_dropoff_station.getPos() + Vec3(0, 0, 1)
        self.cargo.setPos(targetPos)

    def remove_cargo(self):
        """
        Entfernt das aktuell transportierte Paket aus der Szene.
        """
        if self.cargo:
            self.cargo.removeNode()
            self.cargo = None

    def erzeuge_bodenraster(self, center_extent=40, cell_size=1):
        vertex_format = GeomVertexFormat.getV3()
        vdata = GeomVertexData("grid", vertex_format, Geom.UHStatic)
        writer = GeomVertexWriter(vdata, "vertex")
        lines = GeomLines(Geom.UHStatic)
        n_vertices = 0

        min_line, max_line = -center_extent - 0.5, center_extent + 0.5

        # Horizontale Linien
        y = min_line
        while y <= max_line:
            writer.addData3(min_line, y, 0)
            writer.addData3(max_line, y, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            y += cell_size

        # Vertikale Linien
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
