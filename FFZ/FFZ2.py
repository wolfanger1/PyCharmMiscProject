from panda3d.core import (
    LColor,
    GeomVertexFormat,
    GeomVertexData,
    GeomVertexWriter,
    GeomLines,
    GeomTriangles,
    Geom,
    GeomNode,
    ClockObject,
    AmbientLight,
    DirectionalLight
)
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel


class SimpleSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Initialwerte für Simulationszeit und -geschwindigkeit
        self.sim_clock = 0.0
        self.speed_factor = 1.0

        # Kameraeinstellungen: Wir positionieren die Kamera so, dass das Fahrzeug gut sichtbar ist.
        # Es wird angenommen, dass die Fahrtrichtung entlang der Y-Achse (positiv) verläuft.
        self.cam.setPos(0, -30, 10)
        self.cam.lookAt(0, 0, 0)

        # Licht und Raster (Raster-Zellen: 0.1 x 0.1)
        self.setup_light()
        self.create_grid(center_extent=10, cell_size=0.1)

        # Fahrzeug erstellen
        self.create_vehicle()

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

        # Anzeige der Laufzeit
        self.info_label = DirectLabel(
            text="Laufzeit: 0.0s",
            pos=(1.2, 0, 0.8),
            scale=0.07,
            frameColor=(0, 0, 0, 0)
        )

        # Zoom-Funktionalität: Mausrad heran-/herauszoomen
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)

        # Aufgaben zur Aktualisierung der Simulationszeit und Anzeige
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")

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

    def create_grid(self, center_extent=40, cell_size=1):
        """
        Erstellt ein Raster in der XY-Ebene mit einer Zellengröße,
        wobei Z=0 der Boden ist.
        """
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
            writer.addData3f(min_line, y, 0)
            writer.addData3f(max_line, y, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            lines.closePrimitive()
            n_vertices += 2
            y += cell_size

        # Vertikale Linien
        x = min_line
        while x <= max_line:
            writer.addData3f(x, min_line, 0)
            writer.addData3f(x, max_line, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            lines.closePrimitive()
            n_vertices += 2
            x += cell_size

        geom = Geom(vdata)
        geom.addPrimitive(lines)
        node = GeomNode("grid")
        node.addGeom(geom)
        grid_np = self.render.attachNewNode(node)
        grid_np.setColor(0.7, 0.7, 0.7, 1)
        return grid_np

    def setup_light(self):
        ambient_light = AmbientLight("ambient_light")
        ambient_light.setColor((0.5, 0.5, 0.5, 1))
        ambient_np = self.render.attachNewNode(ambient_light)
        self.render.setLight(ambient_np)

        directional_light = DirectionalLight("directional_light")
        directional_light.setColor((1, 1, 1, 1))
        directional_np = self.render.attachNewNode(directional_light)
        directional_np.setPos(10, -10, 10)
        self.render.setLight(directional_np)

    def create_vehicle(self):
        """
        Erzeugt ein fahrerloses Transportfahrzeug als 3D-Modell,
        bestehend aus drei lückenlos verbundenen Modulen:

          • Fahrmodul (Chassis): Größe 1 x 0.5 x 1.2,
            platziert von (0,0,0) bis (1,0.5,1.2).

          • Gabelmodul (Fork): Größe 1 x 1.2 x 0.2,
            wird hinten am Fahrmodul angesetzt.
            (Durch Verschiebung um -1.2 in Y liegt es von y = -1.2 bis 0.)

          • Mast: Größe 1 x 0.1 x 1,
            sitzt oben auf dem Fahrmodul (beginnt bei z = 1.2) und wird in Y zentriert.
        """
        vehicle_node = self.render.attachNewNode("vehicle")

        # Fahrmodul (Chassis) – Farbe: Rot
        box_chassis = self.create_box(1, 0.5, 1.2, (1.0, 0.0, 0.0, 1))
        node_chassis = vehicle_node.attachNewNode(box_chassis)
        node_chassis.setTwoSided(True)
        node_chassis.setPos(0, 0, 0)  # Bereich: x: 0-1, y: 0-0.5, z: 0-1.2

        # Gabelmodul (Fork) – Farbe: Grau, Höhe jetzt 0.2 statt 0.3
        box_fork = self.create_box(1, 1.2, 0.2, (0.3, 0.3, 0.3, 1))
        node_fork = vehicle_node.attachNewNode(box_fork)
        node_fork.setTwoSided(True)
        node_fork.setPos(0, -1.2, 0)  # Bereich: x: 0-1, y: -1.2 bis 0, z: 0-0.2

        # Mast – Farbe: Dunkles Grau (0.2, 0.2, 0.2, 1)
        box_mast = self.create_box(1, 0.1, 1, (0.2, 0.2, 0.2, 1))
        node_mast = vehicle_node.attachNewNode(box_mast)
        node_mast.setTwoSided(True)
        node_mast.setPos(0, 0.2, 1.2)  # Bereich: x: 0-1, y: 0.2-0.3, z: 1.2-2.2

        # Zentriere den gesamten Fahrzeugknoten in X
        vehicle_node.setPos(-0.5, 0, 0)

    def create_box(self, width, depth, height, color):
        """
        Erzeugt einen vollflächigen Quader (Box) mit den Dimensionen:
          - Breite (X): width
          - Tiefe (Y): depth
          - Höhe (Z): height

        Für jede Seite werden eigene Eckpunkte mit korrekten Normalen erzeugt,
        sodass das Objekt wirklich solide wirkt.
        """
        format = GeomVertexFormat.getV3n3cp()
        vdata = GeomVertexData('box', format, Geom.UHStatic)
        vertex = GeomVertexWriter(vdata, 'vertex')
        normal = GeomVertexWriter(vdata, 'normal')
        col = GeomVertexWriter(vdata, 'color')

        # Unterseite (z = 0) mit Normal (0, 0, -1)
        for v in [(0, 0, 0), (width, 0, 0), (width, depth, 0), (0, depth, 0)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, -1)
            col.addData4f(*color)

        # Oberseite (z = height) mit Normal (0, 0, 1)
        for v in [(0, 0, height), (width, 0, height), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, 1)
            col.addData4f(*color)

        # Vorderseite (y = 0) mit Normal (0, -1, 0)
        for v in [(0, 0, 0), (width, 0, 0), (width, 0, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, -1, 0)
            col.addData4f(*color)

        # Rückseite (y = depth) mit Normal (0, 1, 0)
        for v in [(0, depth, 0), (width, depth, 0), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 1, 0)
            col.addData4f(*color)

        # Linke Seite (x = 0) mit Normal (-1, 0, 0)
        for v in [(0, 0, 0), (0, depth, 0), (0, depth, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(-1, 0, 0)
            col.addData4f(*color)

        # Rechte Seite (x = width) mit Normal (1, 0, 0)
        for v in [(width, 0, 0), (width, depth, 0), (width, depth, height), (width, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(1, 0, 0)
            col.addData4f(*color)

        triangles = GeomTriangles(Geom.UHStatic)
        # Jede Seite besteht aus 2 Dreiecken (insgesamt 12 Dreiecke)
        for i in range(6):
            base = i * 4
            triangles.addVertices(base, base + 1, base + 2)
            triangles.closePrimitive()
            triangles.addVertices(base, base + 2, base + 3)
            triangles.closePrimitive()

        geom = Geom(vdata)
        geom.addPrimitive(triangles)
        node = GeomNode("box")
        node.addGeom(geom)
        return node


if __name__ == "__main__":
    app = SimpleSimulation()
    app.run()
