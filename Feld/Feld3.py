from panda3d.core import (
    LColor,
    GeomVertexFormat,
    GeomVertexData,
    GeomVertexWriter,
    GeomLines,
    Geom,
    GeomNode,
    ClockObject,
    AmbientLight,
    DirectionalLight,
    Vec3,
    LineSegs
)
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel
import math

class SimpleSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Initialwerte für Simulationszeit und -geschwindigkeit
        self.sim_clock = 0.0
        self.speed_factor = 1.0

        # Zeichne den Ursprung (Koordinatenachsen) ein
        self.draw_origin()

        # Kameraeinstellungen: So, dass das gesamte Feld gut sichtbar ist.
        self.cam.setPos(11, -80, 40)
        self.cam.lookAt(11, 30, 0)

        # Erzeuge Licht und Bodenraster
        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=70, cell_size=1)

        # Erzeuge die Mauer (flush, bündig ein Rechteck abschließend)
        # Die vier Eckpunkte: (0,0,0), (0,60,0), (22,60,0) und (22,0,0)
        self.create_wall()

        # Erzeuge Annahmestationen, die an den vorgegebenen Punkten platziert werden.
        self.create_annahme_stations()

        # Slider zur Anpassung der Simulationsgeschwindigkeit
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

        # Anzeige der Kennzahlen (z. B. Laufzeit)
        self.info_label = DirectLabel(
            text="Laufzeit: 0.0s",
            pos=(1.2, 0, 0.8),
            scale=0.07,
            frameColor=(0, 0, 0, 0)
        )

        # Zoom-Funktion: Mit Mausrad hereinz- bzw. herauszoomen.
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)

        # Aufgaben: Simulationszeit fortlaufend aktualisieren.
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")

    def draw_origin(self):
        """Zeichnet die drei Achsen im Ursprung zur Orientierung."""
        ls = LineSegs()
        ls.setThickness(2)
        # X-Achse (rot)
        ls.setColor(LColor(1, 0, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(1, 0, 0)
        # Y-Achse (grün)
        ls.setColor(LColor(0, 1, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 1, 0)
        # Z-Achse (blau)
        ls.setColor(LColor(0, 0, 1, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 0, 1)
        self.render.attachNewNode(ls.create())

    def update_sim_clock(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.sim_clock += dt * self.speed_factor
        return Task.cont

    def update_info_display(self, task):
        total_seconds = self.sim_clock
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        formatted_time = f"{hours}h {minutes}m {seconds:.1f}s"
        self.info_label['text'] = f"Laufzeit: {formatted_time}"
        return Task.cont

    def update_simulation_speed(self, speed_factor=None):
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

    def zoom_in(self):
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = max(10, current_fov - 5)
        lens.setFov(new_fov)
        print(f"Zoom In: FOV von {current_fov} auf {new_fov}")

    def zoom_out(self):
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = min(100, current_fov + 5)
        lens.setFov(new_fov)
        print(f"Zoom Out: FOV von {current_fov} auf {new_fov}")

    def erzeuge_bodenraster(self, center_extent=70, cell_size=1):
        vertex_format = GeomVertexFormat.getV3()
        vdata = GeomVertexData("grid", vertex_format, Geom.UHStatic)
        writer = GeomVertexWriter(vdata, "vertex")
        lines = GeomLines(Geom.UHStatic)
        n_vertices = 0
        min_line = -center_extent - 0.5
        max_line = center_extent + 0.5

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

    def erzeuge_licht(self):
        alight = AmbientLight("ambient_light")
        alight.setColor((0.5, 0.5, 0.5, 1))
        alight_np = self.render.attachNewNode(alight)
        self.render.setLight(alight_np)

        dlight = DirectionalLight("directional_light")
        dlight.setColor((1, 1, 1, 1))
        dlight_np = self.render.attachNewNode(dlight)
        dlight_np.setPos(10, -10, 10)
        self.render.setLight(dlight_np)

    def create_wall(self):
        """
        Erzeugt vier Wandsegmente, die ein Rechteck abschließen.
        Die vier Eckpunkte lauten exakt:
            p1 = (0, 0, 0)
            p2 = (0, 60, 0)
            p3 = (22, 60, 0)
            p4 = (22, 0, 0)
        Der innere Rand der Mauer liegt genau auf diesen Punkten.
        """
        p1 = Vec3(0, 0, 0)
        p2 = Vec3(0, 60, 0)
        p3 = Vec3(22, 60, 0)
        p4 = Vec3(22, 0, 0)
        self.add_wall_segment(p1, p2)
        self.add_wall_segment(p2, p3)
        self.add_wall_segment(p3, p4)
        self.add_wall_segment(p4, p1)

    def add_wall_segment(self, start, end, height=2.0, thickness=0.5):
        """
        Fügt ein Wandsegment hinzu – so, dass dessen innere Kante exakt
        die Verbindung zwischen 'start' und 'end' bildet.
        Die vier Eckpunkte der Mauer werden in Clockwise-Reihenfolge angegeben.
        """
        seg_vector = end - start
        length = seg_vector.length()
        if length == 0:
            return

        d = seg_vector.normalized()
        # Für in Clockwise angegebene Eckpunkte (innerer Bereich rechts) berechnen wir:
        outward = Vec3(-d.getY(), d.getX(), 0)
        center = (start + end) * 0.5 + outward * (thickness / 2.0)
        center.setZ(height / 2.0)
        angle = math.degrees(math.atan2(seg_vector.getY(), seg_vector.getX()))

        wall_np = self.render.attachNewNode("wall_np")
        wall = self.loader.loadModel("models/box")
        # Pivot-Korrektur: Zentriere das Modell anhand der TightBounds.
        bounds = wall.getTightBounds()
        if bounds:
            low, high = bounds
            box_center = (low + high) * 0.5
            wall.setPos(-box_center)
        wall.reparentTo(wall_np)

        wall_np.setScale(length, thickness, height)
        wall_np.setPos(center)
        wall_np.setH(angle)
        wall_np.setTextureOff(1)
        wall_np.setColor(LColor(0.5, 0.5, 0.5, 1))

    def create_annahme_station(self, pos):
        """
        Erzeugt eine Annahmestation als 1×1×1-Würfel aus Linien (Gitter) in Grün.
        Die Seite in positiver X-Richtung (x = 1) bleibt geöffnet.
        'pos' wird als untere linke Ecke des Würfels verwendet.
        """
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(0, 1, 0, 1))
        # Lokale Eckpunkte des Würfels relativ zu pos:
        v0 = pos + Vec3(0, 0, 0)   # unten, links, hinten
        v1 = pos + Vec3(1, 0, 0)   # unten, rechts, hinten
        v2 = pos + Vec3(1, 1, 0)   # unten, rechts, vorne
        v3 = pos + Vec3(0, 1, 0)   # unten, links, vorne
        v4 = pos + Vec3(0, 0, 1)   # oben, links, hinten
        v5 = pos + Vec3(1, 0, 1)   # oben, rechts, hinten
        v6 = pos + Vec3(1, 1, 1)   # oben, rechts, vorne
        v7 = pos + Vec3(0, 1, 1)   # oben, links, vorne

        # Zeichne die Kanten des unteren Quadrats (z=0)
        ls.moveTo(v0)
        ls.drawTo(v1)    # v0->v1 (wird gezeichnet, da nur einer Endpoint x=1 ist)
        # v1->v2: beide Punkte haben x==1 → diese Kante bleibt offen
        ls.moveTo(v2)
        ls.drawTo(v3)    # v2->v3
        ls.moveTo(v3)
        ls.drawTo(v0)    # v3->v0

        # Zeichne die Kanten des oberen Quadrats (z=1)
        ls.moveTo(v4)
        ls.drawTo(v5)    # v4->v5 (wird gezeichnet, da v4.x=0, v5.x=1)
        # v5->v6: beide Punkte haben x==1 → diese Kante wird weggelassen
        ls.moveTo(v6)
        ls.drawTo(v7)    # v6->v7
        ls.moveTo(v7)
        ls.drawTo(v4)    # v7->v4

        # Zeichne die vertikalen Kanten (nur die, bei denen nicht beide Enden x==1 sind)
        ls.moveTo(v0)
        ls.drawTo(v4)    # v0->v4
        ls.moveTo(v3)
        ls.drawTo(v7)    # v3->v7

        return self.render.attachNewNode(ls.create())

    def create_annahme_stations(self):
        """
        Platziert Annahmestationen an den vorgegebenen Positionen:
          (1, 5, 0), (1, 10, 0), (1, 15, 0), (1, 20, 0), (1, 25, 0),
          (1, 30, 0), (1, 35, 0), (1, 40, 0), (1, 45, 0) und (1, 50, 0).
        """
        station_points = [
            Vec3(1, 5, 0), Vec3(1, 10, 0), Vec3(1, 15, 0),
            Vec3(1, 20, 0), Vec3(1, 25, 0), Vec3(1, 30, 0),
            Vec3(1, 35, 0), Vec3(1, 40, 0), Vec3(1, 45, 0),
            Vec3(1, 50, 0)
        ]
        for pt in station_points:
            self.create_annahme_station(pt)

if __name__ == "__main__":
    app = SimpleSimulation()
    app.run()
