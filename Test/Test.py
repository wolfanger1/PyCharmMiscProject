import random
import math
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData,
    GeomNode, GeomVertexWriter, GeomLines, Geom, Vec3
)
from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
import random
import math
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData,
    GeomNode, GeomVertexWriter, GeomLines, Geom, Vec3
)
from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
from direct.interval.IntervalGlobal import Sequence, Wait, LerpPosInterval, Func, Parallel


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Fahrzeuggeschwindigkeit: 1.5 m/s * 5 = 7.5 m/s
        self.speed = 1.5 * 5
        self.cam.setPos(0, -60, 30)
        self.cam.lookAt(0, 0, 0)

        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=40, cell_size=1)

        # Erzeuge 5 Annahme- (rot) und 5 Abgabe-Stationen (grün)
        # in einer Linie mit gleichem Abstand.
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

        self.cargo = None  # Aktuell transportiertes Paket
        self.start_delivery_cycle()  # Start des ersten Lieferzyklus

    def start_delivery_cycle(self, start_pos=None):
        """
        Ablauf dieses Zyklus:
        1. Das Fahrzeug fährt vom aktuellen Punkt (start_pos) zur ausgewählten Annahmestation.
        2. Unabhängig davon wird nach 1 Sekunde das Paket (als Würfel) an der Annahmestation erzeugt.
           (Das Paket erscheint also auch, wenn das Fahrzeug noch nicht da ist.)
        3. Sobald das Fahrzeug am Annahmestation-Punkt angekommen ist, wird das (evtl. schon
           vorhandene) Paket als Kind des Fahrzeugs angebracht.
        4. Anschließend fährt das Fahrzeug zur zufällig gewählten Abgabestation, das Paket wird
           dort auf den Würfel der Abgabestation gesetzt; nach 1 Sekunde wird es entfernt.
        5. Der nächste Zyklus startet ab der aktuellen Position (der Abgabestation).
        """
        if start_pos is None:
            start_pos = self.vehicle.getPos()

        # Zufällige Auswahl einer Annahmestation
        idx = random.randrange(len(self.annahme_stationen))
        pickup_station = self.annahme_stationen[idx]
        redPos = pickup_station.getPos()
        seg1_duration = (redPos - start_pos).length() / self.speed

        # Zufällige Auswahl einer Abgabestation
        dropoff_station = random.choice(self.abgabe_stationen)
        self.current_dropoff_station = dropoff_station  # Zum späteren Setzen des Pakets
        greenPos = dropoff_station.getPos()
        seg2_duration = (greenPos - redPos).length() / self.speed

        cycle = Sequence(
            # Parallel: Das Fahrzeug fährt zur Annahmestation und in einer separaten Sequenz
            # erscheint das Paket an der Station (nach 1 Sekunde), unabhängig vom Fahrzeug.
            Parallel(
                LerpPosInterval(self.vehicle, duration=seg1_duration, pos=redPos),
                Sequence(Wait(1), Func(self.spawn_cargo, redPos))
            ),
            # Nachdem das Fahrzeug am Annahmestation-Punkt ist, wird das Paket aufgenommen.
            Func(self.attach_cargo_to_vehicle),
            # Fahrt zur Abgabestation
            LerpPosInterval(self.vehicle, duration=seg2_duration, pos=greenPos),
            Func(self.drop_cargo),
            Wait(1),  # Nach 1 Sekunde an der Abgabestation verschwindet das Paket.
            Func(self.remove_cargo),
            # Starte den nächsten Zyklus ab der aktuellen Position (Abgabestation)
            Func(self.start_delivery_cycle, self.vehicle.getPos())
        )
        cycle.start()

    def spawn_cargo(self, pos):
        # Erzeugt ein neues Paket (Würfel) an der angegebenen Position.
        if self.cargo:
            self.cargo.removeNode()
        self.cargo = self.erzeuge_wuerfel(pos.getX(), pos.getY(), pos.getZ(), LColor(1, 1, 0, 1))

    def attach_cargo_to_vehicle(self):
        # Hängt das Paket als Kind des Fahrzeugs an, damit es mitbewegt wird.
        self.cargo.wrtReparentTo(self.vehicle)
        self.cargo.setPos(0, 0, 1)

    def drop_cargo(self):
        # Setzt das Paket exakt auf den Würfel der Abgabestation (Z-Offset +1).
        self.cargo.wrtReparentTo(self.render)
        targetPos = self.current_dropoff_station.getPos() + Vec3(0, 0, 1)
        self.cargo.setPos(targetPos)

    def remove_cargo(self):
        # Entfernt das Paket endgültig aus der Szene.
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
        # Erzeugt ein Wireframe-Box-Modell als Station.
        gitterbox = self.loader.loadModel("models/box")
        gitterbox.setScale(1, 1, 1)
        gitterbox.setPos(x, y, z)
        gitterbox.setColor(farbe)
        gitterbox.setRenderMode(RenderModeAttrib.MWireframe, 1)
        gitterbox.reparentTo(self.render)
        return gitterbox

    def erzeuge_wuerfel(self, x, y, z, farbe):
        # Erzeugt einen Würfel (als Paket), etwas über dem Boden positioniert.
        wuerfel = self.loader.loadModel("models/box")
        wuerfel.setScale(1, 1, 1)
        wuerfel.setPos(x, y, z + 1)
        wuerfel.setColor(farbe)
        wuerfel.reparentTo(self.render)
        return wuerfel

    def erzeuge_licht(self):
        # Einfaches Beleuchtungssetup: Ambient- und Richtungslicht.
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

